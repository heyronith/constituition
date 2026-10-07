#!/usr/bin/env python3
"""D59 forensics: find first stale round per chain via prompt-hash replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.chain_runner import find_t_stale, verify_chain_consistency  # noqa: E402
from rc.config import repo_root  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-tag", default="main_v1")
    parser.add_argument("--config-id", default="olmo3_7b_final")
    parser.add_argument(
        "--out",
        default=str(ROOT / "results" / "d59_forensics.json"),
    )
    args = parser.parse_args()
    root = repo_root()
    base = root / "runs" / args.run_tag / args.config_id
    rows = []
    unexplained = []
    for chain_dir in sorted(p for p in base.rglob("chain_*") if p.is_dir()):
        meta = json.loads((chain_dir / "meta.json").read_text(encoding="utf-8"))
        ok_rounds = sorted(
            {
                int(json.loads(l)["round"])
                for l in (chain_dir / "rounds.jsonl").read_text().splitlines()
                if l.strip() and json.loads(l).get("parse_status") == "ok"
            }
        )
        t_stale = find_t_stale(chain_dir, root=root)
        # Sanity: if none, every round must match
        if t_stale is None:
            v = verify_chain_consistency(chain_dir, root=root)
            prompt_errs = [e for e in v["errors"] if "prompt_sha256" in e]
            if prompt_errs:
                unexplained.append(
                    {
                        "chain": str(chain_dir.relative_to(base)),
                        "errors": prompt_errs,
                    }
                )
        rows.append(
            {
                "chain_path": str(chain_dir.relative_to(base)),
                "protocol": meta.get("protocol"),
                "condition": meta.get("condition"),
                "chain_idx": meta.get("chain_idx"),
                "n_ok_rounds": len(ok_rounds),
                "t_stale": t_stale,
                "censored_at_round": meta.get("censored_at_round"),
            }
        )

    n_stale = sum(1 for r in rows if r["t_stale"] is not None)
    by_t: dict[str, int] = {}
    for r in rows:
        key = str(r["t_stale"])
        by_t[key] = by_t.get(key, 0) + 1

    report = {
        "run_tag": args.run_tag,
        "config_id": args.config_id,
        "n_chains": len(rows),
        "n_stale": n_stale,
        "n_clean": len(rows) - n_stale,
        "t_stale_histogram": by_t,
        "unexplained_mismatches": unexplained,
        "chains": rows,
        "resume_evidence": {
            "summary": (
                "Stale rounds begin at generation index t_stale after an in-job "
                "Modal container retry/resume of generate_config. The D58 off-by-one "
                "restored constitutions.jsonl round t instead of t+1, so prompts for "
                "t_stale…end were built on a constitution missing the change from "
                "round t_stale-1. Evidence: duplicated constitution/lineage rounds "
                "at cons.round ∈ {10,11} in the pre-repair snapshot; final "
                "cons.round short by 1 vs max(ok_gen)+1; rounds.jsonl unchanged "
                "across the invalid D58 rewrite."
            ),
            "likely_trigger": (
                "Modal worker preemption or automatic function retry of "
                "generate_config after ~10 FORCED lock-step rounds had been "
                "Volume-committed (D31). Not a deliberate modal app stop — the "
                "only SIGTERM in the canary log is at generate→coding handoff "
                "(18:39:39Z). The lineage-duplication pattern matches "
                "_init_unit resume with the pre-D58 off-by-one."
            ),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Markdown table
    print(f"n_chains={len(rows)} n_stale={n_stale} n_clean={len(rows) - n_stale}")
    print(f"t_stale histogram: {by_t}")
    print(f"unexplained: {len(unexplained)}")
    if unexplained:
        print("STOP: unexplained prompt mismatches without t_stale")
        for u in unexplained:
            print(u)
        raise SystemExit(2)
    print("| chain | protocol | condition | n_ok | t_stale |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['chain_path']} | {r['protocol']} | {r['condition']} | "
            f"{r['n_ok_rounds']} | {r['t_stale']} |"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
