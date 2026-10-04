"""Reasoning split and MockBackend behaviour (no GPU)."""

from __future__ import annotations

from rc.generation import (
    GenerationResult,
    MockBackend,
    apply_thinking_token_policy,
    build_request,
    expects_reasoning,
    max_tokens_for,
    split_reasoning,
)


def test_qwen_think_split() -> None:
    raw = "<think>\nstep one\nstep two\n</think>\n{\"ok\": true}"
    final, reasoning, flags = split_reasoning("qwen38_27b_think", raw)
    assert final == '{"ok": true}'
    assert reasoning is not None and "step one" in reasoning
    assert "thinking_leak" not in flags


def test_qwen_nothink_leak_flag() -> None:
    raw = "<think>\nsecret\n</think>\nfinal answer"
    final, reasoning, flags = split_reasoning("qwen38_27b_nothink", raw)
    assert final == "final answer"
    assert reasoning == "secret"
    assert "thinking_leak" in flags


def test_gemma_thought_channel_leak() -> None:
    raw = "<|channel|>thought\ninternal plan\n<channel|>\nvisible answer"
    final, reasoning, flags = split_reasoning("gemma4_12b", raw)
    assert final == "visible answer"
    assert reasoning == "internal plan"
    assert "thinking_leak" in flags


def test_non_thinking_policy_zero_reasoning_tokens() -> None:
    result = GenerationResult(
        text_final="hi",
        text_reasoning="leak",
        n_prompt_tokens=1,
        n_output_tokens=2,
        n_reasoning_tokens=3,
        finish_reason="stop",
        latency_s=0.1,
        flags=[],
    )
    out = apply_thinking_token_policy("gemma4_12b", result)
    assert "thinking_leak" in out.flags


def test_mock_backend_scripted_and_records_calls() -> None:
    backend = MockBackend(
        [
            "<think>\na\n</think>\nDONE",
            "plain",
        ]
    )
    req_think = build_request("p1", "qwen38_27b_think", seed=1)
    req_plain = build_request("p2", "olmo3_7b_final", seed=2)
    out = backend.generate([req_think, req_plain])
    assert len(out) == 2
    assert out[0].text_final == "DONE"
    assert out[0].n_reasoning_tokens > 0
    assert out[1].text_reasoning is None
    assert len(backend.calls) == 1
    assert expects_reasoning("qwen38_27b_think")
    assert not expects_reasoning("qwen38_27b_nothink")
    assert max_tokens_for("qwen38_27b_think") == 16384
    assert max_tokens_for("gemma4_12b") == 4096
