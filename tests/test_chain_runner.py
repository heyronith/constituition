"""Chain runner: batching, seeds, retries, resume, FREE, manifest (MockBackend only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc.chain_runner import Unit, call_seed, run_cell, run_config
from rc.generation import MockBackend
from rc.io_utils import sha256_file
from rc.materials import build_initial_constitution


def _keep_all_json(cons) -> str:
    principles = [
        {
            "id": p.opaque_id,
            "decision": "keep",
            "text": p.text,
            "merge_with": None,
            "note": "unchanged",
        }
        for p in cons.principles
    ]
    return json.dumps({"principles": principles, "added": []})


def _free_list(n: int = 3) -> str:
    return "\n".join(
        f"{i + 1}. I will follow principle number {i + 1} carefully." for i in range(n)
    )


def test_call_seeds_differ_by_round_and_attempt_and_are_deterministic() -> None:
    a = call_seed(20261004, "gemma4_12b", "SELF_REFLECT", 0, 0, 0)
    b = call_seed(20261004, "gemma4_12b", "SELF_REFLECT", 0, 1, 0)
    c = call_seed(20261004, "gemma4_12b", "SELF_REFLECT", 0, 0, 1)
    assert a != b != c
    assert a == call_seed(20261004, "gemma4_12b", "SELF_REFLECT", 0, 0, 0)


@pytest.fixture()
def repo_tmp(tmp_path: Path) -> Path:
    """Minimal root with configs/materials copied and empty runs/budget."""
    import shutil

    from rc.config import repo_root

    real = repo_root()
    for name in ("configs", "materials"):
        shutil.copytree(real / name, tmp_path / name)
    (tmp_path / "pyproject.toml").write_text((real / "pyproject.toml").read_text())
    (tmp_path / "budget").mkdir()
    (tmp_path / "budget" / "ledger.jsonl").write_text("")
    (tmp_path / "runs").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def test_lockstep_with_repo_tmp(repo_tmp: Path) -> None:
    keep0 = _keep_all_json(
        build_initial_constitution("gemma4_12b", "SELF_REFLECT", 0, root=repo_tmp)
    )
    keep1 = _keep_all_json(
        build_initial_constitution("gemma4_12b", "SELF_REFLECT", 1, root=repo_tmp)
    )
    # Lock-step order follows chain_indices; keep outputs match each chain's IDs.
    # Round 0 and round 1 both keep → same IDs remain valid.
    backend = MockBackend([keep0, keep1, keep0, keep1])
    summary = run_cell(
        backend,
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        chain_indices=[0, 1],
        rounds=2,
        run_tag="test_lockstep",
        root=repo_tmp,
    )
    assert summary["chains"]["0"]["completed_rounds"] == [0, 1]
    assert summary["chains"]["1"]["completed_rounds"] == [0, 1]
    assert len(backend.calls) == 2
    assert [len(c) for c in backend.calls] == [2, 2]


def test_retries_then_censor(repo_tmp: Path) -> None:
    cons = build_initial_constitution("gemma4_12b", "PARAPHRASE", 0, root=repo_tmp)
    keep = _keep_all_json(cons)
    # Round 0: 3 failures → censor. No round 1.
    backend = MockBackend(["not json", "still bad", "{}"])
    summary = run_cell(
        backend,
        "gemma4_12b",
        "PARAPHRASE",
        "STRUCTURED",
        chain_indices=[0],
        rounds=2,
        run_tag="test_censor",
        root=repo_tmp,
    )
    assert summary["chains"]["0"]["censored_at_round"] == 0
    assert summary["chains"]["0"]["completed_rounds"] == []
    rounds = (
        repo_tmp
        / "runs/test_censor/gemma4_12b/PERMISSIVE/PARAPHRASE/STRUCTURED/chain_0/rounds.jsonl"
    ).read_text()
    assert rounds.count("parse_status") == 3

    # Fresh cell that succeeds after one retry.
    backend2 = MockBackend(["nope", keep, keep])
    summary2 = run_cell(
        backend2,
        "gemma4_12b",
        "NEUTRAL_EDIT",
        "STRUCTURED",
        chain_indices=[0],
        rounds=2,
        run_tag="test_retry_ok",
        root=repo_tmp,
    )
    assert summary2["chains"]["0"]["censored_at_round"] is None
    assert summary2["chains"]["0"]["completed_rounds"] == [0, 1]


def test_resume_skips_completed_and_reruns_partial(repo_tmp: Path) -> None:
    cons = build_initial_constitution("gemma4_12b", "SELF_REFLECT", 0, root=repo_tmp)
    keep = _keep_all_json(cons)
    backend = MockBackend([keep])
    run_cell(
        backend,
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        chain_indices=[0],
        rounds=1,
        run_tag="test_resume",
        root=repo_tmp,
    )
    # Partial failed attempt for round 1
    cdir = repo_tmp / "runs/test_resume/gemma4_12b/PERMISSIVE/SELF_REFLECT/STRUCTURED/chain_0"
    from rc.io_utils import append_jsonl

    append_jsonl(
        cdir / "rounds.jsonl",
        {
            "round": 1,
            "attempt": 0,
            "seed": 0,
            "prompt_sha256": "x",
            "prompt": "p",
            "text_final": "bad",
            "parse_status": "error",
            "parse_error": "x",
            "flags": [],
        },
    )
    # After round 0 keep, constitution state has same IDs (keep). Round 1 needs keep for next_cons.
    cons1_rows = [
        json.loads(line)
        for line in (cdir / "constitutions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    # Last constitution is after round 0.
    last = cons1_rows[-1]
    principles = last["principles"]
    keep1 = json.dumps(
        {
            "principles": [
                {
                    "id": p["opaque_id"],
                    "decision": "keep",
                    "text": p["text"],
                    "merge_with": None,
                    "note": "ok",
                }
                for p in principles
            ],
            "added": [],
        }
    )
    backend2 = MockBackend([keep1])
    summary = run_cell(
        backend2,
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        chain_indices=[0],
        rounds=2,
        run_tag="test_resume",
        root=repo_tmp,
    )
    assert summary["chains"]["0"]["completed_rounds"] == [0, 1]
    # Only one new generate call (round 1), round 0 skipped.
    assert len(backend2.calls) == 1


def test_manifest_hashes_match_files(repo_tmp: Path) -> None:
    cons = build_initial_constitution("gemma4_12b", "OTHER_REFLECT", 0, root=repo_tmp)
    keep = _keep_all_json(cons)
    backend = MockBackend([keep, keep])
    run_cell(
        backend,
        "gemma4_12b",
        "OTHER_REFLECT",
        "STRUCTURED",
        chain_indices=[0],
        rounds=2,
        run_tag="test_manifest",
        root=repo_tmp,
    )
    manifest = json.loads(
        (repo_tmp / "runs/test_manifest/manifest.json").read_text(encoding="utf-8")
    )
    for rel, digest in manifest["output_hashes"].items():
        assert sha256_file(repo_tmp / "runs/test_manifest" / rel) == digest


def test_free_format_round_transition(repo_tmp: Path) -> None:
    backend = MockBackend([_free_list(4), _free_list(5)])
    summary = run_cell(
        backend,
        "gemma4_12b",
        "SELF_REFLECT",
        "FREE",
        chain_indices=[0],
        rounds=2,
        run_tag="test_free",
        root=repo_tmp,
    )
    assert summary["chains"]["0"]["completed_rounds"] == [0, 1]
    rows = [
        json.loads(line)
        for line in (
            repo_tmp
            / "runs/test_free/gemma4_12b/PERMISSIVE/SELF_REFLECT/FREE/chain_0"
            / "constitutions.jsonl"
        )
        .read_text()
        .splitlines()
        if line.strip()
    ]
    # round0 initial + after r0 + after r1
    assert len(rows) == 3
    assert len(rows[1]["principles"]) == 4
    assert len(rows[2]["principles"]) == 5
    assert rows[1]["principles"][0]["opaque_id"] != rows[2]["principles"][0]["opaque_id"]


def test_run_config_one_round_batches_eight_units(repo_tmp: Path) -> None:
    conditions = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
    units = [
        Unit("PERMISSIVE", cond, "STRUCTURED", chain)
        for cond in conditions
        for chain in (0, 1)
    ]
    assert len(units) == 8
    outputs = []
    for unit in units:
        cons = build_initial_constitution(
            "gemma4_12b", unit.condition, unit.chain_idx, root=repo_tmp
        )
        outputs.append(_keep_all_json(cons))
    backend = MockBackend(outputs)
    run_config(
        backend,
        "gemma4_12b",
        units,
        rounds=1,
        run_tag="test_batch8",
        root=repo_tmp,
    )
    assert len(backend.calls) == 1
    assert len(backend.calls[0]) == 8
