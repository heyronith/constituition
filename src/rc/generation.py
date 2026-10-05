"""Platform-agnostic generation core. Tests use MockBackend only."""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from rc.config import load_models, load_smoke, load_vllm, repo_root

SCHEMA_NAMES = (
    "permissive_structured",
    "forced",
    "forced_paraphrase",
    "endorsement",
    "realism",
    "eval_awareness",
    "calib_generator",
    "calib_verifier",
)

# D30: these schemas get per-request opaque-ID enums.
ID_ENUM_SCHEMAS = frozenset({"permissive_structured", "forced", "endorsement"})

# Qwen thinking delimiters (HF chat template / vLLM reasoning parser).
_QWEN_THINK_CLOSE = "</think>"
# Gemma 4 thought channel (model card): <|channel>thought\n ... <channel|>
_GEMMA_THOUGHT_RE = re.compile(
    r"<\|channel\|>thought\n(?P<thought>.*?)<channel\|>",
    re.DOTALL,
)
_GRAPH_CAPTURE_RE = re.compile(r"Graph capturing finished in (\d+(?:\.\d+)?) secs")


@dataclass
class GenerationRequest:
    prompt: str
    config_id: str
    sampling: dict[str, Any]
    chat_template_kwargs: dict[str, Any]
    max_tokens: int
    seed: int
    json_schema: dict[str, Any] | None = None
    schema_name: str | None = None


def schemas_root(root: Path | None = None) -> Path:
    return (root or repo_root()) / "materials" / "schemas"


def load_json_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    """Load a frozen JSON Schema by stem name (no .json)."""
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown schema {name}; known={SCHEMA_NAMES}")
    path = schemas_root(root) / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def instantiate_schema(
    name: str,
    opaque_ids: list[str] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Deep-copy a base schema; for ID tasks, bind id/merge_with enums (D30)."""
    schema = copy.deepcopy(load_json_schema(name, root))
    if name not in ID_ENUM_SCHEMAS:
        return schema
    if not opaque_ids:
        raise ValueError(f"schema {name} requires non-empty opaque_ids")
    ids = list(opaque_ids)
    id_schema: dict[str, Any] = {"type": "string", "enum": ids}
    # null allowed for optional merge_with.
    merge_schema: dict[str, Any] = {"enum": [None, *ids]}
    if name == "permissive_structured":
        principles = schema["properties"]["principles"]
        principles["minItems"] = len(ids)
        principles["maxItems"] = len(ids)
        item_props = principles["items"]["properties"]
        item_props["id"] = id_schema
        item_props["merge_with"] = merge_schema
    elif name == "forced":
        change_props = schema["properties"]["change"]["properties"]
        change_props["id"] = id_schema
        change_props["merge_with"] = merge_schema
    elif name == "endorsement":
        ratings = schema["properties"]["ratings"]
        ratings["minItems"] = len(ids)
        ratings["maxItems"] = len(ids)
        ratings["items"]["properties"]["id"] = id_schema
    return schema


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
    for section in ("subjects", "smoke_models", "judges"):
        for row in lock.get(section) or []:
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
    # D13/D24: Gemma 31B needs headroom for CUDA-graph capture on A100-80GB.
    # With enforce_eager=False, 16384 exceeds available KV; 12288 fits.
    if config_id == "gemma4_31b":
        return 12288
    # D31: OLMo on Modal L40S uses the default max_model_len (16384), same as
    # other non-think configs. D25's Colab L4 8192 limit is superseded.
    return vllm.default_max_model_len


def expects_reasoning(config_id: str) -> bool:
    return config_id == "qwen38_27b_think"


def count_tokens(text: str | None, tokenizer: Any | None = None) -> int:
    """Count tokens with the model tokenizer when available."""
    if not text:
        return 0
    if tokenizer is not None:
        encoded = tokenizer.encode(text, add_special_tokens=False)
        return len(encoded)
    # MockBackend / tests: whitespace tokens are not used on GPU.
    return len(text.split())


def build_request(
    prompt: str,
    config_id: str,
    seed: int,
    *,
    root: Path | None = None,
    schema_name: str | None = None,
    opaque_ids: list[str] | None = None,
) -> GenerationRequest:
    try:
        subject = load_models(root).by_id(config_id)
        sampling = dict(subject.sampling) if isinstance(subject.sampling, dict) else {}
        kwargs = dict(subject.chat_template_kwargs)
    except KeyError:
        smoke = load_smoke(root)
        if smoke.config_id != config_id:
            raise
        sampling = dict(smoke.sampling)
        kwargs = dict(smoke.chat_template_kwargs)
    if "reasoning_effort" in sampling:
        kwargs["reasoning_effort"] = sampling.pop("reasoning_effort")
    # vLLM SamplingParams.seed must fit a signed 32-bit C long on Linux.
    safe_seed = int(seed) & 0x7FFFFFFF
    schema = None
    if schema_name:
        schema = instantiate_schema(schema_name, opaque_ids, root=root)
    return GenerationRequest(
        prompt=prompt,
        config_id=config_id,
        sampling=sampling,
        chat_template_kwargs=kwargs,
        max_tokens=max_tokens_for(config_id, root),
        seed=safe_seed,
        json_schema=schema,
        schema_name=schema_name,
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


def apply_thinking_token_policy(config_id: str, result: GenerationResult) -> GenerationResult:
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
        self.load_s = 0.0
        self.graph_capture_s = 0.0

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        self.calls.append(requests)
        results: list[GenerationResult] = []
        for req in requests:
            if not self.outputs:
                raise RuntimeError("MockBackend exhausted scripted outputs")
            raw = self.outputs.pop(0)
            final, reasoning, flags = split_reasoning(req.config_id, raw)
            n_reason = count_tokens(reasoning)
            result = GenerationResult(
                text_final=final,
                text_reasoning=reasoning,
                n_prompt_tokens=count_tokens(req.prompt),
                n_output_tokens=count_tokens(raw),
                n_reasoning_tokens=n_reason,
                finish_reason="stop",
                latency_s=0.001,
                flags=flags,
            )
            results.append(apply_thinking_token_policy(req.config_id, result))
        return results


class _GraphCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.seconds = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        match = _GRAPH_CAPTURE_RE.search(record.getMessage())
        if match:
            self.seconds = float(match.group(1))


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
        enforce_eager: bool = False,
        max_num_seqs: int | None = None,
        root: Path | None = None,
    ) -> None:
        from vllm import LLM

        vllm_cfg = load_vllm(root)
        self.config_id = config_id
        self.load_s = 0.0
        self.graph_capture_s = 0.0
        handler = _GraphCaptureHandler()
        logging.getLogger().addHandler(handler)
        started = time.perf_counter()
        llm_kwargs: dict[str, Any] = {
            "model": model_path,
            "revision": revision,
            "dtype": "bfloat16",
            "max_model_len": max_model_len or max_model_len_for(config_id, root),
            "gpu_memory_utilization": (
                gpu_memory_utilization
                if gpu_memory_utilization is not None
                else vllm_cfg.gpu_memory_utilization
            ),
            "trust_remote_code": True,
            "enforce_eager": enforce_eager,
            "max_num_seqs": max_num_seqs if max_num_seqs is not None else vllm_cfg.max_num_seqs,
        }
        # D26: for thinking subjects, use the Qwen reasoning parser so structured
        # outputs constrain only the final answer after reasoning.
        if expects_reasoning(config_id):
            llm_kwargs["reasoning_parser"] = "qwen3"
        self._llm = LLM(**llm_kwargs)
        total = time.perf_counter() - started
        logging.getLogger().removeHandler(handler)
        self.graph_capture_s = handler.seconds if not enforce_eager else 0.0
        self.load_s = max(0.0, total - self.graph_capture_s)
        self._tokenizer = self._llm.get_tokenizer()

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        from vllm import SamplingParams

        if not requests:
            return []

        # Group by identical chat_template_kwargs; preserve original order in results.
        groups: dict[str, list[int]] = {}
        for i, req in enumerate(requests):
            key = repr(sorted((req.chat_template_kwargs or {}).items()))
            groups.setdefault(key, []).append(i)

        slots: list[GenerationResult | None] = [None] * len(requests)
        for idxs in groups.values():
            chunk = [requests[i] for i in idxs]
            chunk_results = self._generate_group(chunk, SamplingParams)
            for i, result in zip(idxs, chunk_results, strict=True):
                slots[i] = result
        return [r for r in slots if r is not None]

    def _generate_group(self, requests: list[GenerationRequest], sampling_cls: Any) -> list:
        from vllm.sampling_params import StructuredOutputsParams

        conversations = [[{"role": "user", "content": req.prompt}] for req in requests]
        sampling_params = []
        for req in requests:
            so = None
            if req.json_schema is not None:
                so = StructuredOutputsParams(json=req.json_schema)
            sampling_params.append(
                sampling_cls(
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
                    structured_outputs=so,
                )
            )
        # reasoning_effort / enable_thinking via chat_template_kwargs:
        # https://huggingface.co/Qwen/Qwen3.8-27B
        kwargs0 = requests[0].chat_template_kwargs or None
        started = time.perf_counter()
        outs = self._llm.chat(
            conversations,
            sampling_params=sampling_params,
            chat_template_kwargs=kwargs0,
        )
        per = (time.perf_counter() - started) / max(len(outs), 1)
        results: list[GenerationResult] = []
        for req, out in zip(requests, outs, strict=True):
            raw = out.outputs[0].text
            reasoning_attr = getattr(out.outputs[0], "reasoning", None) or getattr(
                out.outputs[0], "reasoning_content", None
            )
            n_reason_vllm = getattr(out.outputs[0], "num_reasoning_tokens", None)
            if reasoning_attr:
                final = raw
                reasoning = str(reasoning_attr)
                flags: list[str] = []
            else:
                final, reasoning, flags = split_reasoning(req.config_id, raw)
            prompt_tokens = len(getattr(out, "prompt_token_ids", []) or [])
            output_tokens = len(out.outputs[0].token_ids or [])
            if n_reason_vllm is not None:
                n_reason = int(n_reason_vllm)
            else:
                n_reason = count_tokens(reasoning, self._tokenizer)
            if not (expects_reasoning(req.config_id) or reasoning):
                n_reason = 0
            result = GenerationResult(
                text_final=final,
                text_reasoning=reasoning,
                n_prompt_tokens=prompt_tokens,
                n_output_tokens=output_tokens,
                n_reasoning_tokens=n_reason,
                finish_reason=str(out.outputs[0].finish_reason or "stop"),
                latency_s=per,
                flags=flags,
            )
            results.append(apply_thinking_token_policy(req.config_id, result))
        return results
