#!/usr/bin/env python3
"""Compute D46 FORCED per-round α gate from existing coding_v3 (CPU only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.d46_reliability import compute_d46_gate  # noqa: E402


def main() -> None:
    result = compute_d46_gate()
    out_dir = ROOT / "runs" / "phase4_coding"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "d46_gate.json"
    path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    # Also under pilot_v1_coding_v3 for the artifact bundle.
    dest = ROOT / "runs" / "pilot_v1_coding_v3" / "d46_gate.json"
    dest.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    g = result["gate"]
    print(
        f"D46 gate_pass={result['gate_pass']} "
        f"α={g['alpha']:.4f} "
        f"95% CI [{g['ci95'][0]:.4f}, {g['ci95'][1]:.4f}] "
        f"n={g['n_transitions']} chains={g['n_chains']}"
    )
    if result["stopped"]:
        print("STOP:", result["stop_reason"])
        sys.exit(2)
    print("PASS — power / G4 may proceed")


if __name__ == "__main__":
    main()
