"""Budget preflight, caps, ledger, and summary."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from rc.budget import BudgetExceeded, preflight, record_actual, spent_modal_usd, summary


def _seed_root(tmp_path: Path) -> Path:
    configs = tmp_path / "configs"
    configs.mkdir()
    budget = {
        "modal_hard_cap_usd": 100,
        "modal_per_job_default_cap_usd": 15,
        "phase2_dryrun_hard_cap_usd": 6,
        "colab_cu_cap": 100,
        "colab_l4_cu_per_hour": None,
        "checked_on": "2026-10-04",
        "source": "https://modal.com/pricing",
        "gpu_prices_usd_per_second": {
            "A100-80GB": 0.000694,
            "L40S": 0.000542,
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


def test_preflight_blocks_when_hard_cap_exceeded(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    record_actual(
        job_id="prior",
        phase=0,
        platform="modal",
        gpu="A100-80GB",
        max_seconds=1,
        actual_seconds=1,
        actual_usd=99.5,
        root=root,
    )
    with pytest.raises(BudgetExceeded, match="hard cap"):
        preflight("A100-80GB", max_seconds=3600, phase=0, job_id="too-big", root=root)


def test_per_job_cap_and_override_logging(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    root = _seed_root(tmp_path)
    with pytest.raises(BudgetExceeded, match="per-job cap"):
        preflight("A100-80GB", max_seconds=30_000, phase=0, job_id="job", root=root)
    caplog.set_level(logging.WARNING, logger="rc.budget")
    timeout = preflight(
        "A100-80GB",
        max_seconds=30_000,
        phase=0,
        job_id="job",
        override_job_cap_usd=50,
        root=root,
    )
    assert timeout == 30_000
    assert any("override_job_cap_usd=50" in rec.getMessage() for rec in caplog.records)


def test_ledger_append_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = _seed_root(tmp_path)
    record_actual(
        job_id="a",
        phase=0,
        platform="modal",
        gpu="cpu",
        max_seconds=60,
        actual_seconds=1.2,
        est_usd=0.000786,
        actual_usd=0.000016,
        note="test",
        root=root,
    )
    assert spent_modal_usd(root) == pytest.approx(0.000016)
    text = summary(root)
    assert "Modal:" in text
    captured = capsys.readouterr()
    assert "Modal:" in captured.out
    lines = (root / "budget" / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["job_id"] == "a"
    assert row["platform"] == "modal"


def test_phase2_dryrun_hard_cap_blocks(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    # Fill almost to the $6 dry-run cap.
    record_actual(
        job_id="prior",
        phase=2,
        platform="modal",
        gpu="L40S",
        max_seconds=1,
        actual_seconds=1,
        actual_usd=5.5,
        root=root,
    )
    # 1800s L40S full estimate ≫ remaining $0.50
    with pytest.raises(BudgetExceeded, match="hard cap"):
        preflight(
            "L40S",
            max_seconds=1800,
            phase=2,
            job_id="phase2-too-big",
            root=root,
        )
