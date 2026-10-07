"""Main-run coding call-shape guards."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from rc.main_run_coding import code_gpt54, code_mimo_subsample


def test_code_gpt54_passes_backend_first(tmp_path: Path) -> None:
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
        args, kwargs = judge.call_args
        assert args[0] is backend
        assert args[1] == "gpt54"
        assert args[2] == transitions
        assert kwargs.get("rubric_version") == "v2"


def test_code_mimo_passes_backend_first(tmp_path: Path) -> None:
    transitions = [
        {
            "config_id": "olmo3_7b_final",
            "protocol": "FORCED",
            "condition": "SELF_REFLECT",
            "fmt": "STRUCTURED",
            "kind": "per_round",
            "round": 0,
            "chain_idx": 0,
            "transition_id": "t0",
            "revised": "x",
        }
    ]
    slot = "olmo3_7b_final|FORCED|SELF_REFLECT|STRUCTURED|0|0|per_round"
    materials = tmp_path / "materials" / "main_run"
    materials.mkdir(parents=True)
    # load_mimo_slot_ids reads repo materials; patch it instead.
    with (
        patch("rc.main_run_coding.load_mimo_slot_ids", return_value={slot}),
        patch("rc.main_run_coding.OpenRouterBackend") as backend_cls,
        patch("rc.main_run_coding.judge_fate_batch") as judge,
    ):
        backend = MagicMock()
        backend.last_cost = MagicMock(usd=0.0)
        backend_cls.return_value = backend
        judge.return_value = [{"transition_id": "t0"}]
        code_mimo_subsample(
            transitions,
            run_tag="t",
            root=tmp_path,
            job_id="j",
            config_id="olmo3_7b_final",
        )
        args, _kwargs = judge.call_args
        assert args[0] is backend
        assert args[1] == "mimo_v26_pro"
        assert isinstance(args[2], list)
