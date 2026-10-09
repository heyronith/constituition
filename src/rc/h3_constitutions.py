"""Build H3 installed constitutions from main-run chains (D50/D52/D66)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rc.battery import (
    build_validation_constitution,
    constitution_system_prompt,
    inverted_rewrite_map,
)
from rc.config import repo_root
from rc.io_utils import sha256_bytes
from rc.materials import HiddenMeta, LineageRecord, Principle, build_initial_constitution

SwapCategory = Literal["COR", "AGENT"]
ConstitutionType = Literal[
    "R0", "R20", "COR_SWAP", "AGENT_SWAP", "NONE", "COR_INV", "AGENT_INV"
]

H3_CONDITIONS = ("SELF_REFLECT", "OTHER_REFLECT")
H3_CHAINS = (0, 1, 2, 3, 4)
PROTOCOL = "FORCED"
FMT = "STRUCTURED"


@dataclass
class TipState:
    """Final tip of a round-0 clause after lineage through r_final."""

    tip_id: str | None
    text: str | None
    deleted: bool
    absorbed_partner_ids: set[str]


def chain_dir(
    run_tag: str,
    config_id: str,
    condition: str,
    chain_idx: int,
    *,
    root: Path | None = None,
) -> Path:
    root = root or repo_root()
    return (
        root
        / "runs"
        / run_tag
        / config_id
        / PROTOCOL
        / condition
        / FMT
        / f"chain_{chain_idx}"
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_chain_bundle(
    run_tag: str,
    config_id: str,
    condition: str,
    chain_idx: int,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load meta, constitutions, lineage for one chain."""
    cdir = chain_dir(run_tag, config_id, condition, chain_idx, root=root)
    meta_path = cdir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing chain meta: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cons_rows = _load_jsonl(cdir / "constitutions.jsonl")
    lin_rows = _load_jsonl(cdir / "lineage.jsonl")
    if not cons_rows:
        raise FileNotFoundError(f"missing constitutions: {cdir}")
    by_round = {int(r["round"]): r for r in cons_rows}
    r0 = by_round[0]
    # D66: censored → last valid constitution is "final".
    cens = meta.get("censored_at_round")
    if cens is not None:
        r_final = max(int(r) for r in by_round if int(r) <= int(cens))
    else:
        r_final = max(int(r) for r in by_round)
    r_final_row = by_round[r_final]
    lineage = [
        LineageRecord(
            round=int(r["round"]),
            opaque_id=str(r["opaque_id"]),
            parent_ids=list(r.get("parent_ids") or []),
            decision=r.get("decision"),
            merge_with=r.get("merge_with"),
            before_text=r.get("before_text"),
            after_text=r.get("after_text"),
            flags=list(r.get("flags") or []),
            item_id=r.get("item_id"),
            category=r.get("category"),
        )
        for r in lin_rows
    ]
    return {
        "meta": meta,
        "r0": r0,
        "r_final": r_final,
        "r_final_row": r_final_row,
        "lineage": lineage,
        "censored_at_round": cens,
        "path": str(cdir),
    }


def _meta_map(cons_row: dict[str, Any]) -> dict[str, HiddenMeta]:
    out: dict[str, HiddenMeta] = {}
    for oid, m in (cons_row.get("metadata") or {}).items():
        out[str(oid)] = HiddenMeta(
            item_id=str(m["item_id"]),
            category=str(m["category"]),
            form=m.get("form"),
        )
    return out


def _principles(cons_row: dict[str, Any]) -> list[Principle]:
    return [
        Principle(opaque_id=str(p["opaque_id"]), text=str(p["text"]))
        for p in cons_row["principles"]
    ]


def resolve_tip(
    round0_id: str,
    lineage: list[LineageRecord],
    *,
    r_final: int,
    final_texts: dict[str, str],
) -> TipState:
    """Follow keep/revise/merge/delete to the tip at r_final.

    FORCED merge writes two rows (``apply_forced``): the survivor keeps
    ``decision="merge"`` with ``after_text`` set, and the absorbed partner is a
    stub with ``after_text=None``. Only the stub redirects ``current``; the
    survivor stays put and harvests co-parents from ``parent_ids`` (same as
    PERMISSIVE survivor ``revise`` rows).
    """
    current = round0_id
    deleted = False
    absorbed: set[str] = set()
    for rec in sorted(lineage, key=lambda r: (r.round, r.opaque_id)):
        if rec.round <= 0 or rec.round > r_final:
            continue
        if rec.decision == "delete" and rec.opaque_id == current:
            deleted = True
            break
        if rec.decision == "merge" and rec.opaque_id == current:
            # Absorbed stub: after_text is None; redirect to survivor.
            if rec.after_text is None and rec.merge_with:
                absorbed.add(rec.opaque_id)
                current = str(rec.merge_with)
                continue
            # Survivor merge row (FORCED): stay on id; record absorbed partners.
            for pid in rec.parent_ids:
                if pid != current:
                    absorbed.add(str(pid))
            if rec.merge_with:
                absorbed.add(str(rec.merge_with))
            continue
        if rec.decision in {"keep", "revise"} and rec.opaque_id == current:
            # Survivors that absorbed others list them in parent_ids.
            for pid in rec.parent_ids:
                if pid != current:
                    absorbed.add(str(pid))
    if deleted:
        return TipState(tip_id=None, text=None, deleted=True, absorbed_partner_ids=absorbed)
    text = final_texts.get(current)
    if text is None:
        # Tip id missing from final row (should not happen unless delete missed).
        return TipState(tip_id=None, text=None, deleted=True, absorbed_partner_ids=absorbed)
    return TipState(
        tip_id=current, text=text, deleted=False, absorbed_partner_ids=absorbed
    )


def build_category_swap(
    *,
    r0_row: dict[str, Any],
    r_final_row: dict[str, Any],
    lineage: list[LineageRecord],
    r_final: int,
    category: SwapCategory,
) -> tuple[list[str], int, dict[str, Any]]:
    """Return (principle texts, n_changed_vs_r0, debug)."""
    r0_ps = _principles(r0_row)
    r0_meta = _meta_map(r0_row)
    final_texts = {p.opaque_id: p.text for p in _principles(r_final_row)}

    tips: dict[str, TipState] = {}
    drop_r0: set[str] = set()
    for p in r0_ps:
        hid = r0_meta[p.opaque_id]
        if hid.category != category:
            continue
        tip = resolve_tip(p.opaque_id, lineage, r_final=r_final, final_texts=final_texts)
        tips[p.opaque_id] = tip
        if tip.deleted:
            continue
        for pid in tip.absorbed_partner_ids:
            if pid in r0_meta and r0_meta[pid].category != category:
                drop_r0.add(pid)
        # If tip is an original non-category R0 id, drop its verbatim R0 copy.
        if tip.tip_id and tip.tip_id in r0_meta:
            if r0_meta[tip.tip_id].category != category:
                drop_r0.add(tip.tip_id)

    out: list[str] = []
    seen_tips: set[str] = set()
    for p in r0_ps:
        hid = r0_meta[p.opaque_id]
        if hid.category == category:
            tip = tips[p.opaque_id]
            if tip.deleted or tip.tip_id is None or tip.text is None:
                continue
            if tip.tip_id in seen_tips:
                continue
            seen_tips.add(tip.tip_id)
            out.append(tip.text)
        else:
            if p.opaque_id in drop_r0:
                continue
            out.append(p.text)

    r0_texts = [p.text for p in r0_ps]
    n_changed = sum(1 for a, b in zip(out, r0_texts) if a != b) + abs(len(out) - len(r0_texts))
    # Prefer explicit count: clauses whose text differs from R0 positionally is messy
    # when lengths differ; report |set symmetric| style: n_r0 - n_unchanged_r0_slots.
    unchanged = 0
    out_set_counts: dict[str, int] = {}
    for t in out:
        out_set_counts[t] = out_set_counts.get(t, 0) + 1
    for t in r0_texts:
        if out_set_counts.get(t, 0) > 0:
            out_set_counts[t] -= 1
            unchanged += 1
    n_changed = len(r0_texts) - unchanged
    debug = {
        "n_category_r0": sum(1 for p in r0_ps if r0_meta[p.opaque_id].category == category),
        "n_deleted": sum(1 for t in tips.values() if t.deleted),
        "n_drop_r0": len(drop_r0),
        "drop_r0_ids": sorted(drop_r0),
        "n_out": len(out),
    }
    return out, n_changed, debug


def _constitution_id(
    ctype: ConstitutionType,
    *,
    config_id: str,
    condition: str | None,
    chain_idx: int | None,
) -> str:
    if ctype == "NONE":
        return f"{config_id}|NONE"
    if ctype in {"COR_INV", "AGENT_INV"}:
        return f"{config_id}|{ctype}|chain_0"
    assert condition is not None and chain_idx is not None
    return f"{config_id}|{ctype}|{condition}|chain_{chain_idx}"


def build_installed_for_chain(
    run_tag: str,
    config_id: str,
    condition: str,
    chain_idx: int,
    *,
    root: Path | None = None,
    include_r0: bool = True,
) -> list[dict[str, Any]]:
    """Build R0 (optional), R20, COR_SWAP, AGENT_SWAP for one chain."""
    root = root or repo_root()
    bundle = load_chain_bundle(
        run_tag, config_id, condition, chain_idx, root=root
    )
    r0_row = bundle["r0"]
    r_final = int(bundle["r_final"])
    r_final_row = bundle["r_final_row"]
    lineage = bundle["lineage"]
    out: list[dict[str, Any]] = []

    def pack(
        ctype: ConstitutionType,
        texts: list[str],
        *,
        n_changed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cid = _constitution_id(
            ctype, config_id=config_id, condition=condition, chain_idx=chain_idx
        )
        system = constitution_system_prompt(texts) if texts else None
        rec = {
            "constitution_id": cid,
            "config_id": config_id,
            "type": ctype,
            "chain": chain_idx,
            "condition": condition,
            "r_final": r_final,
            "clauses": texts,
            "n_clauses": len(texts),
            "n_changed_vs_r0": n_changed,
            "sha256": sha256_bytes(
                json.dumps({"type": ctype, "clauses": texts}, sort_keys=True).encode()
            ),
            "system_sha256": sha256_bytes((system or "").encode()),
            "censored_at_round": bundle["censored_at_round"],
        }
        if extra:
            rec.update(extra)
        return rec

    r0_texts = [p.text for p in _principles(r0_row)]
    if include_r0:
        # R0 is condition-independent (D17); caller usually builds once from SELF_REFLECT.
        out.append(pack("R0", r0_texts, n_changed=0))

    r20_texts = [p.text for p in _principles(r_final_row)]
    # n_changed vs R0 for R20
    _, n_ch_r20, _ = build_category_swap(
        r0_row=r0_row,
        r_final_row=r_final_row,
        lineage=lineage,
        r_final=r_final,
        category="COR",
    )
    # Count textual diff properly for R20
    out_set: dict[str, int] = {}
    for t in r20_texts:
        out_set[t] = out_set.get(t, 0) + 1
    unchanged = 0
    for t in r0_texts:
        if out_set.get(t, 0) > 0:
            out_set[t] -= 1
            unchanged += 1
    n_ch_r20 = len(r0_texts) - unchanged
    out.append(pack("R20", r20_texts, n_changed=n_ch_r20))

    for cat, ctype in (("COR", "COR_SWAP"), ("AGENT", "AGENT_SWAP")):
        texts, n_ch, dbg = build_category_swap(
            r0_row=r0_row,
            r_final_row=r_final_row,
            lineage=lineage,
            r_final=r_final,
            category=cat,  # type: ignore[arg-type]
        )
        out.append(pack(ctype, texts, n_changed=n_ch, extra={"swap_debug": dbg}))  # type: ignore[arg-type]
    return out


def build_positive_controls(
    config_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    """COR_INV / AGENT_INV from chain-0 R0 materials (D52), not from Volume."""
    root = root or repo_root()
    out: list[dict[str, Any]] = []
    for kind in ("COR_INV", "AGENT_INV"):
        system, meta = build_validation_constitution(
            kind, config_id=config_id, chain_idx=0, root=root  # type: ignore[arg-type]
        )
        texts = list(meta["principle_texts"])
        cid = _constitution_id(kind, config_id=config_id, condition=None, chain_idx=0)  # type: ignore[arg-type]
        out.append(
            {
                "constitution_id": cid,
                "config_id": config_id,
                "type": kind,
                "chain": 0,
                "condition": None,
                "r_final": 0,
                "clauses": texts,
                "n_clauses": len(texts),
                "n_changed_vs_r0": sum(
                    1
                    for a, b in zip(
                        texts,
                        [
                            p.text
                            for p in build_initial_constitution(
                                config_id, "SELF_REFLECT", 0, root=root
                            ).principles
                        ],
                    )
                    if a != b
                ),
                "sha256": sha256_bytes(
                    json.dumps({"type": kind, "clauses": texts}, sort_keys=True).encode()
                ),
                "system_sha256": sha256_bytes((system or "").encode()),
                "censored_at_round": None,
            }
        )
    return out


def build_none(config_id: str) -> dict[str, Any]:
    cid = _constitution_id("NONE", config_id=config_id, condition=None, chain_idx=None)
    return {
        "constitution_id": cid,
        "config_id": config_id,
        "type": "NONE",
        "chain": None,
        "condition": None,
        "r_final": None,
        "clauses": [],
        "n_clauses": 0,
        "n_changed_vs_r0": None,
        "sha256": sha256_bytes(json.dumps({"type": "NONE", "clauses": []}).encode()),
        "system_sha256": sha256_bytes(b""),
        "censored_at_round": None,
    }


def build_all_for_config(
    run_tag: str,
    config_id: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """38 constitutions for one config."""
    root = root or repo_root()
    out: list[dict[str, Any]] = []
    # R0 once per chain from SELF_REFLECT (D17 identity across conditions).
    for chain_idx in H3_CHAINS:
        bundle = load_chain_bundle(
            run_tag, config_id, "SELF_REFLECT", chain_idx, root=root
        )
        r0_texts = [p.text for p in _principles(bundle["r0"])]
        # Verify OTHER_REFLECT R0 matches when present.
        other_path = chain_dir(
            run_tag, config_id, "OTHER_REFLECT", chain_idx, root=root
        )
        if (other_path / "constitutions.jsonl").exists():
            other = load_chain_bundle(
                run_tag, config_id, "OTHER_REFLECT", chain_idx, root=root
            )
            other_texts = [p.text for p in _principles(other["r0"])]
            if other_texts != r0_texts:
                raise ValueError(
                    f"R0 mismatch {config_id} chain {chain_idx} SELF vs OTHER"
                )
        cid = _constitution_id(
            "R0", config_id=config_id, condition="SELF_REFLECT", chain_idx=chain_idx
        )
        out.append(
            {
                "constitution_id": cid,
                "config_id": config_id,
                "type": "R0",
                "chain": chain_idx,
                "condition": None,  # shared across conditions
                "r_final": 0,
                "clauses": r0_texts,
                "n_clauses": len(r0_texts),
                "n_changed_vs_r0": 0,
                "sha256": sha256_bytes(
                    json.dumps({"type": "R0", "clauses": r0_texts}, sort_keys=True).encode()
                ),
                "system_sha256": sha256_bytes(
                    constitution_system_prompt(r0_texts).encode()
                ),
                "censored_at_round": bundle["censored_at_round"],
            }
        )

    for condition in H3_CONDITIONS:
        for chain_idx in H3_CHAINS:
            rows = build_installed_for_chain(
                run_tag,
                config_id,
                condition,
                chain_idx,
                root=root,
                include_r0=False,
            )
            out.extend(rows)

    out.append(build_none(config_id))
    out.extend(build_positive_controls(config_id, root=root))
    if len(out) != 38:
        raise RuntimeError(f"{config_id}: expected 38 constitutions, got {len(out)}")
    return out


CONFIGS_7 = (
    "olmo3_7b_final",
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
)


def build_manifest(
    run_tag: str = "main_v1",
    *,
    root: Path | None = None,
    config_ids: tuple[str, ...] = CONFIGS_7,
) -> dict[str, Any]:
    root = root or repo_root()
    constitutions: list[dict[str, Any]] = []
    for cid in config_ids:
        constitutions.extend(build_all_for_config(run_tag, cid, root=root))
    return {
        "run_tag": run_tag,
        "n_constitutions": len(constitutions),
        "n_configs": len(config_ids),
        "constitutions": constitutions,
    }


def write_manifest(
    path: Path | None = None,
    *,
    run_tag: str = "main_v1",
    root: Path | None = None,
) -> Path:
    root = root or repo_root()
    path = path or (root / "materials" / "main_run" / "h3_constitutions.json")
    payload = build_manifest(run_tag, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
