"""Build confirmatory item-round hazard tables (prereg §4.2 / D76)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.h3_constitutions import LineageRecord, resolve_tip
from rc.judge_integrity import prompt_hash_gate
from rc.judging import EROSION_FATES, normalize_fate, structural_fate
from rc.main_run_coding import load_mimo_slot_ids, mimo_slot_post_censor, slot_key
from rc.pilot_coding import extract_pilot_transitions

OVERRIDE_RE = re.compile(
    r"\b(even when|even if|whatever|whoever|regardless)\b", re.IGNORECASE
)

COLUMNS = [
    "config",
    "condition",
    "protocol",
    "chain",
    "item_id",
    "category",
    "form",
    "round",
    "at_risk",
    "event_gpt54",
    "event_mimo",
    "fate_gpt54",
    "override",
    "testlikeness",
    "position",
    "eval_aware_flag",
]

MAIN_CONFIGS = (
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
    "olmo3_7b_final",
)

FORCED_CONDITIONS = (
    "SELF_REFLECT",
    "OTHER_REFLECT",
    "PARAPHRASE",
    "NEUTRAL_EDIT",
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _cons_at(chain_dir: Path, round_idx: int) -> dict[str, Any] | None:
    rows = [
        r
        for r in _load_jsonl(chain_dir / "constitutions.jsonl")
        if int(r.get("round", -1)) == round_idx
    ]
    return rows[-1] if rows else None


def _chain_k(chain_name: str) -> int:
    return int(str(chain_name).split("_", 1)[1])


def load_testlikeness(root: Path) -> dict[tuple[str, str], float]:
    """Item×form mean realism rating pooled across models (D27)."""
    audit = root / "runs" / "phase2b_realism_audit"
    if not audit.exists():
        raise FileNotFoundError(f"missing realism audit: {audit}")
    sums: dict[tuple[str, str], float] = defaultdict(float)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for calls in audit.glob("*/calls.jsonl"):
        for row in _load_jsonl(calls):
            if row.get("parse_status") != "ok":
                continue
            rating = row.get("rating")
            item_id = row.get("item_id")
            form = row.get("form")
            if rating is None or not item_id or not form:
                continue
            key = (str(item_id), str(form))
            sums[key] += float(rating)
            counts[key] += 1
    if not counts:
        raise RuntimeError("realism audit has no usable ratings")
    return {k: sums[k] / counts[k] for k in counts}


def _load_judgments(
    path: Path, *, require_ok_parse: bool = True
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for row in _load_jsonl(path):
        key = row.get("judgment_key") or row.get("transition_id")
        if not key:
            continue
        fate = row.get("fate")
        if fate is None:
            continue
        if normalize_fate(fate) is None:
            continue
        ps = row.get("parse_status")
        # GPT: require ok/repaired. MiMo: some rows have a usable fate with
        # parse_status=error (typo keys in raw JSON); still join by key (D78).
        if require_ok_parse and ps not in (None, "ok", "repaired"):
            continue
        out[str(key)] = row
    return out


def judgment_source_paths(
    config_id: str, *, run_tag: str = "main_v1", root: Path | None = None, judge: str = "gpt54"
) -> list[Path]:
    """D78: all on-disk locations that may hold a config's coded transitions.

    - ``coding/<config>/<judge>.jsonl`` (standard 7B layout)
    - ``coding/<config>/<config>/<judge>.jsonl`` (nested relaunch layout)
    - ``coding/<judge>.jsonl`` (canary / 7A combined file; filtered by key prefix)
    """
    root = root or repo_root()
    coding = root / "runs" / run_tag / "coding"
    return [
        coding / config_id / f"{judge}.jsonl",
        coding / config_id / config_id / f"{judge}.jsonl",
        coding / f"{judge}.jsonl",
    ]


def load_config_judgments(
    config_id: str,
    *,
    run_tag: str = "main_v1",
    root: Path | None = None,
    judge: str = "gpt54",
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Merge judgments for one config from all D78 source paths (key = transition_id)."""
    root = root or repo_root()
    out: dict[str, dict[str, Any]] = {}
    used: list[str] = []
    require_ok = judge == "gpt54"
    for path in judgment_source_paths(config_id, run_tag=run_tag, root=root, judge=judge):
        if not path.exists():
            continue
        n_before = len(out)
        for key, row in _load_judgments(path, require_ok_parse=require_ok).items():
            # Combined canary file: keep only this config's keys.
            if path.parent.name == "coding" and path.name == f"{judge}.jsonl":
                if not key.startswith(f"{config_id}|"):
                    continue
            out[key] = row
        if len(out) > n_before:
            used.append(f"{path}(+{len(out) - n_before})")
    return out, used


def censor_round_for_chain(
    meta: dict[str, Any], lineage_rows: list[dict[str, Any]], cons_by_round: dict[int, Any]
) -> int | None:
    """Last round with a completed transition, or None if the chain was not censored.

    ``meta.censored_at_round`` marks that the chain stopped early. The operational
    censor round for the risk set is the last lineage/constitution round that
    actually completed (D78).
    """
    if meta.get("censored_at_round") is None:
        return None
    lin_rounds = [int(r["round"]) for r in lineage_rows if int(r.get("round", -1)) > 0]
    if lin_rounds:
        return max(lin_rounds)
    cons_rounds = [r for r in cons_by_round if r > 0]
    return max(cons_rounds) if cons_rounds else 0


def _lineage_records(rows: list[dict[str, Any]]) -> list[LineageRecord]:
    return [
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
        for r in rows
    ]


def _r0_item_covars(
    cons0: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Static covariates from round-0 constitution."""
    oid_to_pos = {
        str(p["opaque_id"]): i + 1 for i, p in enumerate(cons0.get("principles") or [])
    }
    text_by_oid = {str(p["opaque_id"]): p.get("text") or "" for p in cons0.get("principles") or []}
    out: dict[str, dict[str, Any]] = {}
    for oid, meta in (cons0.get("metadata") or {}).items():
        item_id = meta.get("item_id")
        if not item_id:
            continue
        form = str(meta.get("form") or "")
        text = text_by_oid.get(str(oid), "")
        out[str(item_id)] = {
            "category": str(meta.get("category") or ""),
            "form": form,
            "position": int(oid_to_pos.get(str(oid), 0)),
            "override": int(bool(OVERRIDE_RE.search(text))),
            "round0_oid": str(oid),
        }
    return out


def _resolve_fate(
    transition: dict[str, Any],
    gpt_map: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    tid = transition["transition_id"]
    row = gpt_map.get(tid)
    if row and row.get("fate") is not None:
        fate = normalize_fate(row.get("fate")) or "NONE"
        return fate, row
    if transition.get("deleted") or transition.get("decision") == "delete":
        return "DELETED", None
    sf = structural_fate(
        transition.get("original") or "",
        transition.get("rewrite"),
        deleted=bool(transition.get("deleted")),
    )
    # D78: structural_fate returns FateJudgment — never str()-coerce the object.
    if sf is not None:
        return normalize_fate(sf.fate) or "NONE", None
    return "NONE", None


def build_hazard_rows(
    run_tag: str = "main_v1",
    *,
    root: Path | None = None,
    eval_aware_chains: set[tuple[str, str, str]] | None = None,
    max_round: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build at-risk hazard rows for FORCED × 4 conditions.

    ``eval_aware_chains`` keys are ``(config_id, condition, chain_dir_name)``.
    """
    root = root or repo_root()
    testlikeness = load_testlikeness(root)
    mimo_slots = load_mimo_slot_ids(root)
    eval_aware_chains = eval_aware_chains or set()

    gpt_maps: dict[str, dict[str, dict[str, Any]]] = {}
    mimo_maps: dict[str, dict[str, dict[str, Any]]] = {}
    judgment_sources: dict[str, dict[str, list[str]]] = {}
    for cfg in MAIN_CONFIGS:
        gpt_maps[cfg], gpt_src = load_config_judgments(
            cfg, run_tag=run_tag, root=root, judge="gpt54"
        )
        mimo_maps[cfg], mimo_src = load_config_judgments(
            cfg, run_tag=run_tag, root=root, judge="mimo"
        )
        judgment_sources[cfg] = {"gpt54": gpt_src, "mimo": mimo_src}
        if not gpt_maps[cfg]:
            raise RuntimeError(
                f"D78: no GPT-5.4 judgments found for {cfg} under "
                f"{judgment_source_paths(cfg, run_tag=run_tag, root=root)}"
            )

    transitions = extract_pilot_transitions(
        run_tag,
        root=root,
        forced_cumulative_rounds=(10, 20),
        permissive_cumulative_rounds=(10,),
    )
    # Index per_round* only, by (config, condition, chain_name, item_id, round)
    by_item_round: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = defaultdict(
        list
    )
    touch_by_tid: dict[str, dict[str, Any]] = {}
    for t in transitions:
        if t.get("protocol") != "FORCED":
            continue
        if t.get("kind") not in ("per_round", "per_round_absorbed"):
            continue
        key = (
            str(t["config_id"]),
            str(t["condition"]),
            str(t["chain"]),
            str(t["item_id"]),
            int(t["round"]),
        )
        by_item_round[key].append(t)
        touch_by_tid[str(t["transition_id"])] = t

    rows: list[dict[str, Any]] = []
    coded_for_hash: list[dict[str, Any]] = []
    independent_events = 0
    n_chains = 0
    # Coverage tracking (D78 hard gate)
    at_risk_touches = 0
    at_risk_touches_coded = 0
    at_risk_touch_gaps: list[str] = []
    post_risk_code_ok = 0  # codes for touches after event/censor (allowed)
    code_without_touch = 0
    censor_assert_ok = 0
    censor_assert_fail = 0
    # Per-chain max risk round for censor check
    chain_max_round: dict[tuple[str, str, str], int] = {}
    chain_censor: dict[tuple[str, str, str], int | None] = {}

    # Track which (config,condition,chain_name,item) eroded at which round for coverage
    eroded_at: dict[tuple[str, str, str, str], int] = {}

    base = root / "runs" / run_tag
    for config_id in MAIN_CONFIGS:
        for condition in FORCED_CONDITIONS:
            struct = base / config_id / "FORCED" / condition / "STRUCTURED"
            if not struct.exists():
                continue
            for chain_dir in sorted(struct.glob("chain_*")):
                n_chains += 1
                chain_name = chain_dir.name
                k = _chain_k(chain_name)
                chain_label = f"{condition}:{k}"
                meta = json.loads((chain_dir / "meta.json").read_text(encoding="utf-8"))
                cons0 = _cons_at(chain_dir, 0)
                if not cons0:
                    raise RuntimeError(f"missing R0: {chain_dir}")
                covars = _r0_item_covars(cons0)
                lin_rows = _load_jsonl(chain_dir / "lineage.jsonl")
                lineage = _lineage_records(lin_rows)
                cons_by_round = {
                    int(r["round"]): r for r in _load_jsonl(chain_dir / "constitutions.jsonl")
                }
                cens_int = censor_round_for_chain(meta, lin_rows, cons_by_round)
                chain_censor[(config_id, condition, chain_name)] = cens_int
                flag = int(
                    (config_id, condition, chain_name) in eval_aware_chains
                    or (config_id, condition, chain_label) in eval_aware_chains
                )
                eroded: set[str] = set()

                for t in range(1, max_round + 1):
                    if cens_int is not None and t > cens_int:
                        break
                    cons_prev = cons_by_round.get(t - 1)
                    if cons_prev is None:
                        break
                    final_texts = {
                        str(p["opaque_id"]): str(p["text"])
                        for p in (cons_prev.get("principles") or [])
                    }
                    for item_id, cov in covars.items():
                        if item_id in eroded:
                            continue
                        tip = resolve_tip(
                            cov["round0_oid"],
                            lineage,
                            r_final=t - 1,
                            final_texts=final_texts,
                        )
                        if tip.deleted:
                            continue
                        touch = by_item_round.get(
                            (config_id, condition, chain_name, item_id, t), []
                        )
                        fate = "NONE"
                        event = 0
                        used_tid: str | None = None
                        for tr in touch:
                            at_risk_touches += 1
                            f, jrow = _resolve_fate(tr, gpt_maps[config_id])
                            # Coverage: at-risk touch must have a code (LLM map or structural).
                            tid = tr["transition_id"]
                            has_llm = tid in gpt_maps[config_id]
                            if has_llm or f != "NONE":
                                at_risk_touches_coded += 1
                            else:
                                at_risk_touch_gaps.append(tid)
                            if jrow is not None:
                                coded_for_hash.append(jrow)
                            used_tid = tid
                            # Prefer an erosion fate if any touch erodes.
                            if f in EROSION_FATES:
                                fate = f
                                event = 1
                                break
                            if fate == "NONE":
                                fate = f
                        if event:
                            eroded.add(item_id)
                            eroded_at[(config_id, condition, chain_name, item_id)] = t
                            independent_events += 1

                        event_mimo: int | str = ""
                        if touch:
                            # Slot membership is design-slot level (D56).
                            sk = slot_key(
                                {
                                    "config_id": config_id,
                                    "protocol": "FORCED",
                                    "condition": condition,
                                    "chain": chain_name,
                                    "round": t,
                                }
                            )
                            if sk in mimo_slots and used_tid:
                                mrow = mimo_maps[config_id].get(used_tid)
                                if mrow and mrow.get("fate") is not None:
                                    mf = normalize_fate(mrow.get("fate")) or ""
                                    event_mimo = int(mf in EROSION_FATES)
                                else:
                                    # Slot-level code may be on a sibling touch (same slot).
                                    for tr in touch:
                                        mrow = mimo_maps[config_id].get(tr["transition_id"])
                                        if mrow and mrow.get("fate") is not None:
                                            break
                                    event_mimo = ""

                        tl = testlikeness.get((item_id, cov["form"]))
                        if tl is None:
                            raise KeyError(
                                f"missing testlikeness for {item_id} form={cov['form']}"
                            )
                        rows.append(
                            {
                                "config": config_id,
                                "condition": condition,
                                "protocol": "FORCED",
                                "chain": chain_label,
                                "item_id": item_id,
                                "category": cov["category"],
                                "form": cov["form"],
                                "round": t,
                                "at_risk": 1,
                                "event_gpt54": event,
                                "event_mimo": event_mimo if event_mimo != "" else "",
                                "fate_gpt54": fate,
                                "override": cov["override"],
                                "testlikeness": round(float(tl), 6),
                                "position": cov["position"],
                                "eval_aware_flag": flag,
                            }
                        )
                        ck = (config_id, condition, chain_name)
                        chain_max_round[ck] = max(chain_max_round.get(ck, 0), t)

    # Codes that do not map to a touch: count; allow if post-event or post-censor.
    for cfg in MAIN_CONFIGS:
        for tid, row in gpt_maps[cfg].items():
            if "|FORCED|" not in tid or "|cum" in tid:
                continue
            # per_round keys only
            parts = tid.split("|")
            if len(parts) < 7:
                continue
            # config|FORCED|cond|chain|rN|item|decision...
            if not (parts[4].startswith("r") and parts[4][1:].isdigit()):
                continue
            if tid in touch_by_tid:
                tr = touch_by_tid[tid]
                cond = str(tr["condition"])
                chain_name = str(tr["chain"])
                item = str(tr["item_id"])
                rnd = int(tr["round"])
                cens = chain_censor.get((cfg, cond, chain_name))
                er = eroded_at.get((cfg, cond, chain_name, item))
                if cens is not None and rnd > cens:
                    post_risk_code_ok += 1
                elif er is not None and rnd > er:
                    post_risk_code_ok += 1
                # else mapped to a touch (covered above)
            else:
                # May be cumulative or non-touch key
                if "|r" in tid and "|cum" not in tid:
                    code_without_touch += 1

    # Censoring assertion
    for ck, cens in chain_censor.items():
        if cens is None:
            continue
        mx = chain_max_round.get(ck)
        if mx == cens:
            censor_assert_ok += 1
        else:
            censor_assert_fail += 1

    sum_events = sum(int(r["event_gpt54"]) for r in rows)

    hash_gate = prompt_hash_gate(coded_for_hash, root=root) if coded_for_hash else {
        "ok": False,
        "n_checked": 0,
        "n_mismatch": 0,
        "gate": "prompt_hash",
        "mismatch_rate": 1.0,
        "examples": [],
    }

    n_at_risk = len(rows)
    bad_event_vals = sum(
        1
        for r in rows
        if int(r["at_risk"]) == 1 and r["event_gpt54"] not in (0, 1, "0", "1")
    )

    independent_recount = _independent_event_count(root, run_tag, gpt_maps, max_round)

    # MiMo: every subsample slot with a realized transition must have a code.
    mimo_slots_needed = 0
    mimo_slots_joined = 0
    mimo_gaps: list[str] = []
    slots_with_touch: dict[str, list[str]] = defaultdict(list)
    for tid, tr in touch_by_tid.items():
        sk = slot_key(tr)
        if sk in mimo_slots:
            slots_with_touch[sk].append(tid)
    for sk, tids in slots_with_touch.items():
        if mimo_slot_post_censor(sk, run_tag=run_tag, root=root):
            continue
        mimo_slots_needed += 1
        cfg = sk.split("|", 1)[0]
        if any(tid in mimo_maps.get(cfg, {}) for tid in tids):
            mimo_slots_joined += 1
        else:
            mimo_gaps.append(sk)

    coverage_ok = (
        at_risk_touches > 0
        and at_risk_touches_coded == at_risk_touches
        and len(at_risk_touch_gaps) == 0
        and mimo_slots_needed == mimo_slots_joined
        and censor_assert_fail == 0
        and bool(hash_gate.get("ok"))
        and sum_events == independent_recount == independent_events
    )

    # Per-config totals (allowed under D55/D73 for 7E-A3)
    per_config: dict[str, dict[str, int]] = {
        cfg: {"rows": 0, "fate_rows": 0, "events": 0, "mimo_coded_rows": 0}
        for cfg in MAIN_CONFIGS
    }
    for r in rows:
        pc = per_config[r["config"]]
        pc["rows"] += 1
        if r["fate_gpt54"] != "NONE":
            pc["fate_rows"] += 1
        if int(r["event_gpt54"]) == 1:
            pc["events"] += 1
        if r["event_mimo"] not in ("", "NA", None):
            pc["mimo_coded_rows"] += 1

    report = {
        "n_chains": n_chains,
        "n_rows": n_at_risk,
        "n_events_table": sum_events,
        "n_events_builder": independent_events,
        "n_events_independent": independent_recount,
        "events_match": sum_events == independent_recount == independent_events,
        "every_at_risk_has_event_value": bad_event_vals == 0,
        "prompt_hash_gate": {
            "ok": bool(hash_gate.get("ok")),
            "n_checked": hash_gate.get("n_checked"),
            "n_mismatch": hash_gate.get("n_mismatch"),
        },
        "n_coded_rows_hashed": len(coded_for_hash),
        "judgment_sources": judgment_sources,
        "coverage": {
            "ok": coverage_ok,
            "at_risk_touches": at_risk_touches,
            "at_risk_touches_coded": at_risk_touches_coded,
            "at_risk_touch_gaps_n": len(at_risk_touch_gaps),
            "at_risk_touch_gap_examples": at_risk_touch_gaps[:5],
            "post_risk_code_ok": post_risk_code_ok,
            "code_without_touch": code_without_touch,
            "mimo_slots_needed": mimo_slots_needed,
            "mimo_slots_joined": mimo_slots_joined,
            "mimo_gap_examples": mimo_gaps[:5],
            "censor_assert_ok": censor_assert_ok,
            "censor_assert_fail": censor_assert_fail,
        },
        "per_config": per_config,
    }
    if not coverage_ok:
        raise RuntimeError(
            "D78 coverage gate FAIL: "
            + json.dumps(report["coverage"], sort_keys=True)
        )
    return rows, report


def _independent_event_count(
    root: Path,
    run_tag: str,
    gpt_maps: dict[str, dict[str, dict[str, Any]]],
    max_round: int,
) -> int:
    """Recount first erosion events from lineage.jsonl + codes (no hazard CSV)."""
    transitions = extract_pilot_transitions(
        run_tag,
        root=root,
        forced_cumulative_rounds=(10, 20),
        permissive_cumulative_rounds=(10,),
    )
    by_item_round: dict[tuple[str, str, str, str, int], list[dict[str, Any]]] = defaultdict(
        list
    )
    for t in transitions:
        if t.get("protocol") != "FORCED":
            continue
        if t.get("kind") not in ("per_round", "per_round_absorbed"):
            continue
        by_item_round[
            (
                str(t["config_id"]),
                str(t["condition"]),
                str(t["chain"]),
                str(t["item_id"]),
                int(t["round"]),
            )
        ].append(t)

    n_events = 0
    base = root / "runs" / run_tag
    for config_id in MAIN_CONFIGS:
        for condition in FORCED_CONDITIONS:
            struct = base / config_id / "FORCED" / condition / "STRUCTURED"
            if not struct.exists():
                continue
            for chain_dir in sorted(struct.glob("chain_*")):
                chain_name = chain_dir.name
                meta = json.loads((chain_dir / "meta.json").read_text(encoding="utf-8"))
                cons0 = _cons_at(chain_dir, 0)
                if not cons0:
                    continue
                covars = _r0_item_covars(cons0)
                lin_rows = _load_jsonl(chain_dir / "lineage.jsonl")
                lineage = _lineage_records(lin_rows)
                cons_by_round = {
                    int(r["round"]): r for r in _load_jsonl(chain_dir / "constitutions.jsonl")
                }
                cens_int = censor_round_for_chain(meta, lin_rows, cons_by_round)
                eroded: set[str] = set()
                for t in range(1, max_round + 1):
                    if cens_int is not None and t > cens_int:
                        break
                    cons_prev = cons_by_round.get(t - 1)
                    if cons_prev is None:
                        break
                    final_texts = {
                        str(p["opaque_id"]): str(p["text"])
                        for p in (cons_prev.get("principles") or [])
                    }
                    for item_id, cov in covars.items():
                        if item_id in eroded:
                            continue
                        tip = resolve_tip(
                            cov["round0_oid"],
                            lineage,
                            r_final=t - 1,
                            final_texts=final_texts,
                        )
                        if tip.deleted:
                            continue
                        touch = by_item_round.get(
                            (config_id, condition, chain_name, item_id, t), []
                        )
                        for tr in touch:
                            fate, _ = _resolve_fate(tr, gpt_maps[config_id])
                            if fate in EROSION_FATES:
                                eroded.add(item_id)
                                n_events += 1
                                break
    return n_events


def write_hazard_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz" or str(path).endswith(".csv.gz"):
        opener = gzip.open
        mode = "wt"
    else:
        opener = open  # type: ignore[assignment]
        mode = "w"
    with opener(path, mode, encoding="utf-8", newline="") as fh:  # type: ignore[arg-type]
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            out = {c: row.get(c) for c in COLUMNS}
            # Empty string for NA event_mimo (R reads as NA with na.strings)
            if out["event_mimo"] == "":
                out["event_mimo"] = "NA"
            writer.writerow(out)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_trace_examples(
    rows: list[dict[str, Any]],
    *,
    root: Path,
    run_tag: str,
    out_path: Path,
    n: int = 5,
    seed: int = 20261004,
) -> None:
    """Hand-check n random item traces (category-blind sampling)."""
    rng = random.Random(seed)
    # Unique (config, condition, chain, item_id)
    keys = sorted(
        {
            (r["config"], r["condition"], r["chain"], r["item_id"])
            for r in rows
        }
    )
    picked = rng.sample(keys, k=min(n, len(keys)))
    by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_key[(r["config"], r["condition"], r["chain"], r["item_id"])].append(r)

    lines = [
        "# Hazard trace examples (blinded)",
        "",
        f"Seed `{seed}`; {len(picked)} items sampled without regard to category.",
        "",
    ]
    for config, condition, chain_label, item_id in picked:
        k = int(str(chain_label).split(":")[1])
        chain_dir = (
            root
            / "runs"
            / run_tag
            / config
            / "FORCED"
            / condition
            / "STRUCTURED"
            / f"chain_{k}"
        )
        cons0 = _cons_at(chain_dir, 0)
        text0 = None
        if cons0:
            for oid, meta in (cons0.get("metadata") or {}).items():
                if meta.get("item_id") == item_id:
                    for p in cons0.get("principles") or []:
                        if p.get("opaque_id") == oid:
                            text0 = p.get("text")
                            break
        item_rows = sorted(by_key[(config, condition, chain_label, item_id)], key=lambda r: r["round"])
        lines.append(f"## {config} | {chain_label} | {item_id}")
        lines.append("")
        lines.append(f"- R0 text: {text0!r}")
        lines.append(f"- at-risk rounds: {len(item_rows)}")
        for r in item_rows:
            if int(r["event_gpt54"]) == 1 or r["fate_gpt54"] not in ("NONE", "RETAINED"):
                lines.append(
                    f"- round {r['round']}: at_risk={r['at_risk']} "
                    f"event_gpt54={r['event_gpt54']} fate_gpt54={r['fate_gpt54']} "
                    f"event_mimo={r['event_mimo']!r}"
                )
                # Lineage texts for this round
                for lr in _load_jsonl(chain_dir / "lineage.jsonl"):
                    if int(lr.get("round", -1)) != int(r["round"]):
                        continue
                    if lr.get("item_id") != item_id and lr.get("decision") != "merge":
                        continue
                    lines.append(
                        f"  - lineage decision={lr.get('decision')} "
                        f"before={str(lr.get('before_text'))[:160]!r} "
                        f"after={str(lr.get('after_text'))[:160]!r}"
                    )
        # Always show first/last row flags
        if item_rows:
            first, last = item_rows[0], item_rows[-1]
            lines.append(
                f"- first row: round={first['round']} event={first['event_gpt54']} "
                f"fate={first['fate_gpt54']}"
            )
            lines.append(
                f"- last row: round={last['round']} event={last['event_gpt54']} "
                f"fate={last['fate_gpt54']}"
            )
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def patch_eval_aware_flags(
    rows: list[dict[str, Any]],
    flagged_chains: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """Set chain-level eval_aware_flag from (config, condition, chain_label) keys."""
    for r in rows:
        key = (r["config"], r["condition"], r["chain"])
        r["eval_aware_flag"] = int(key in flagged_chains)
    return rows
