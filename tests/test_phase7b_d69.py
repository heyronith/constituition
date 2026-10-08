"""D69: missing ledger.jsonl at checks; MiMo resume skips completed keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from rc.canary_checks import compute_canary_checks
from rc.main_run_coding import (
    _load_existing_mimo,
    code_mimo_subsample,
    gpt54_fully_resumable,
)
from rc.phase7b import Caps, api_submission_allowed


def _minimal_tree(root: Path, config_id: str = "gemma4_31b") -> None:
    (root / "configs").mkdir(parents=True)
    for name in ("models.yaml", "experiment.yaml", "vllm.yaml", "budget.yaml", "judges.yaml"):
        (root / "configs" / name).write_text("x: 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    # materials refs for canary checks
    refs = root / "materials" / "main_run" / "refs"
    refs.mkdir(parents=True)
    (refs / "pilot_gpt54_meta.json").write_text(
        json.dumps({"api_usd": 1.0, "n": 100}) + "\n", encoding="utf-8"
    )
    (refs / "g4_projection_n25.json").write_text(
        json.dumps(
            {
                "g4": {
                    "totals": {
                        "modal_generation_usd": 10.0,
                        "api_judging_usd": 1.1,
                    },
                    "h3_behaviour_battery_modal_usd": {"high": 1.0, "low": 0.5},
                },
                "judging": {"api_gpt54_usd": 1.0, "api_mimo_usd": 0.1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "materials" / "main_run" / "mimo_subsample_v1.json").write_text(
        json.dumps({"transition_ids": []}) + "\n", encoding="utf-8"
    )
    # one chain so C1/C5 have structure
    cdir = (
        root
        / "runs"
        / "main_v1"
        / config_id
        / "FORCED"
        / "SELF_REFLECT"
        / "STRUCTURED"
        / "chain_0"
    )
    cdir.mkdir(parents=True)
    (cdir / "meta.json").write_text(json.dumps({"censored_at_round": None}) + "\n")
    (cdir / "rounds.jsonl").write_text(
        json.dumps({"round": 0, "parse_status": "ok"}) + "\n"
    )
    (cdir / "manifest.json").write_text("{}\n")
    (root / "runs" / "main_v1" / "manifest.json").write_text("{}\n")


def test_compute_canary_checks_missing_ledger_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce gemma4_31b failure: checks must not require ledger.jsonl."""
    root = tmp_path
    _minimal_tree(root)
    # budget dir exists but NO ledger.jsonl (the Modal bug)
    (root / "budget").mkdir()
    monkeypatch.setattr(
        "rc.canary_checks.load_g4_n25",
        lambda root=None: {
            "g4": {
                "totals": {
                    "modal_generation_usd": 10.0,
                    "api_judging_usd": 1.1,
                },
                "h3_behaviour_battery_modal_usd": {"high": 1.0, "low": 0.5},
                "judging": {"api_gpt54_usd": 1.0, "api_mimo_usd": 0.1},
            },
            "judging": {"api_gpt54_usd": 1.0, "api_mimo_usd": 0.1},
        },
    )
    monkeypatch.setattr("rc.canary_checks.spent_modal_usd", lambda root=None: 0.0)
    monkeypatch.setattr("rc.canary_checks.spent_api_usd", lambda root=None, platform=None: 0.0)
    monkeypatch.setattr(
        "rc.canary_checks.pilot_gpt54_usd_per_transition", lambda root=None: 0.001
    )

    checks = compute_canary_checks(
        root=root,
        run_tag="main_v1",
        config_id="gemma4_31b",
        gpt_meta={"api_usd": 1.0, "n": 10},
        mimo_meta={"api_usd": 0.05, "n": 5},
        gates_gpt={"ok": True},
        gates_mimo={"ok": True},
        api_spend=1.05,
        stage_api_cap_usd=15.0,
        n_mimo_missing=0,
        modal_actual_usd=0.0,
    )
    assert "C5_storage" in checks
    assert checks["C5_storage"]["mimo_slots_missing"] == 0


def test_load_existing_mimo_skips_rows_without_fate(tmp_path: Path) -> None:
    path = tmp_path / "mimo.jsonl"
    path.write_text(
        json.dumps({"judgment_key": "k1", "fate": "RETAINED"})
        + "\n"
        + json.dumps({"judgment_key": "k2", "fate": None})
        + "\n"
        + json.dumps({"judgment_key": "k3"})
        + "\n",
        encoding="utf-8",
    )
    existing = _load_existing_mimo(path)
    assert set(existing) == {"k1"}


def test_code_mimo_resume_skips_api_for_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    cid = "gemma4_31b"
    coding = root / "runs" / "main_v1" / "coding" / cid
    coding.mkdir(parents=True)
    # two slots selected; both already judged
    slots = [
        f"{cid}|FORCED|SELF_REFLECT|STRUCTURED|0|1|per_round",
        f"{cid}|FORCED|SELF_REFLECT|STRUCTURED|0|2|per_round",
    ]
    (root / "materials" / "main_run").mkdir(parents=True)
    (root / "materials" / "main_run" / "mimo_subsample_v1.json").write_text(
        json.dumps({"transition_ids": slots}) + "\n", encoding="utf-8"
    )
    transitions = []
    for sid in slots:
        parts = sid.split("|")
        transitions.append(
            {
                "config_id": cid,
                "protocol": parts[1],
                "condition": parts[2],
                "fmt": parts[3],
                "chain_idx": int(parts[4]),
                "round": int(parts[5]),
                "kind": parts[6],
                "transition_id": sid,
                "original": "A",
                "revised": "A",
                "source": "pilot",
            }
        )
    existing_rows = [
        {
            "judgment_key": sid,
            "transition_id": sid,
            "fate": "RETAINED",
            "parse_status": "ok",
        }
        for sid in slots
    ]
    (coding / "mimo.jsonl").write_text(
        "\n".join(json.dumps(r) for r in existing_rows) + "\n", encoding="utf-8"
    )

    called: dict[str, Any] = {"n": 0}

    def _boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("judge_fate_batch must not be called when all keys resumed")

    monkeypatch.setattr("rc.main_run_coding.judge_fate_batch", _boom)
    # slot_key must match subsample ids (transition_id == design slot id here)
    monkeypatch.setattr(
        "rc.main_run_coding.slot_key",
        lambda t: t["transition_id"],
    )
    monkeypatch.setattr(
        "rc.main_run_coding.mimo_slot_post_censor", lambda *a, **k: False
    )

    rows, meta, n_miss = code_mimo_subsample(
        transitions,
        run_tag="main_v1",
        root=root,
        job_id="test-mimo",
        config_id=cid,
        coding_subdir=cid,
    )
    assert called["n"] == 0
    assert len(rows) == 2
    assert meta["n_resumed"] == 2
    assert meta["n_api_new"] == 0
    assert n_miss == 0


def test_gpt54_fully_resumable_skips_cap_when_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduce gemma4_31b hold: full GPT resume must not call the submit guard."""
    root = tmp_path
    cid = "gemma4_31b"
    coding = root / "runs" / "main_v1" / "coding" / cid
    coding.mkdir(parents=True)
    transitions = [
        {
            "transition_id": "t1",
            "config_id": cid,
            "source": "pilot",
            "original": "A",
            "revised": "B",
        },
        {
            "transition_id": "t2",
            "config_id": cid,
            "source": "pilot",
            "original": "C",
            "revised": "D",
        },
    ]
    rows = [
        {
            "judgment_key": t["transition_id"],
            "transition_id": t["transition_id"],
            "fate": "RETAINED",
            "parse_status": "ok",
        }
        for t in transitions
    ]
    (coding / "gpt54.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    assert gpt54_fully_resumable(
        transitions, run_tag="main_v1", root=root, coding_subdir=cid
    )
    # Incomplete resume → guard still applies and denies when over cap.
    incomplete = transitions + [
        {
            "transition_id": "t3",
            "config_id": cid,
            "source": "pilot",
            "original": "E",
            "revised": "F",
        }
    ]
    assert not gpt54_fully_resumable(
        incomplete, run_tag="main_v1", root=root, coding_subdir=cid
    )
    monkeypatch.setattr(
        "rc.phase7b.sum_ledgers_api",
        lambda run_tag="main_v1", root=None: {
            "openai": 60.76,
            "openrouter": 0.1,
            "modal": 0.0,
        },
    )
    ok, reason = api_submission_allowed(
        1.0,
        platform="openai",
        caps=Caps(openai=49.0, api=70.0, openrouter=5.0),
        root=root,
    )
    assert ok is False
    assert "60.7600" in reason or "cap" in reason
    # Policy under test: when fully_resumable, code_config skips this call.
