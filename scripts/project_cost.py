#!/usr/bin/env python3
"""G4: project main-run cost for N ∈ {10,15,20,25}."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rc.config import repo_root
from rc.cost_projection import project_main_run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judging-usd-per-transition", type=float, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON summary (default: reports/phase4_g4_projection.json)",
    )
    args = parser.parse_args()
    root = repo_root()
    out = args.out or (root / "reports" / "phase4_g4_projection.json")
    payload = project_main_run(
        judging_usd_per_transition=args.judging_usd_per_transition,
        root=root,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        k: payload[k] for k in ("spent_modal_usd", "remaining_budget_usd", "projections")
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
