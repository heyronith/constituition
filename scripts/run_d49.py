"""CPU-only D49: power audit, corrected table, G4 under new scope."""

from __future__ import annotations

import json
import time
from pathlib import Path

from rc.config import repo_root
from rc.d49_power_g4 import run_d49


def main() -> None:
    root = repo_root()
    t0 = time.time()
    print("D49 start", flush=True)
    result = run_d49(root=root, n_sims=20000)
    h, p, g = result["hazard"], result["power"], result["g4"]
    print(
        f"hazard events={h['agent_events']} risk={h['agent_risk']} "
        f"p={h['agent_baseline_hazard']:.6f} ci={h['agent_hazard_ci95']}"
    )
    for row in p["table"]:
        if row["hr"] == 1.5:
            print(
                f"  N={row['n_chains']} H1@1.5 sim={row['power_sim']:.3f} "
                f"analytic={row['power_analytic']:.3f}"
            )
    print("recommended_n", p["recommended_n_hr15"])
    chosen = g["chosen_n"]
    at = g["at_chosen_n"]
    print(
        f"G4 N={chosen} modal_gen=${at['generation']['modal_usd']:.2f} "
        f"api=${at['judging']['api_usd']:.2f} "
        f"fits_modal={at['budget']['generation_fits_remaining_modal']}"
    )
    print(f"done in {time.time()-t0:.1f}s")
    status = {
        "stage": "d49_power_g4",
        "state": "done",
        "decision": "D49",
        "recommended_n": p["recommended_n_hr15"],
        "agent_baseline_hazard": h["agent_baseline_hazard"],
        "agent_hazard_ci95": h["agent_hazard_ci95"],
        "agent_events": h["agent_events"],
        "agent_risk": h["agent_risk"],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = root / "runs" / "phase4_coding" / "STATUS_d49.json"
    path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
