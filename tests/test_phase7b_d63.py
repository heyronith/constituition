"""D63: concurrent config isolation, Batch error classify, canary protection, stale."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rc.chain_runner import _update_run_manifest
from rc.phase7b import (
    assert_not_canary_write,
    classify_openai_batch_error,
    is_stale_status,
    snapshot_canary_tree,
    verify_canary_snapshot,
)


def test_concurrent_manifests_do_not_clobber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "configs").mkdir()
    for name in ("models.yaml", "experiment.yaml", "vllm.yaml"):
        # Minimal stubs — write_run_manifest only hashes these files.
        (root / "configs" / name).write_text("x: 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    # load_experiment needs real experiment — monkeypatch sha helpers via files existing.
    monkeypatch.setattr(
        "rc.chain_runner.load_experiment",
        lambda root=None: type("E", (), {"master_seed": 1})(),
    )
    monkeypatch.setattr("rc.chain_runner.git_sha", lambda root=None: "deadbeef")
    monkeypatch.setattr("rc.chain_runner.sha256_file", lambda p: "a" * 64)

    for cfg in ("cfg_a", "cfg_b"):
        cdir = root / "runs" / "main_v1" / cfg / "FORCED" / "SELF_REFLECT" / "STRUCTURED" / "chain_0"
        cdir.mkdir(parents=True)
        (cdir / "rounds.jsonl").write_text(json.dumps({"round": 0}) + "\n", encoding="utf-8")

    _update_run_manifest("main_v1", root, config_id="cfg_a")
    _update_run_manifest("main_v1", root, config_id="cfg_b")

    ma = json.loads((root / "runs/main_v1/cfg_a/manifest.json").read_text())
    mb = json.loads((root / "runs/main_v1/cfg_b/manifest.json").read_text())
    assert "FORCED/SELF_REFLECT/STRUCTURED/chain_0/rounds.jsonl" in ma["output_hashes"]
    assert "FORCED/SELF_REFLECT/STRUCTURED/chain_0/rounds.jsonl" in mb["output_hashes"]
    # Neither manifest contains the other config's path.
    assert not any("cfg_b" in k for k in ma["output_hashes"])
    assert not any("cfg_a" in k for k in mb["output_hashes"])


def test_canary_write_guard(tmp_path: Path) -> None:
    root = tmp_path
    canary = root / "runs" / "main_v1" / "olmo3_7b_final" / "x.txt"
    canary.parent.mkdir(parents=True)
    canary.write_text("hi\n")
    with pytest.raises(PermissionError, match="canary"):
        assert_not_canary_write(canary, root=root)


def test_classify_openai_errors() -> None:
    assert classify_openai_batch_error("Rate limit exceeded 429") == "rate_limit"
    assert classify_openai_batch_error("enqueued token limit") == "rate_limit"
    assert classify_openai_batch_error("Billing hard limit reached") == "billing"
    assert classify_openai_batch_error("insufficient_quota") == "billing"
    assert classify_openai_batch_error("invalid schema") == "other"


def test_classify_insufficient_quota_429_is_billing_not_rate_limit() -> None:
    """OpenAI uses HTTP 429 for insufficient_quota — must api_budget_hold, not retry."""
    msg = (
        "Error code: 429 - {'error': {'message': 'You exceeded your current quota', "
        "'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}}"
    )
    assert classify_openai_batch_error(msg) == "billing"
    assert (
        classify_openai_batch_error(
            "Error code: 400 - {'error': {'code': 'billing_hard_limit_reached'}}"
        )
        == "billing"
    )


def test_stale_flag() -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert is_stale_status({"state": "running", "last_update_utc": old}) is True
    assert is_stale_status({"state": "api_wait", "last_update_utc": old}) is False
    assert is_stale_status({"state": "running", "batch_state": "in_progress", "last_update_utc": old}) is False
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert is_stale_status({"state": "running", "last_update_utc": fresh}) is False


def test_canary_snapshot_roundtrip(tmp_path: Path) -> None:
    root = tmp_path
    base = root / "runs" / "main_v1" / "olmo3_7b_final" / "FORCED" / "chain_0"
    base.mkdir(parents=True)
    (base / "rounds.jsonl").write_text('{"round":0}\n', encoding="utf-8")
    snap = snapshot_canary_tree(root=root)
    assert verify_canary_snapshot(snap, root=root)["ok"] is True
    (base / "rounds.jsonl").write_text('{"round":0,"x":1}\n', encoding="utf-8")
    assert verify_canary_snapshot(snap, root=root)["ok"] is False
