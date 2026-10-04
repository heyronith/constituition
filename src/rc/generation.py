"""Platform-agnostic generation core. Tests use MockBackend only."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from rc.config import load_models, load_vllm, repo_root

# Qwen thinking delimiters (HF chat template / vLLM reasoning parser).
_QWEN_THINK_CLOSE = "</think>"
# Gemma 4 thought channel (model card): <|channel>thought\n ... <channel|>
_GEMMA_THOUGHT_RE = re.compile(
    r"<\|channel\|>thought\n(?P<thought>.*?)<channel\|>",
    re.DOTALL,
)


@dataclass
class GenerationRequest:
    prompt: str
    config_id: str
    sampling: dict[str, Any]
    chat_template_kwargs: dict[str, Any]
    max_tokens: int
    seed: int


@dataclass
class GenerationResult:
    text_final: str
    text_reasoning: str | None
    n_prompt_tokens: int
    n_output_tokens: int
    n_reasoning_tokens: int
    finish_reason: str
    latency_s: float
    flags: list[str] = field(default_factory=list)


class Backend(Protocol):
    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]: ...


def load_lock_revision(config_id: str, root: Path | None = None) -> tuple[str, str]:
    root = root or repo_root()
    lock = yaml.safe_load((root / "configs" / "model_revisions.lock.yaml").read_text())
    for row in lock.get("subjects", []):
        if row.get("config_id") == config_id:
            return row["exact_repo_id"], row["sha"]
    raise KeyError(f"no lock entry for {config_id}")


def max_tokens_for(config_id: str, root: Path | None = None) -> int:
    vllm = load_vllm(root)
    if config_id == "qwen38_27b_think":
        return vllm.think_max_tokens
    return vllm.default_max_tokens


def max_model_len_for(config_id: str, root: Path | None = None) -> int:
    vllm = load_vllm(root)
    if config_id == "qwen38_27b_think":
        return vllm.think_max_model_len
    # D13: Gemma 31B uses 16384
    return vllm.default_max_model_len


def expects_reasoning(config_id: str) -> bool:
    return config_id == "qwen38_27b_think"


def build_request(
    prompt: str,
    config_id: str,
    seed: int,
    *,
    root: Path | None = None,
) -> GenerationRequest:
    subject = load_models(root).by_id(config_id)
    sampling = dict(subject.sampling) if isinstance(subject.sampling, dict) else {}
    # reasoning_effort belongs in chat_template_kwargs (Qwen jinja), not SamplingParams.
    # https://huggingface.co/Qwen/Qwen3.8-27B
    kwargs = dict(subject.chat_template_kwargs)
    if "reasoning_effort" in sampling:
        kwargs["reasoning_effort"] = sampling.pop("reasoning_effort")
    return GenerationRequest(
        prompt=prompt,
        config_id=config_id,
        sampling=sampling,
        chat_template_kwargs=kwargs,
        max_tokens=max_tokens_for(config_id, root),
        seed=seed,
    )


def split_reasoning(config_id: str, raw: str) -> tuple[str, str | None, list[str]]:
    """Separate reasoning from final answer. Returns (final, reasoning, flags)."""
    flags: list[str] = []
    text = raw

    # Gemma thought-channel leak (thinking off still may emit empty/nonempty channel).
    gemma_match = _GEMMA_THOUGHT_RE.search(text)
    if gemma_match:
        thought = gemma_match.group("thought").strip()
        text = _GEMMA_THOUGHT_RE.sub("", text, count=1).strip()
        if thought:
            flags.append("thinking_leak")
            return text, thought, flags
        # Empty thought block: strip tags, no leak flag.
        return text, None, flags

    if expects_reasoning(config_id) or _QWEN_THINK_CLOSE in text or "<think>" in text:
        # Prefer explicit </think> split (Qwen).
        if _QWEN_THINK_CLOSE in text:
            before, after = text.split(_QWEN_THINK_CLOSE, 1)
            reasoning = before
            for tag in ("<think>", "<|im_start|>", "<|im_end|>"):
                reasoning = reasoning.replace(tag, "")
            reasoning = reasoning.strip()
            final = after.strip()
            if not expects_reasoning(config_id) and reasoning:
                flags.append("thinking_leak")
            return final, reasoning or None, flags
        if expects_reasoning(config_id):
            # No delimiter: treat whole output as final; flag for inspection.
            flags.append("missing_think_close")
            return text, None, flags

    if not expects_reasoning(config_id):
        return text, None, flags
    return text, None, flags


def apply_thinking_token_policy(
    config_id: str, result: GenerationResult
) -> GenerationResult:
    """Enforce n_reasoning_tokens policy and thinking_leak flags."""
    flags = list(result.flags)
    if expects_reasoning(config_id):
        if result.n_reasoning_tokens <= 0 and not (result.text_reasoning or "").strip():
            flags.append("missing_reasoning")
    else:
        if result.n_reasoning_tokens > 0 or (result.text_reasoning or "").strip():
            if "thinking_leak" not in flags:
                flags.append("thinking_leak")
            result.n_reasoning_tokens = max(result.n_reasoning_tokens, 0)
    result.flags = flags
    return result


class MockBackend:
    """Scripted backend for unit tests. No GPU / no vLLM."""

    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = list(outputs or [])
        self.calls: list[list[GenerationRequest]] = []

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        self.calls.append(requests)
        results: list[GenerationResult] = []
        for i, req in enumerate(requests):
            if not self.outputs:
                raise RuntimeError("MockBackend exhausted scripted outputs")
            raw = self.outputs.pop(0)
            final, reasoning, flags = split_reasoning(req.config_id, raw)
            n_reason = len((reasoning or "").split())
            result = GenerationResult(
                text_final=final,
                text_reasoning=reasoning,
                n_prompt_tokens=len(req.prompt.split()),
                n_output_tokens=len(raw.split()),
                n_reasoning_tokens=n_reason,
                finish_reason="stop",
                latency_s=0.001,
                flags=flags,
            )
            results.append(apply_thinking_token_policy(req.config_id, result))
        return results


class VLLMBackend:
    """vLLM offline backend. Instantiated only inside Modal/Colab images."""

    def __init__(
        self,
        config_id: str,
        *,
        model_path: str,
        revision: str | None = None,
        max_model_len: int | None = None,
        gpu_memory_utilization: float | None = None,
        root: Path | None = None,
    ) -> None:
        from vllm import LLM

        vllm_cfg = load_vllm(root)
        self.config_id = config_id
        self._llm = LLM(
            model=model_path,
            revision=revision,
            dtype="bfloat16",
            max_model_len=max_model_len or max_model_len_for(config_id, root),
            gpu_memory_utilization=(
                gpu_memory_utilization
                if gpu_memory_utilization is not None
                else vllm_cfg.gpu_memory_utilization
            ),
            trust_remote_code=True,
        )

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        from vllm import SamplingParams

        results: list[GenerationResult] = []
        # Per-request chat_template_kwargs / seeds: loop (vLLM batching still
        # amortizes the loaded weights; dry-run batches are tiny).
        for req in requests:
            sp = SamplingParams(
                temperature=float(req.sampling.get("temperature", 1.0)),
                top_p=float(req.sampling.get("top_p", 1.0)),
                top_k=int(req.sampling.get("top_k", -1))
                if req.sampling.get("top_k") is not None
                else -1,
                min_p=float(req.sampling.get("min_p", 0.0))
                if req.sampling.get("min_p") is not None
                else 0.0,
                presence_penalty=float(req.sampling.get("presence_penalty", 0.0)),
                repetition_penalty=float(req.sampling.get("repetition_penalty", 1.0)),
                max_tokens=req.max_tokens,
                seed=req.seed,
            )
            messages = [{"role": "user", "content": req.prompt}]
            started = time.perf_counter()
            # reasoning_effort / enable_thinking via chat_template_kwargs:
            # https://huggingface.co/Qwen/Qwen3.8-27B
            outs = self._llm.chat(
                [messages],
                sampling_params=sp,
                chat_template_kwargs=req.chat_template_kwargs or None,
            )
            latency = time.perf_counter() - started
            out = outs[0]
            raw = out.outputs[0].text
            # Prefer vLLM reasoning field if present.
            reasoning_attr = getattr(out.outputs[0], "reasoning", None) or getattr(
                out.outputs[0], "reasoning_content", None
            )
            if reasoning_attr:
                final = raw
                reasoning = str(reasoning_attr)
                flags: list[str] = []
            else:
                final, reasoning, flags = split_reasoning(req.config_id, raw)
            prompt_tokens = len(getattr(out, "prompt_token_ids", []) or [])
            output_tokens = len(out.outputs[0].token_ids or [])
            n_reason = 0
            if reasoning:
                # Approximate if tokenizer unavailable for reasoning span alone.
                n_reason = max(1, len(reasoning.split()))
            result = GenerationResult(
                text_final=final,
                text_reasoning=reasoning,
                n_prompt_tokens=prompt_tokens,
                n_output_tokens=output_tokens,
                n_reasoning_tokens=n_reason if expects_reasoning(req.config_id) or reasoning else 0,
                finish_reason=str(out.outputs[0].finish_reason or "stop"),
                latency_s=latency,
                flags=flags,
            )
            results.append(apply_thinking_token_policy(req.config_id, result))
        return results
