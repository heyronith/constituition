"""D70: ledger path dedupe + dashboard floor for API guard."""

from __future__ import annotations

import json
from pathlib import Path

from rc.phase7b import (
    OPENAI_DASHBOARD_USD,
    api_submission_allowed,
    load_openai_dashboard_usd,
    sum_ledgers_api,
)


def test_sum_ledgers_api_dedupes_budget_symlink(tmp_path: Path) -> None:
    """Reproduce 60.76 bug: /budget → runs/main_v1/budget must count once."""
    run_tag = "main_v1"
    vol_budget = tmp_path / "runs" / run_tag / "budget"
    vol_budget.mkdir(parents=True)
    row = {
        "platform": "openai",
        "job_id": "phase7b-gpt54-gemma4_31b",
        "actual_usd": 27.30007125,
    }
    (vol_budget / f"ledger_{run_tag}_gemma4_31b.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )
    budget_link = tmp_path / "budget"
    budget_link.symlink_to(vol_budget)
    spent = sum_ledgers_api(run_tag=run_tag, root=tmp_path)
    assert spent["openai"] == 27.30007125


def test_api_guard_uses_d70_dashboard_floor(tmp_path: Path, monkeypatch) -> None:
    refs = tmp_path / "materials" / "main_run" / "refs"
    refs.mkdir(parents=True)
    (refs / "openai_dashboard_usd.json").write_text(
        json.dumps({"openai_dashboard_usd": 44.62}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "rc.phase7b.sum_ledgers_api",
        lambda run_tag="main_v1", root=None: {
            "openai": 27.30,
            "openrouter": 0.63,
            "modal": 0.0,
        },
    )
    from rc.phase7b import Caps

    # Ledger under dashboard → floor applies (44.62 + 9 > openai cap 49).
    ok, reason = api_submission_allowed(
        9.0,
        platform="openai",
        caps=Caps(openai=49.0, api=60.0, openrouter=5.0),
        root=tmp_path,
    )
    assert ok is False
    assert "53.6200" in reason  # 44.62 + 9.0
    assert load_openai_dashboard_usd(tmp_path) == 44.62
    assert OPENAI_DASHBOARD_USD == 44.62
