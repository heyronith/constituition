#!/usr/bin/env python3
"""CLI wrapper for Phase 7E-A eval-awareness coding."""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from rc.config import repo_root
from rc.eval_awareness_main import run_eval_awareness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tag", default="main_v1")
    parser.add_argument("--forecast-only", action="store_true")
    parser.add_argument("--dashboard-usd", type=float, default=None)
    parser.add_argument("--post-dashboard-usd", type=float, default=None)
    parser.add_argument("--cap-usd", type=float, default=55.0)
    args = parser.parse_args()
    root = repo_root()
    load_dotenv(root / ".env", override=False)
    summary = run_eval_awareness(
        run_tag=args.run_tag,
        root=root,
        forecast_only=args.forecast_only,
        dashboard_usd=args.dashboard_usd,
        post_dashboard_usd=args.post_dashboard_usd,
        cap_usd=args.cap_usd,
    )
    # Totals only
    safe = {
        k: summary[k]
        for k in (
            "n_units",
            "n_flagged_rounds",
            "n_flagged_chains",
            "stopped",
            "reason",
            "ok",
            "to_date_usd",
            "forecast_usd",
            "projected_usd",
            "n_pending",
            "n_units_total",
            "forecast_only",
        )
        if k in summary
    }
    if "meta" in summary:
        safe["api_usd"] = (summary.get("meta") or {}).get("api_usd")
        safe["prompt_hash_ok"] = (summary.get("meta") or {}).get("prompt_hash_ok")
    if "budget_gate" in summary:
        bg = summary["budget_gate"]
        safe["budget"] = {
            "to_date_usd": bg.get("to_date_usd"),
            "forecast_usd": bg.get("forecast_usd"),
            "projected_usd": bg.get("projected_usd"),
            "ok": bg.get("ok"),
        }
    if "n_flagged_chains" in summary:
        (root / "results" / "eval_awareness_main_v1.json").write_text(
            json.dumps(
                {
                    "n_units": summary["n_units"],
                    "n_flagged_rounds": summary["n_flagged_rounds"],
                    "n_flagged_chains": summary["n_flagged_chains"],
                    "flagged_chains": summary["flagged_chains"],
                    "api_usd": (summary.get("meta") or {}).get("api_usd"),
                    "budget_gate": summary.get("budget_gate"),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(safe, indent=2, sort_keys=True))
    if summary.get("stopped"):
        raise SystemExit(f"STOP: {summary.get('reason')}")


if __name__ == "__main__":
    main()
