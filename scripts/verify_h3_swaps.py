#!/usr/bin/env python3
"""Independent COR_SWAP / AGENT_SWAP check (D74 Session 2).

Different method from ``rc.h3_constitutions.resolve_tip``: start from the final
constitution row + reverse-walk lineage parents to round-0 ancestors, then rebuild
swaps and compare clause lists to the frozen manifest.

Does not print counts by category. PASS/FAIL per swap only.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.config import repo_root  # noqa: E402
from rc.h3_constitutions import (  # noqa: E402
    CONFIGS_7,
    H3_CHAINS,
    H3_CONDITIONS,
    PROTOCOL,
    FMT,
    chain_dir,
    load_chain_bundle,
)
from rc.materials import LineageRecord  # noqa: E402
from rc.phase7d import load_h3_manifest  # noqa: E402


def _records(raw: list[dict]) -> list[LineageRecord]:
    out: list[LineageRecord] = []
    for r in raw:
        out.append(
            LineageRecord(
                round=int(r["round"]),
                opaque_id=str(r["opaque_id"]),
                parent_ids=[str(x) for x in r.get("parent_ids") or []],
                decision=r.get("decision"),
                merge_with=str(r["merge_with"]) if r.get("merge_with") else None,
                before_text=r.get("before_text"),
                after_text=r.get("after_text"),
                flags=list(r.get("flags") or []),
                item_id=r.get("item_id"),
                category=r.get("category"),
            )
        )
    return out


def _r0_category_map(r0_row: dict) -> dict[str, str]:
    return {str(oid): str(m["category"]) for oid, m in (r0_row.get("metadata") or {}).items()}


def _deleted_ids(lineage: list[LineageRecord], r_final: int) -> set[str]:
    deleted: set[str] = set()
    for rec in lineage:
        if 0 < rec.round <= r_final and rec.decision == "delete":
            deleted.add(rec.opaque_id)
    return deleted


def _parent_edges(lineage: list[LineageRecord], r_final: int) -> dict[str, set[str]]:
    """Map child opaque_id → parent opaque_ids appearing in lineage ≤ r_final.

    Independent of resolve_tip: uses parent_ids on keep/revise/merge survivor rows
    and merge stubs (absorbed → survivor via merge_with when after_text is None).
    """
    child_to_parents: dict[str, set[str]] = defaultdict(set)
    for rec in lineage:
        if rec.round <= 0 or rec.round > r_final:
            continue
        if rec.decision in {"keep", "revise"}:
            for pid in rec.parent_ids:
                if pid != rec.opaque_id:
                    child_to_parents[rec.opaque_id].add(pid)
        elif rec.decision == "merge":
            if rec.after_text is None and rec.merge_with:
                # absorbed stub: child survivor is merge_with; parent is absorbed id
                child_to_parents[str(rec.merge_with)].add(rec.opaque_id)
            else:
                # survivor merge row
                for pid in rec.parent_ids:
                    if pid != rec.opaque_id:
                        child_to_parents[rec.opaque_id].add(pid)
                if rec.merge_with:
                    child_to_parents[rec.opaque_id].add(str(rec.merge_with))
    return child_to_parents


def _r0_ancestors(
    tip_id: str,
    child_to_parents: dict[str, set[str]],
    r0_ids: set[str],
) -> set[str]:
    """Reverse-walk from a final tip to the set of round-0 opaque ids."""
    seen: set[str] = set()
    stack = [tip_id]
    ancestors: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in r0_ids:
            ancestors.add(cur)
        for p in child_to_parents.get(cur, ()):
            stack.append(p)
        # Tip that never left R0 id
        if cur in r0_ids and cur not in child_to_parents:
            ancestors.add(cur)
    if tip_id in r0_ids:
        ancestors.add(tip_id)
    return ancestors


def rebuild_swap_from_final(
    *,
    r0_row: dict,
    r_final_row: dict,
    lineage_raw: list[dict],
    r_final: int,
    category: str,
) -> list[str]:
    """Rebuild swap clause texts from final row + reverse lineage (not resolve_tip)."""
    lineage = _records(lineage_raw)
    r0_cat = _r0_category_map(r0_row)
    r0_order = [str(p["opaque_id"]) for p in r0_row["principles"]]
    r0_text = {str(p["opaque_id"]): str(p["text"]) for p in r0_row["principles"]}
    r0_ids = set(r0_order)
    final_text = {str(p["opaque_id"]): str(p["text"]) for p in r_final_row["principles"]}
    final_ids = list(final_text.keys())
    deleted = _deleted_ids(lineage, r_final)
    edges = _parent_edges(lineage, r_final)

    # tip_id → r0 ancestors
    tip_anc: dict[str, set[str]] = {
        tid: _r0_ancestors(tid, edges, r0_ids) for tid in final_ids
    }
    # For each R0 id in category, which final tip carries it?
    r0_to_tip: dict[str, str] = {}
    for tid, ancs in tip_anc.items():
        for a in ancs:
            if r0_cat.get(a) == category:
                # Prefer tip that lists this ancestor; first wins then overwrite if more specific
                r0_to_tip[a] = tid

    # Non-category R0 ids absorbed into a category tip → drop verbatim R0
    drop_r0: set[str] = set()
    for tid, ancs in tip_anc.items():
        cat_ancs = {a for a in ancs if r0_cat.get(a) == category}
        if not cat_ancs:
            continue
        for a in ancs:
            if r0_cat.get(a) != category:
                drop_r0.add(a)

    out: list[str] = []
    seen_tips: set[str] = set()
    for oid in r0_order:
        cat = r0_cat[oid]
        if cat == category:
            if oid in deleted and oid not in r0_to_tip:
                continue
            tip = r0_to_tip.get(oid)
            if tip is None:
                # Surviving unchanged under same id
                if oid in final_text and oid not in deleted:
                    tip = oid
                else:
                    continue
            if tip in seen_tips:
                continue
            seen_tips.add(tip)
            out.append(final_text[tip])
        else:
            # D66: non-swapped categories stay verbatim R0 even if later deleted
            # in the chain; only drop when absorbed into a swapped-category tip.
            if oid in drop_r0:
                continue
            out.append(r0_text[oid])
    return out


def main() -> int:
    root = repo_root()
    # Prefer Volume via runs/ symlink if present; else fail clearly.
    man = load_h3_manifest(root)
    by_id = {r["constitution_id"]: r for r in man["constitutions"]}
    results: list[dict] = []
    n_fail = 0
    for config_id in CONFIGS_7:
        for condition in H3_CONDITIONS:
            for chain_idx in H3_CHAINS:
                cdir = chain_dir(
                    "main_v1", config_id, condition, chain_idx, root=root
                )
                if not (cdir / "constitutions.jsonl").exists():
                    results.append(
                        {
                            "status": "FAIL",
                            "constitution_ids": [],
                            "reason": f"missing chain dir {cdir}",
                        }
                    )
                    n_fail += 1
                    continue
                bundle = load_chain_bundle(
                    "main_v1", config_id, condition, chain_idx, root=root
                )
                lineage_raw = [
                    {
                        "round": r.round,
                        "opaque_id": r.opaque_id,
                        "parent_ids": list(r.parent_ids),
                        "decision": r.decision,
                        "merge_with": r.merge_with,
                        "before_text": r.before_text,
                        "after_text": r.after_text,
                        "flags": list(r.flags),
                        "item_id": r.item_id,
                        "category": r.category,
                    }
                    for r in bundle["lineage"]
                ]
                for cat, ctype in (("COR", "COR_SWAP"), ("AGENT", "AGENT_SWAP")):
                    cid = f"{config_id}|{ctype}|{condition}|chain_{chain_idx}"
                    rebuilt = rebuild_swap_from_final(
                        r0_row=bundle["r0"],
                        r_final_row=bundle["r_final_row"],
                        lineage_raw=lineage_raw,
                        r_final=int(bundle["r_final"]),
                        category=cat,
                    )
                    expected = by_id[cid]["clauses"]
                    ok = rebuilt == expected
                    row = {
                        "status": "PASS" if ok else "FAIL",
                        "constitution_id": cid,
                        "config_id": config_id,
                        "condition": condition,
                        "chain": chain_idx,
                        "type": ctype,
                    }
                    if not ok:
                        n_fail += 1
                        row["mismatch"] = {
                            "rebuilt": rebuilt,
                            "manifest": expected,
                        }
                    results.append(row)
                    print(f"{row['status']} {cid}")

    out_path = root / "results" / "phase7d_swap_verify.json"
    out_path.write_text(
        json.dumps(
            {
                "n": len(results),
                "n_fail": n_fail,
                "all_pass": n_fail == 0,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path} n={len(results)} n_fail={n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
