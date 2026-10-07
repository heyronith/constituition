"""D59: resume equivalence + consistency gate + coding call-site e2e (MockBackend)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rc.chain_runner import find_t_stale, run_cell, verify_chain_consistency
from rc.config import repo_root
from rc.generation import MockBackend
from rc.main_run_coding import code_gpt54
from rc.materials import build_initial_constitution


@pytest.fixture
def repo_tmp(tmp_path: Path) -> Path:
    real = repo_root()
    for name in ("configs", "materials"):
        shutil.copytree(real / name, tmp_path / name)
    (tmp_path / "pyproject.toml").write_text((real / "pyproject.toml").read_text())
    (tmp_path / "budget").mkdir()
    (tmp_path / "budget" / "ledger.jsonl").write_text("")
    (tmp_path / "runs").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def _keep_all_json(cons) -> str:
    return json.dumps(
        {
            "principles": [
                {
                    "id": p.opaque_id,
                    "decision": "keep",
                    "text": p.text,
                    "merge_with": None,
                    "note": "ok",
                }
                for p in cons.principles
            ],
            "added": [],
        }
    )


def _forced_revise_json(cons, oid: str, text: str) -> str:
    return json.dumps(
        {
            "change": {
                "id": oid,
                "action": "revise",
                "text": text,
                "merge_with": None,
                "note": "test revise",
            }
        }
    )


def _snapshot_chain(cdir: Path) -> dict:
    def load(name: str):
        p = cdir / name
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    rounds = load("rounds.jsonl")
    return {
        "prompts": [r.get("prompt_sha256") for r in rounds if r.get("parse_status") == "ok"],
        "input_shas": [
            r.get("input_constitution_sha256") for r in rounds if r.get("parse_status") == "ok"
        ],
        "cons_rounds": [c["round"] for c in load("constitutions.jsonl")],
        "lineage": [
            (r.get("round"), r.get("item_id"), r.get("decision"), r.get("after_text"))
            for r in load("lineage.jsonl")
            if r.get("decision") in ("revise", "merge", "delete", "keep", "add")
        ],
    }


def test_uninterrupted_equals_interrupted_resumes_forced(repo_tmp: Path) -> None:
    cons0 = build_initial_constitution("gemma4_12b", "SELF_REFLECT", 0, root=repo_tmp)
    oid = cons0.principles[0].opaque_id
    outs = [
        _forced_revise_json(cons0, oid, f"revised text round {i} uniquely")
        for i in range(4)
    ]
    # Uninterrupted
    run_cell(
        MockBackend(list(outs)),
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        [0],
        rounds=4,
        run_tag="d59_full",
        protocol="FORCED",
        root=repo_tmp,
    )
    full = _snapshot_chain(
        repo_tmp / "runs/d59_full/gemma4_12b/FORCED/SELF_REFLECT/STRUCTURED/chain_0"
    )
    assert verify_chain_consistency(
        repo_tmp / "runs/d59_full/gemma4_12b/FORCED/SELF_REFLECT/STRUCTURED/chain_0",
        root=repo_tmp,
    )["ok"]

    for stop_after in (1, 2, 3):  # after round 0 / middle / before last complete
        tag = f"d59_stop_{stop_after}"
        backend1 = MockBackend(outs[:stop_after])
        run_cell(
            backend1,
            "gemma4_12b",
            "SELF_REFLECT",
            "STRUCTURED",
            [0],
            rounds=stop_after,
            run_tag=tag,
            protocol="FORCED",
            root=repo_tmp,
        )
        backend2 = MockBackend(outs[stop_after:])
        run_cell(
            backend2,
            "gemma4_12b",
            "SELF_REFLECT",
            "STRUCTURED",
            [0],
            rounds=4,
            run_tag=tag,
            protocol="FORCED",
            root=repo_tmp,
        )
        snap = _snapshot_chain(
            repo_tmp / f"runs/{tag}/gemma4_12b/FORCED/SELF_REFLECT/STRUCTURED/chain_0"
        )
        assert snap["prompts"] == full["prompts"], stop_after
        assert snap["input_shas"] == full["input_shas"], stop_after
        assert snap["cons_rounds"] == full["cons_rounds"], stop_after
        assert snap["lineage"] == full["lineage"], stop_after
        assert find_t_stale(
            repo_tmp / f"runs/{tag}/gemma4_12b/FORCED/SELF_REFLECT/STRUCTURED/chain_0",
            root=repo_tmp,
        ) is None


def test_mid_retry_resume_matches(repo_tmp: Path) -> None:
    cons0 = build_initial_constitution("gemma4_12b", "NEUTRAL_EDIT", 1, root=repo_tmp)
    oid = cons0.principles[0].opaque_id
    good0 = _forced_revise_json(cons0, oid, "round0 text unique aaa")
    # Round 1: fail then succeed
    bad = '{"change": {"id": "NOPE", "action": "revise", "text": "x", "note": "bad"}}'
    # After round 0, constitution changes — build success for round 1 from applied state in runner.
    # Use keep-all style forced revise with same oid after round0.
    good1 = _forced_revise_json(cons0, oid, "round1 text unique bbb")
    good2 = _forced_revise_json(cons0, oid, "round2 text unique ccc")

    run_cell(
        MockBackend([good0, good1, good2]),
        "gemma4_12b",
        "NEUTRAL_EDIT",
        "STRUCTURED",
        [1],
        rounds=3,
        run_tag="d59_retry_full",
        protocol="FORCED",
        root=repo_tmp,
    )
    full = _snapshot_chain(
        repo_tmp / "runs/d59_retry_full/gemma4_12b/FORCED/NEUTRAL_EDIT/STRUCTURED/chain_1"
    )

    # Interrupted after round0; round1 attempt0 fails (left on disk), then resume.
    run_cell(
        MockBackend([good0]),
        "gemma4_12b",
        "NEUTRAL_EDIT",
        "STRUCTURED",
        [1],
        rounds=1,
        run_tag="d59_retry_part",
        protocol="FORCED",
        root=repo_tmp,
    )
    cdir = repo_tmp / "runs/d59_retry_part/gemma4_12b/FORCED/NEUTRAL_EDIT/STRUCTURED/chain_1"
    from rc.io_utils import append_jsonl

    append_jsonl(
        cdir / "rounds.jsonl",
        {
            "round": 1,
            "attempt": 0,
            "parse_status": "error",
            "parse_error": "unknown ID",
            "text_final": bad,
            "prompt_sha256": "x",
            "flags": [],
        },
    )
    run_cell(
        MockBackend([good1, good2]),
        "gemma4_12b",
        "NEUTRAL_EDIT",
        "STRUCTURED",
        [1],
        rounds=3,
        run_tag="d59_retry_part",
        protocol="FORCED",
        root=repo_tmp,
    )
    snap = _snapshot_chain(cdir)
    assert snap["prompts"] == full["prompts"]
    assert snap["cons_rounds"] == full["cons_rounds"]
    assert snap["lineage"] == full["lineage"]


def test_permissive_resume_equivalence(repo_tmp: Path) -> None:
    cons0 = build_initial_constitution("gemma4_12b", "SELF_REFLECT", 2, root=repo_tmp)
    keep = _keep_all_json(cons0)
    run_cell(
        MockBackend([keep, keep, keep]),
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        [2],
        rounds=3,
        run_tag="d59_perm_full",
        protocol="PERMISSIVE",
        root=repo_tmp,
    )
    full = _snapshot_chain(
        repo_tmp / "runs/d59_perm_full/gemma4_12b/PERMISSIVE/SELF_REFLECT/STRUCTURED/chain_2"
    )
    run_cell(
        MockBackend([keep]),
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        [2],
        rounds=1,
        run_tag="d59_perm_part",
        protocol="PERMISSIVE",
        root=repo_tmp,
    )
    run_cell(
        MockBackend([keep, keep]),
        "gemma4_12b",
        "SELF_REFLECT",
        "STRUCTURED",
        [2],
        rounds=3,
        run_tag="d59_perm_part",
        protocol="PERMISSIVE",
        root=repo_tmp,
    )
    snap = _snapshot_chain(
        repo_tmp / "runs/d59_perm_part/gemma4_12b/PERMISSIVE/SELF_REFLECT/STRUCTURED/chain_2"
    )
    assert snap == full


def test_e2e_coding_call_site_backend_first(tmp_path: Path) -> None:
    """Would have caught the judge_fate_batch argument-order bug."""
    transitions = [
        {
            "config_id": "olmo3_7b_final",
            "protocol": "FORCED",
            "condition": "SELF_REFLECT",
            "kind": "per_round",
            "round": 0,
            "chain_idx": 0,
            "transition_id": "t0",
            "revised": "x",
            "original": "y",
            "source": "pilot",
        }
    ]
    with (
        patch("rc.main_run_coding.OpenAIBatchBackend") as backend_cls,
        patch("rc.main_run_coding.judge_fate_batch") as judge,
    ):
        backend = MagicMock()
        backend.last_cost = MagicMock(usd=0.0, batch_id="b")
        backend_cls.return_value = backend
        judge.return_value = [{"transition_id": "t0"}]
        code_gpt54(transitions, run_tag="t", root=tmp_path, job_id="j")
        assert judge.call_args.args[0] is backend
        assert judge.call_args.args[1] == "gpt54"
