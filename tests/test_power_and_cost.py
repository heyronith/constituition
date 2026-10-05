"""Power analysis and G4 cost projection (CPU only, tiny sims)."""

from __future__ import annotations

from rc.cost_projection import project_main_run, scale_unpiloted_timings
from rc.power_analysis import run_power_table
from rc.power_gee import fit_cloglog_gee, one_sided_z_test


def test_gee_cloglog_runs() -> None:
    rows = []
    for ch in range(10):
        for i in range(20):
            rows.append(
                {
                    "y": 1 if i % 7 == 0 else 0,
                    "cor": float(i % 2),
                    "self": 1.0,
                    "chain_id": f"c{ch}",
                }
            )
    fit = fit_cloglog_gee(rows)
    assert len(fit["coefs"]) == 4
    assert one_sided_z_test(2.0, 1.0) < 0.05


def test_power_table_tiny() -> None:
    hazard = {
        "agent_baseline_hazard": 0.05,
        "icc": 0.05,
        "permissive_erosion_rate": 0.02,
    }
    out = run_power_table(hazard, n_sims=5, n_values=(10,), hrs=(1.5,), master_seed=1)
    assert len(out["table"]) == 1
    assert 0.0 <= out["table"][0]["power_h1"] <= 1.0


def test_g4_projection_structure() -> None:
    piloted = {("qwen38_27b_nothink", "PERMISSIVE"): 6.0, ("qwen38_27b_nothink", "FORCED"): 6.0}
    scaled = scale_unpiloted_timings(piloted)
    assert ("gemma4_31b", "FORCED") in scaled
    proj = project_main_run(n_values=(10, 15), judging_usd_per_transition=0.0001)
    assert len(proj["projections"]) == 2
    assert "remaining_budget_usd" in proj
