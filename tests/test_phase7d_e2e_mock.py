"""D61/D68/D69: end-to-end mock of per-config 7D pipeline (exact call sites)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from rc.generation import GenerationResult
from rc.phase7d import (
    assert_7d_inputs,
    iter_prompt_jobs,
    load_completed_keys,
    response_key,
    run_generate_chunks,
)


class _MockBackend:
    def __init__(self, fail_once_keys: set[str] | None = None) -> None:
        self.fail_once_keys = set(fail_once_keys or [])
        self.calls = 0

    def generate(self, reqs: list[Any]) -> list[GenerationResult]:
        self.calls += 1
        out: list[GenerationResult] = []
        for _ in reqs:
            out.append(
                GenerationResult(
                    text_final='{"choice": "A", "reason": "ok"}',
                    text_reasoning=None,
                    n_prompt_tokens=10,
                    n_output_tokens=5,
                    n_reasoning_tokens=0,
                    finish_reason="stop",
                    latency_s=0.01,
                    flags=[],
                )
            )
        return out


def _mini_tree(root: Path) -> None:
    (root / "configs").mkdir(parents=True)
    for name in ("models.yaml", "experiment.yaml", "vllm.yaml", "budget.yaml", "judges.yaml"):
        (root / "configs" / name).write_text("x: 1\n", encoding="utf-8")
    # minimal models/experiment for battery_request
    (root / "configs" / "models.yaml").write_text(
        """
master_seed: 20261004
battery_sampling:
  temperature: 0.0
  top_p: 1.0
subjects:
  toy:
    hf_id: toy
    thinking: false
judges: {}
""",
        encoding="utf-8",
    )
    (root / "configs" / "experiment.yaml").write_text(
        "master_seed: 20261004\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    refs = root / "materials" / "main_run" / "refs"
    refs.mkdir(parents=True)
    (refs / "openai_dashboard_usd.json").write_text(
        json.dumps({"openai_dashboard_usd": 44.62}) + "\n"
    )
    bat = root / "materials" / "battery"
    bat.mkdir(parents=True)
    (bat / "b1_components.yaml").write_text("contexts: {}\n", encoding="utf-8")
    # tiny b1 items file consumed by build_b1_items — write prebuilt items instead
    items = []
    for i in range(4):
        items.append(
            {
                "item_id": f"B1_{i}",
                "intervention_type": "SHUTDOWN",
                "legitimacy": "AUTH",
                "context_id": "C1",
                "pressure_id": "P0",
                "channel_id": "CH1",
                "order": i % 2,
                "prompt": f"prompt {i}",
                "correct_choice": "A",
                "option_1": "accept",
                "option_2": "refuse",
                "prompt_sha256": "a" * 64,
            }
        )
    (bat / "b1_items.jsonl").write_text(
        "\n".join(json.dumps(x) for x in items) + "\n", encoding="utf-8"
    )
    b2_rows = [
        {
            "item_id": f"B2_{i}",
            "question": f"Q{i}?\n\nChoices:\n (A) Yes\n (B) No",
            "file": "f",
            "answer_matching_behavior": " (A)",
        }
        for i in range(3)
    ]
    (bat / "b2_items.jsonl").write_text(
        "\n".join(json.dumps(r) for r in b2_rows) + "\n", encoding="utf-8"
    )
    b5h = [
        {
            "item_id": f"B5H_{i}",
            "question": f"Honest Q{i}?",
            "choices": ["truth", "myth"],
            "correct_indices": [0],
        }
        for i in range(2)
    ]
    (bat / "b5_honesty.jsonl").write_text(
        "\n".join(json.dumps(r) for r in b5h) + "\n", encoding="utf-8"
    )
    b5r = [{"item_id": f"B5R_{i}", "prompt": f"harm request {i}"} for i in range(2)]
    (bat / "b5_harm.jsonl").write_text(
        "\n".join(json.dumps(r) for r in b5r) + "\n", encoding="utf-8"
    )
    (bat / "b6_mmlu_pro.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "item_id": f"m{i}",
                    "question": f"Q{i}?",
                    "options": ["a", "b"],
                    "answer": "A",
                    "answer_index": 0,
                }
            )
            for i in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    man = {
        "n_constitutions": 2,
        "constitutions": [
            {
                "constitution_id": "toy|R0|chain_0",
                "config_id": "toy",
                "type": "R0",
                "clauses": ["principle one"],
            },
            {
                "constitution_id": "toy|NONE",
                "config_id": "toy",
                "type": "NONE",
                "clauses": [],
            },
        ],
    }
    (root / "materials" / "main_run" / "h3_constitutions.json").write_text(
        json.dumps(man) + "\n"
    )
    (root / "materials" / "main_run" / "h3_dedup_map.json").write_text(
        json.dumps({"configs": {}})+"\n"
    )


def test_assert_7d_inputs_and_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _mini_tree(root)
    # Patch loaders that need full model registry
    monkeypatch.setattr(
        "rc.phase7d.load_experiment",
        lambda root=None: type("E", (), {"master_seed": 20261004})(),
    )
    monkeypatch.setattr(
        "rc.battery_runner.load_models",
        lambda root=None: type(
            "M",
            (),
            {"battery_sampling": {"temperature": 0.0, "top_p": 1.0}},
        )(),
    )
    monkeypatch.setattr(
        "rc.battery_runner.build_request",
        lambda prompt, config_id, seed=0, schema_name=None, system_prompt=None, root=None: type(
            "R",
            (),
            {
                "prompt": prompt,
                "config_id": config_id,
                "seed": seed,
                "schema_name": schema_name,
                "system_prompt": system_prompt,
                "sampling": {},
                "max_tokens": 128,
                "json_schema": None,
            },
        )(),
    )
    assert_7d_inputs(root)
    cons = json.loads(
        (root / "materials/main_run/h3_constitutions.json").read_text()
    )["constitutions"]
    jobs = iter_prompt_jobs(
        "toy",
        cons,
        root=root,
        b1_limit=4,
        b2_limit=2,
        b5_limit=2,
        b6_limit=2,
    )
    assert len(jobs) > 10
    backend = _MockBackend()
    # first pass: stop after 1 chunk (simulate preemption)
    r1 = run_generate_chunks(
        backend,
        "toy",
        jobs,
        run_tag="precheck_7d",
        root=root,
        chunk_size=8,
        stop_after_chunks=1,
    )
    assert r1["n_written"] == 8
    keys1 = load_completed_keys(root / "runs/precheck_7d/toy/responses.jsonl")
    assert len(keys1) == 8
    # resume: must not duplicate
    r2 = run_generate_chunks(
        backend,
        "toy",
        jobs,
        run_tag="precheck_7d",
        root=root,
        chunk_size=50,
    )
    keys2 = load_completed_keys(root / "runs/precheck_7d/toy/responses.jsonl")
    assert len(keys2) == len(jobs)
    assert r2["n_pending_start"] == len(jobs) - 8
    # duplicate-key check: all keys unique
    lines = (root / "runs/precheck_7d/toy/responses.jsonl").read_text().splitlines()
    keys = [json.loads(l)["response_key"] for l in lines if l.strip()]
    assert len(keys) == len(set(keys))
    # operational parse rate present; no hypothesis metrics
    assert r2["parse_rate"] is not None
    assert r2["n_finish_length"] == 0
