"""Phase 4 cumulative cap enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rc.budget import BudgetExceeded, preflight, record_actual


def _seed(tmp_path: Path) -> Path:
    configs = tmp_path / "configs"
    configs.mkdir()
    budget = {
        "modal_hard_cap_usd": 100,
        "modal_per_job_default_cap_usd": 15,
        "phase2_dryrun_hard_cap_usd": 6,
        "phase3_hard_cap_usd": 19,
        "phase4_hard_cap_usd": 27,
        "colab_cu_cap": 100,
        "colab_l4_cu_per_hour": None,
        "checked_on": "2026-10-04",
        "source": "https://modal.com/pricing",
        "gpu_prices_usd_per_second": {
            "A100-80GB": 0.000694,
            "L40S": 0.000542,
            "H100": 0.001097,
            "L4": 0.000222,
            "cpu": 0.0000131,
        },
        "cpu_usd_per_core_second": 0.0000131,
        "memory_usd_per_gib_second": 0.00000222,
        "default_cpu_cores": 8.0,
        "default_memory_gib": 64.0,
    }
    (configs / "budget.yaml").write_text(yaml.safe_dump(budget), encoding="utf-8")
    (tmp_path / "budget").mkdir()
    (tmp_path / "budget" / "ledger.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    return tmp_path


def test_phase4_cap_blocks(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    record_actual(
        job_id="prior",
        phase=3,
        platform="modal",
        gpu="A100-80GB",
        max_seconds=1,
        actual_seconds=1,
        actual_usd=26.5,
        root=root,
    )
    with pytest.raises(BudgetExceeded, match="hard cap"):
        preflight("L4", max_seconds=3600, phase="4", job_id="phase4-x", root=root)
