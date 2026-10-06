#!/usr/bin/env python3
"""CPU-only D35 recompute from stored raw judge labels (no regeneration)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from rc.config import repo_root
from rc.judge_metrics import (
    krippendorff_alpha_ordinal,
    metrics_for_judge,
    select_judges_d33,
)
from rc.judging import fate_ordinal, normalize_fate
from rc.pilot_coding import resolve_disagreement


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def recompute_calibration(root: Path) -> dict:
    calib_dir = root / "runs" / "phase4" / "calib"
    per: dict[str, list[dict]] = {}
    for path in sorted(calib_dir.glob("*.jsonl")):
        per[path.stem] = _load_jsonl(path)
    if not per:
        return {"ok": False, "reason": "no calibration jsonl under runs/phase4/calib"}
    metrics = {jid: metrics_for_judge(rows) for jid, rows in per.items()}
    selection = select_judges_d33(per)
    # Explicit pairwise α under D35 ordinal (same as select_judges_d33).
    out = {
        "ok": True,
        "n_judges": len(per),
        "judge_ids": sorted(per),
        "metrics": metrics,
        "selection_d33": selection,
    }
    dest = root / "reports" / "phase4_recompute_d35_calibration.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


def recompute_pilot_coding(root: Path) -> dict | None:
    """Re-resolve disagreements from stored j1/j2/j3 raw labels under D35 ordinal."""
    coding_dir = root / "runs" / "phase4" / "coding"
    if not coding_dir.exists():
        return None
    summary_path = root / "runs" / "phase4" / "pilot_coding_summary.json"
    prev = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    j1 = prev.get("j1")
    j2 = prev.get("j2")
    j3 = prev.get("j3")
    if not j1 or not j2:
        return {"ok": False, "reason": "missing j1/j2 in pilot_coding_summary.json"}

    def load_role(role: str, jid: str) -> dict[int, dict]:
        path = coding_dir / f"{role}_{jid}.jsonl"
        return {int(r["item_index"]): r for r in _load_jsonl(path)}

    j1_map = load_role("j1", j1)
    j2_map = load_role("j2", j2)
    j3_map = load_role("j3", j3) if j3 else {}
    coded_path = root / "runs" / "phase4" / "pilot_v1_coding.jsonl"
    old_coded = _load_jsonl(coded_path)
    # Rebuild non-structural from role maps; keep structural rows.
    structural = [r for r in old_coded if r.get("structural")]
    llm_n = max(j1_map) + 1 if j1_map else 0
    ratings = []
    unresolved = 0
    resolved_rows = []
    for i in range(llm_n):
        a, b = j1_map[i], j2_map[i]
        c = j3_map.get(i)
        resolved = resolve_disagreement(a, b, c)
        if resolved["unresolved"]:
            unresolved += 1
        base = next(
            (
                r
                for r in old_coded
                if not r.get("structural") and r.get("item_index") == i
            ),
            {},
        )
        resolved_rows.append({**base, **resolved, "structural": False, "item_index": i})
        ratings.append([fate_ordinal(a.get("fate")), fate_ordinal(b.get("fate"))])
    alpha = krippendorff_alpha_ordinal(ratings)
    coded = structural + resolved_rows
    # Rewrite coding jsonl + summary fields that depend on ordinal.
    with coded_path.open("w", encoding="utf-8") as fh:
        for row in coded:
            slim = {k: v for k, v in row.items() if k not in {"j1", "j2", "j3"}}
            fh.write(json.dumps(slim, sort_keys=True) + "\n")
    dist: dict[str, Counter] = defaultdict(Counter)
    for row in coded:
        key = f"{row.get('protocol')}|{row.get('condition')}"
        dist[key][normalize_fate(row.get("fate")) or "?"] += 1
    summary = {
        **prev,
        "j1_j2_alpha": alpha,
        "alpha_gate_pass": bool(alpha is not None and alpha >= 0.70),
        "unresolved_rate": unresolved / max(llm_n, 1),
        "unresolved_n": unresolved,
        "fate_distributions": {k: dict(v) for k, v in dist.items()},
        "d35_recomputed": True,
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    (root / "reports" / "phase4_recompute_d35_pilot.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    root = repo_root()
    calib = recompute_calibration(root)
    print(
        json.dumps(
            {
                "calib_ok": calib.get("ok"),
                "n_judges": calib.get("n_judges"),
                "stopped": (calib.get("selection_d33") or {}).get("stopped"),
                "j1": (calib.get("selection_d33") or {}).get("j1"),
                "j2": (calib.get("selection_d33") or {}).get("j2"),
                "j3": (calib.get("selection_d33") or {}).get("j3"),
                "alpha": (calib.get("selection_d33") or {}).get("j1_j2_alpha"),
                "stop_reason": (calib.get("selection_d33") or {}).get("stop_reason"),
            },
            indent=2,
        )
    )
    if calib.get("metrics"):
        for jid, m in calib["metrics"].items():
            print(
                f"  {jid}: macro_f1={m['macro_f1']:.4f} κ={m['weighted_kappa']:.4f} "
                f"|COR-AGENT|={abs(m.get('cor_minus_agent_accuracy') or 0):.4f}"
            )
    pilot = recompute_pilot_coding(root)
    if pilot is None:
        print("pilot coding: not present yet (skip)")
    else:
        print(
            json.dumps(
                {
                    "pilot_alpha": pilot.get("j1_j2_alpha"),
                    "alpha_gate_pass": pilot.get("alpha_gate_pass"),
                    "unresolved_rate": pilot.get("unresolved_rate"),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
