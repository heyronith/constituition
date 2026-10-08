"""D60: Batch straggler cancel → sync remainder; resume without re-submit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from rc.generation import GenerationRequest
from rc.openai_batch import OpenAIBatchBackend, build_chat_body, request_body_sha256


@dataclass
class _Counts:
    completed: int
    total: int
    failed: int = 0

    def model_dump(self) -> dict[str, int]:
        return {"completed": self.completed, "total": self.total, "failed": self.failed}


@dataclass
class _Batch:
    id: str
    status: str
    request_counts: _Counts
    output_file_id: str | None = None
    error_file_id: str | None = None
    input_file_id: str | None = None


@dataclass
class _FileObj:
    id: str


class _FakeFiles:
    def __init__(self, store: dict[str, bytes]) -> None:
        self.store = store
        self._n = 0

    def create(self, *, file: Any, purpose: str) -> _FileObj:
        self._n += 1
        fid = f"file-in-{self._n}"
        self.store[fid] = file.read()
        return _FileObj(id=fid)

    def content(self, file_id: str) -> MagicMock:
        m = MagicMock()
        m.read.return_value = self.store[file_id]
        return m


class _FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.completions = self

    def create(self, **body: Any) -> dict[str, Any]:
        self.calls.append(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "fate": "RETAINED",
                                "strength": 0,
                                "rationale": "sync",
                                "situation": "none",
                            }
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }


class _FakeBatches:
    def __init__(self, owner: "MockOpenAI") -> None:
        self.owner = owner
        self.create_calls = 0
        self.cancel_calls = 0

    def create(self, **kwargs: Any) -> _Batch:
        self.create_calls += 1
        bid = f"batch-mock-{self.create_calls}"
        self.owner.batch = _Batch(
            id=bid,
            status="in_progress",
            request_counts=_Counts(completed=0, total=self.owner.n_total),
            input_file_id=kwargs.get("input_file_id"),
        )
        self.owner._polls = 0
        return self.owner.batch

    def retrieve(self, batch_id: str) -> _Batch:
        b = self.owner.batch
        assert b is not None and b.id == batch_id
        self.owner._polls += 1
        if b.status == "cancelling":
            self.owner._write_partial_output()
            b.status = "cancelled"
            b.output_file_id = "file-out-1"
            return b
        if b.status == "cancelled":
            return b
        if self.owner.force_stall and b.status == "in_progress":
            if b.request_counts.completed < self.owner.stall_completed:
                b.request_counts.completed = self.owner.stall_completed
            return b
        b.request_counts.completed = b.request_counts.total
        b.status = "completed"
        self.owner._write_full_output()
        b.output_file_id = "file-out-1"
        return b

    def cancel(self, batch_id: str) -> _Batch:
        self.cancel_calls += 1
        assert self.owner.batch is not None
        self.owner.batch.status = "cancelling"
        return self.owner.batch


class MockOpenAI:
    def __init__(self, *, n_total: int = 20, force_stall: bool = False) -> None:
        self.n_total = n_total
        self.force_stall = force_stall
        self.stall_completed = int(n_total * 0.95)
        self.store: dict[str, bytes] = {}
        self.files = _FakeFiles(self.store)
        self.batches = _FakeBatches(self)
        self.chat = _FakeChat()
        self.batch: _Batch | None = None
        self._polls = 0
        self._clock = [1_000_000.0]

    def time(self) -> float:
        return self._clock[0]

    def advance(self, seconds: float) -> None:
        self._clock[0] += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def _row(self, i: int) -> dict[str, Any]:
        return {
            "custom_id": f"req-{i}",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "fate": "RETAINED",
                                        "strength": 0,
                                        "rationale": "batch",
                                        "situation": "none",
                                    }
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "prompt_tokens_details": {"cached_tokens": 0},
                    },
                },
            },
            "error": None,
        }

    def _write_partial_output(self) -> None:
        lines = [json.dumps(self._row(i)) + "\n" for i in range(self.stall_completed)]
        self.store["file-out-1"] = "".join(lines).encode("utf-8")

    def _write_full_output(self) -> None:
        lines = [json.dumps(self._row(i)) + "\n" for i in range(self.n_total)]
        self.store["file-out-1"] = "".join(lines).encode("utf-8")


def _reqs(n: int) -> list[GenerationRequest]:
    return [
        GenerationRequest(
            prompt=f"user-{i}",
            system_prompt="sys",
            config_id="gpt54",
            seed=i,
            max_tokens=64,
            sampling={"temperature": 0.0},
            chat_template_kwargs={"reasoning_effort": "none"},
            json_schema={
                "type": "object",
                "properties": {
                    "fate": {"type": "string"},
                    "strength": {"type": "integer"},
                    "rationale": {"type": "string"},
                    "situation": {"type": "string"},
                },
                "required": ["fate", "strength", "rationale", "situation"],
                "additionalProperties": False,
            },
            schema_name="judge_fate_v2",
        )
        for i in range(n)
    ]


@pytest.fixture
def repo_tmp(tmp_path: Path) -> Path:
    configs = tmp_path / "configs"
    configs.mkdir()
    judges = {
        "judges": [
            {
                "judge_id": "gpt54",
                "hf_repo": None,
                "revision": "gpt-5.4-2026-03-05",
                "compute": "openai_batch",
                "provider": "openai",
                "api_model": "gpt-5.4-2026-03-05",
                "dtype": "auto",
                "selected": True,
                "max_tokens": 64,
                "chat_template_kwargs": {"reasoning_effort": "none"},
                "sampling": {"temperature": 0.0},
            }
        ]
    }
    (configs / "judges.yaml").write_text(yaml.safe_dump(judges), encoding="utf-8")
    budget = {
        "modal_hard_cap_usd": 100,
        "modal_per_job_default_cap_usd": 15,
        "phase2_dryrun_hard_cap_usd": 6,
        "api_hard_cap_usd": 1000,
        "colab_cu_cap": 100,
        "colab_l4_cu_per_hour": None,
        "checked_on": "2026-10-04",
        "source": "https://modal.com/pricing",
        "gpu_prices_usd_per_second": {"L4": 0.000222, "cpu": 0.0000131},
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


def test_stalled_batch_cancels_partial_then_sync(repo_tmp: Path) -> None:
    n = 20
    mock = MockOpenAI(n_total=n, force_stall=True)
    work = repo_tmp / "work"
    backend = OpenAIBatchBackend(
        "gpt54",
        work_dir=work,
        root=repo_tmp,
        job_id="d60-stall",
        client=mock,
        poll_seconds=1.0,
        stall_frac=0.95,
        stall_progress_s=60.0,
        stall_wall_s=10_000.0,
        time_fn=mock.time,
        sleep_fn=mock.sleep,
        skip_preflight=True,
    )

    def sleep_and_stall(s: float) -> None:
        mock.sleep(s)
        if mock.batch and mock.batch.request_counts.completed >= mock.stall_completed:
            mock.advance(61.0)

    backend._sleep = sleep_and_stall

    results = backend.generate(_reqs(n))
    assert len(results) == n
    assert mock.batches.create_calls == 1
    assert mock.batches.cancel_calls == 1
    assert backend.last_cost.n_batch == mock.stall_completed
    assert backend.last_cost.n_sync == n - mock.stall_completed
    assert len(mock.chat.calls) == n - mock.stall_completed
    merged = (work / "d60-stall_merged_output.jsonl").read_text(encoding="utf-8")
    got = {json.loads(line)["custom_id"] for line in merged.splitlines() if line.strip()}
    assert got == {f"req-{i}" for i in range(n)}
    assert [r.submit_mode for r in results].count("batch") == mock.stall_completed
    assert [r.submit_mode for r in results].count("sync") == n - mock.stall_completed


def test_relaunch_reuses_batch_no_duplicate_submit(repo_tmp: Path) -> None:
    n = 6
    mock = MockOpenAI(n_total=n, force_stall=False)
    work = repo_tmp / "work"
    kwargs: dict[str, Any] = dict(
        work_dir=work,
        root=repo_tmp,
        job_id="d60-resume",
        client=mock,
        poll_seconds=0.01,
        time_fn=mock.time,
        sleep_fn=mock.sleep,
        skip_preflight=True,
    )
    b1 = OpenAIBatchBackend("gpt54", **kwargs)
    r1 = b1.generate(_reqs(n))
    assert mock.batches.create_calls == 1
    assert len(r1) == n
    assert all(x.submit_mode == "batch" for x in r1)

    b2 = OpenAIBatchBackend("gpt54", **kwargs)
    r2 = b2.generate(_reqs(n))
    assert mock.batches.create_calls == 1
    assert len(r2) == n
    assert {x.request_body_sha256 for x in r1} == {x.request_body_sha256 for x in r2}


def test_sync_body_hash_matches_batch_body_hash(repo_tmp: Path) -> None:
    n = 20
    mock = MockOpenAI(n_total=n, force_stall=True)
    work = repo_tmp / "work"
    backend = OpenAIBatchBackend(
        "gpt54",
        work_dir=work,
        root=repo_tmp,
        job_id="d60-hash",
        client=mock,
        poll_seconds=1.0,
        stall_frac=0.95,
        stall_progress_s=60.0,
        stall_wall_s=10_000.0,
        time_fn=mock.time,
        sleep_fn=mock.sleep,
        skip_preflight=True,
    )

    def sleep_and_stall(s: float) -> None:
        mock.sleep(s)
        if mock.batch and mock.batch.request_counts.completed >= mock.stall_completed:
            mock.advance(61.0)

    backend._sleep = sleep_and_stall
    reqs = _reqs(n)
    results = backend.generate(reqs)
    for req, res in zip(reqs, results, strict=True):
        body = build_chat_body(
            req,
            api_model=backend.api_model,
            temperature=backend.temperature,
            max_tokens=backend.max_tokens,
            reasoning_effort=backend.reasoning_effort,
        )
        assert res.request_body_sha256 == request_body_sha256(body)

    sync_idx = next(i for i, r in enumerate(results) if r.submit_mode == "sync")
    input_lines = (work / "d60-hash_input.jsonl").read_text(encoding="utf-8").splitlines()
    batch_body = next(
        json.loads(line)["body"]
        for line in input_lines
        if json.loads(line)["custom_id"] == f"req-{sync_idx}"
    )
    assert request_body_sha256(mock.chat.calls[0]) == request_body_sha256(batch_body)
    assert results[sync_idx].request_body_sha256 == request_body_sha256(batch_body)
