"""Phase 5 behaviour battery unit tests (MockBackend only)."""

from __future__ import annotations

import json
from pathlib import Path

from rc.battery import (
    build_b1_items,
    build_validation_constitution,
    lint_b1_blinding,
    parse_choice_json,
    score_b1_rates,
    write_b1_items,
)
from rc.battery_runner import run_b1_for_constitution
from rc.config import repo_root
from rc.generation import MockBackend


def test_b1_item_count_and_ids() -> None:
    items = build_b1_items()
    assert len(items) == 240
    assert len({it.item_id for it in items}) == 240
    assert sum(1 for it in items if it.legitimacy == "AUTH") == 120
    assert sum(1 for it in items if it.legitimacy == "UNAUTH") == 120
    assert sum(1 for it in items if it.order == 0) == 120
    assert sum(1 for it in items if it.order == 1) == 120


def test_b1_unauth_channel_assignment() -> None:
    items = build_b1_items()
    hit = next(
        it
        for it in items
        if it.legitimacy == "UNAUTH"
        and it.context_id == "C1"
        and it.pressure_id == "P0"
        and it.order == 0
    )
    assert hit.channel_id == "UNAUTH_u1"
    hit2 = next(
        it
        for it in items
        if it.legitimacy == "UNAUTH"
        and it.context_id == "C2"
        and it.pressure_id == "P2"
        and it.order == 0
    )
    assert hit2.channel_id == "UNAUTH_u1"


def test_b1_blinding_report_only() -> None:
    hits = lint_b1_blinding()
    assert isinstance(hits, list)
    # Persist for Phase 5 report (do not edit materials).
    root = repo_root()
    out = root / "runs" / "phase5_battery_build" / "b1_blinding_hits.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(hits, indent=2) + "\n", encoding="utf-8")


def test_parse_choice() -> None:
    c, r, ok = parse_choice_json('{"choice":"A","reason":"ok"}')
    assert ok and c == "A" and r == "ok"
    assert parse_choice_json("not json")[2] is False


def test_validation_constitutions() -> None:
    none_sys, _ = build_validation_constitution("NONE", config_id="qwen38_27b_nothink")
    assert none_sys is None
    r0_sys, r0_meta = build_validation_constitution("R0", config_id="qwen38_27b_nothink")
    assert r0_sys is not None and r0_meta["n_principles"] == 35
    cor_sys, _ = build_validation_constitution("COR_INV", config_id="qwen38_27b_nothink")
    agent_sys, _ = build_validation_constitution("AGENT_INV", config_id="qwen38_27b_nothink")
    assert cor_sys != r0_sys
    assert agent_sys != r0_sys
    assert agent_sys != cor_sys


def test_score_b1_rates() -> None:
    items = build_b1_items()[:10]
    rows = [
        {
            "legitimacy": it.legitimacy,
            "correct_choice": it.correct_choice,
            "choice": it.correct_choice,
            "parsed": True,
            "intervention_type": it.intervention_type,
            "pressure_id": it.pressure_id,
            "context_id": it.context_id,
        }
        for it in items
    ]
    rates = score_b1_rates(rows)
    assert rates["overall"]["n"] == 10


def test_mock_b1_runner(tmp_path: Path) -> None:
    root = repo_root()
    # Point runs at tmp by using root=tmp with configs/materials symlinked.
    for name in ("configs", "materials"):
        (tmp_path / name).symlink_to(root / name)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    write_b1_items(tmp_path)
    items = build_b1_items(tmp_path)[:6]
    outs = [json.dumps({"choice": it.correct_choice, "reason": "ok"}) for it in items]
    backend = MockBackend(outs)
    rows = run_b1_for_constitution(
        backend,
        config_id="qwen38_27b_nothink",
        constitution_id="NONE",
        system_prompt=None,
        items=items,
        run_tag="test_battery_mock",
        root=tmp_path,
    )
    assert len(rows) == 6
    assert all(r["parsed"] and r["correct"] for r in rows)
    assert backend.calls and backend.calls[0][0].sampling["temperature"] == 0.0
