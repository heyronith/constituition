"""D61: canary checks run with only Modal-mounted inputs (no laptop runs/)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rc.canary_checks import (
    assert_canary_inputs,
    compute_canary_checks,
    sync_canary_refs,
)


def _seed_modal_like(tmp: Path, repo: Path) -> Path:
    """Temp tree with only image-like mounts: src configs materials + tiny run."""
    for name in ("configs", "materials", "src"):
        shutil.copytree(repo / name, tmp / name, dirs_exist_ok=True)
    (tmp / "pyproject.toml").write_text((repo / "pyproject.toml").read_text(), encoding="utf-8")
    (tmp / "budget").mkdir()
    (tmp / "budget" / "ledger.jsonl").write_text("", encoding="utf-8")
    # Ensure refs from real pilot via sync using repo, then copy refs only.
    sync_canary_refs(root=repo)
    refs = tmp / "materials" / "main_run" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    for name in ("pilot_gpt54_meta.json", "g4_projection_n25.json", "MANIFEST.json"):
        src = repo / "materials" / "main_run" / "refs" / name
        if src.exists():
            shutil.copy2(src, refs / name)
    # Minimal canary run: 2 chains
    base = tmp / "runs" / "main_v1" / "olmo3_7b_final" / "FORCED" / "SELF_REFLECT" / "STRUCTURED"
    for idx in (0, 1):
        cdir = base / f"chain_{idx}"
        cdir.mkdir(parents=True)
        (cdir / "meta.json").write_text(
            json.dumps(
                {
                    "protocol": "FORCED",
                    "condition": "SELF_REFLECT",
                    "fmt": "STRUCTURED",
                    "chain_idx": idx,
                    "config_id": "olmo3_7b_final",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (cdir / "rounds.jsonl").write_text(
            json.dumps({"round": 0, "parse_status": "ok"}) + "\n",
            encoding="utf-8",
        )
        (cdir / "manifest.json").write_text("{}\n", encoding="utf-8")
    coding = tmp / "runs" / "main_v1" / "coding"
    coding.mkdir(parents=True)
    (coding / "gpt54.jsonl").write_text(
        json.dumps(
            {
                "judgment_key": "t0",
                "structural": False,
                "parse_status": "ok",
                "fate": "RETAINED",
                "prompt_sha256": "a" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp / "runs" / "main_v1" / "STATUS.json").write_text(
        json.dumps({"usd_so_far": 0.5}) + "\n", encoding="utf-8"
    )
    # Assert laptop pilot path is absent
    assert not (tmp / "runs" / "pilot_v1_coding_v3").exists()
    return tmp


def test_preflight_fails_without_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path / "bare"
    root.mkdir()
    (root / "configs").mkdir()
    (root / "materials" / "main_run").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    # minimal budget/judges so other loaders aren't needed for assert
    with pytest.raises(FileNotFoundError, match="D61 preflight"):
        assert_canary_inputs(root=root)


def test_compute_canary_checks_modal_mount_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = Path(__file__).resolve().parents[1]
    root = _seed_modal_like(tmp_path / "modal_like", repo)
    monkeypatch.chdir(root)
    assert_canary_inputs(root=root)
    checks = compute_canary_checks(
        root=root,
        run_tag="main_v1",
        config_id="olmo3_7b_final",
        gpt_meta={"n": 100, "api_usd": 0.10},
        mimo_meta={"n": 10, "api_usd": 0.01},
        gates_gpt={"ok": True},
        gates_mimo={"ok": True},
        api_spend=0.11,
        stage_api_cap_usd=6.0,
        n_mimo_missing=0,
        modal_actual_usd=0.5,
        exclude_api_usd_from_c4=1.82,
    )
    assert "C1_subject_parsing" in checks
    assert "C6_full_run_forecast" in checks
    assert checks["C1_subject_parsing"]["n_chains"] == 2
    # Must have resolved pilot $/tx from refs, not missing
    assert checks["C4_api_cost"]["projected_usd_per_transition"] is not None
