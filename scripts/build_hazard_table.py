#!/usr/bin/env python3
"""Build tidy item-round hazard table for confirmatory analysis (prereg §6).

Reads main-run (or simulated) lineage + judge codes and writes a CSV/JSONL with:
config, condition, protocol, chain, item_id, category, form, round,
at_risk, event_gpt54, event_mimo, fate_gpt54, override, testlikeness,
position, eval_aware_flag

This script is the production builder. For Phase 6 freeze validation, synthetic
tables are produced by analysis/confirmatory/simulate.R instead.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from rc.config import repo_root


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tag", required=True, help="Main-run tag under runs/")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV (default: results/hazard_table_<run_tag>.csv)",
    )
    parser.add_argument(
        "--from-jsonl",
        type=Path,
        default=None,
        help="If set, copy/validate a pre-built tidy JSONL (sim or fixture).",
    )
    args = parser.parse_args()
    root = repo_root()
    out = args.out or (root / "results" / f"hazard_table_{args.run_tag}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.from_jsonl is not None:
        rows = []
        for line in args.from_jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        missing = [c for c in COLUMNS if rows and c not in rows[0]]
        if missing:
            raise SystemExit(f"missing columns: {missing}")
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c) for c in COLUMNS})
        print(f"wrote {len(rows)} rows → {out}")
        return

    raise SystemExit(
        "Main-run hazard extraction is not available yet (no main-run data). "
        "Pass --from-jsonl for simulated/fixture tables, or wait until after OSF registration."
    )


if __name__ == "__main__":
    main()
