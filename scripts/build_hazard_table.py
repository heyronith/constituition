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
from rc.hazard_table import (
    COLUMNS,
    build_hazard_rows,
    sha256_file,
    write_hazard_csv,
    write_trace_examples,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tag", required=True, help="Main-run tag under runs/")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV (default: results/hazard_table_<run_tag>.csv.gz)",
    )
    parser.add_argument(
        "--from-jsonl",
        type=Path,
        default=None,
        help="If set, copy/validate a pre-built tidy JSONL (sim or fixture).",
    )
    parser.add_argument(
        "--eval-aware-json",
        type=Path,
        default=None,
        help="Optional JSON with flagged_chains list of {config,condition,chain}.",
    )
    parser.add_argument(
        "--trace-out",
        type=Path,
        default=None,
        help="Write hand-check traces (default: results/hazard_trace_examples.md).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Write validation report JSON (totals only).",
    )
    args = parser.parse_args()
    root = repo_root()
    out = args.out or (root / "results" / f"hazard_table_{args.run_tag}.csv.gz")
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

    eval_chains: set[tuple[str, str, str]] = set()
    if args.eval_aware_json and args.eval_aware_json.exists():
        payload = json.loads(args.eval_aware_json.read_text(encoding="utf-8"))
        for c in payload.get("flagged_chains") or []:
            eval_chains.add((c["config"], c["condition"], c["chain"]))

    rows, report = build_hazard_rows(
        args.run_tag, root=root, eval_aware_chains=eval_chains
    )
    write_hazard_csv(rows, out)
    trace_out = args.trace_out or (root / "results" / "hazard_trace_examples.md")
    write_trace_examples(rows, root=root, run_tag=args.run_tag, out_path=trace_out)
    report["out"] = str(out)
    report["sha256"] = sha256_file(out)
    report["trace_out"] = str(trace_out)
    report_out = args.report_out or (root / "results" / f"hazard_table_{args.run_tag}_report.json")
    report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Totals only — never by category/condition.
    print(
        json.dumps(
            {
                "wrote_rows": report["n_rows"],
                "n_chains": report["n_chains"],
                "n_events": report["n_events_table"],
                "events_match": report["events_match"],
                "every_at_risk_has_event_value": report["every_at_risk_has_event_value"],
                "prompt_hash_ok": report["prompt_hash_gate"]["ok"],
                "out": str(out),
                "sha256": report["sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
