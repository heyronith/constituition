"""OpenAI Batch API backend for frontier judges (gpt54). Never logs API keys."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rc.budget import BudgetExceeded, spent_api_usd
from rc.config import load_budget, load_judges, repo_root
from rc.generation import GenerationRequest, GenerationResult, apply_thinking_token_policy

# Batch pricing (half of standard GPT-5.4): USD per 1M tokens.
BATCH_INPUT_USD_PER_M = 1.25
BATCH_CACHED_INPUT_USD_PER_M = 0.125
BATCH_OUTPUT_USD_PER_M = 7.50


@dataclass
class BatchCost:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    batch_id: str | None = None
    file_ids: list[str] = field(default_factory=list)


def estimate_batch_usd(
    n_requests: int,
    *,
    est_input_tokens_per: int = 900,
    est_output_tokens_per: int = 80,
    cache_hit_frac: float = 0.85,
) -> float:
    """Conservative Batch cost estimate with prompt-cache credit on system message."""
    total_in = n_requests * est_input_tokens_per
    cached = int(total_in * cache_hit_frac)
    uncached = total_in - cached
    out = n_requests * est_output_tokens_per
    return (
        uncached / 1e6 * BATCH_INPUT_USD_PER_M
        + cached / 1e6 * BATCH_CACHED_INPUT_USD_PER_M
        + out / 1e6 * BATCH_OUTPUT_USD_PER_M
    )


def preflight_openai_batch(
    n_requests: int,
    job_id: str,
    *,
    root: Path | None = None,
) -> float:
    root = root or repo_root()
    budget = load_budget(root)
    estimate = estimate_batch_usd(n_requests)
    already = spent_api_usd(root, platform="openai")
    cap = float(budget.api_hard_cap_usd)
    if already + estimate > cap:
        raise BudgetExceeded(
            f"job {job_id} would bring OpenAI spend to "
            f"${already + estimate:.4f} > API hard cap ${cap:.2f}"
        )
    return estimate


def _usage_usd(usage: dict[str, Any]) -> tuple[int, int, int, float]:
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    uncached = max(inp - cached, 0)
    usd = (
        uncached / 1e6 * BATCH_INPUT_USD_PER_M
        + cached / 1e6 * BATCH_CACHED_INPUT_USD_PER_M
        + out / 1e6 * BATCH_OUTPUT_USD_PER_M
    )
    return inp, cached, out, usd


class OpenAIBatchBackend:
    """Submit chat-completion Batch jobs and poll until complete."""

    def __init__(
        self,
        judge_id: str,
        *,
        work_dir: Path,
        root: Path | None = None,
        poll_seconds: float = 30.0,
        job_id: str = "openai-batch",
    ) -> None:
        self.judge_id = judge_id
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.root = root or repo_root()
        self.poll_seconds = poll_seconds
        self.job_id = job_id
        self.load_s = 0.0
        self.last_cost = BatchCost()
        judge = load_judges(self.root).by_id(judge_id)
        self.api_model = judge.api_model or judge.revision
        if not self.api_model:
            raise ValueError(f"{judge_id} missing api_model/revision")
        self.max_tokens = int(judge.max_tokens)
        self.temperature = float((judge.sampling or {}).get("temperature", 0.0))
        self.reasoning_effort = (judge.chat_template_kwargs or {}).get("reasoning_effort", "none")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import OpenAI

        self._client = OpenAI(api_key=key)

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        if not requests:
            return []
        preflight_openai_batch(len(requests), self.job_id, root=self.root)
        in_path = self.work_dir / f"{self.job_id}_input.jsonl"
        with in_path.open("w", encoding="utf-8") as fh:
            for i, req in enumerate(requests):
                messages: list[dict[str, str]] = []
                if req.system_prompt:
                    messages.append({"role": "system", "content": req.system_prompt})
                messages.append({"role": "user", "content": req.prompt})
                body: dict[str, Any] = {
                    "model": self.api_model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_completion_tokens": req.max_tokens or self.max_tokens,
                    "reasoning_effort": self.reasoning_effort,
                }
                if req.json_schema is not None:
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": req.schema_name or "judge_fate_v2",
                            "strict": True,
                            "schema": req.json_schema,
                        },
                    }
                row = {
                    "custom_id": f"req-{i}",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": body,
                }
                fh.write(json.dumps(row, sort_keys=True) + "\n")

        with in_path.open("rb") as fh:
            uploaded = self._client.files.create(file=fh, purpose="batch")
        batch = self._client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"job_id": self.job_id, "judge_id": self.judge_id},
        )
        (self.work_dir / f"{self.job_id}_batch.json").write_text(
            json.dumps(
                {
                    "batch_id": batch.id,
                    "input_file_id": uploaded.id,
                    "n_requests": len(requests),
                    "status": batch.status,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        started = time.perf_counter()
        while True:
            batch = self._client.batches.retrieve(batch.id)
            status = batch.status
            counts = getattr(batch, "request_counts", None)
            if counts is not None and hasattr(counts, "model_dump"):
                counts_payload: Any = counts.model_dump()
            else:
                counts_payload = str(counts) if counts is not None else None
            (self.work_dir / f"{self.job_id}_batch.json").write_text(
                json.dumps(
                    {
                        "batch_id": batch.id,
                        "input_file_id": uploaded.id,
                        "n_requests": len(requests),
                        "status": status,
                        "request_counts": counts_payload,
                    },
                    indent=2,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            if status in {"completed", "failed", "expired", "cancelled"}:
                break
            time.sleep(self.poll_seconds)

        if status != "completed":
            raise RuntimeError(f"OpenAI batch {batch.id} ended with status={status}")

        out_file_id = batch.output_file_id
        if not out_file_id:
            raise RuntimeError(f"OpenAI batch {batch.id} completed with no output_file_id")
        content = self._client.files.content(out_file_id)
        out_path = self.work_dir / f"{self.job_id}_output.jsonl"
        raw_bytes = content.read() if hasattr(content, "read") else content
        if isinstance(raw_bytes, str):
            raw_bytes = raw_bytes.encode("utf-8")
        out_path.write_bytes(raw_bytes)

        by_id: dict[str, dict[str, Any]] = {}
        total_in = total_cached = total_out = 0
        total_usd = 0.0
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            by_id[row["custom_id"]] = row
            resp = (row.get("response") or {}).get("body") or {}
            usage = resp.get("usage") or {}
            if usage:
                inp, cached, out_t, usd = _usage_usd(usage)
                total_in += inp
                total_cached += cached
                total_out += out_t
                total_usd += usd

        elapsed = time.perf_counter() - started
        per = elapsed / max(len(requests), 1)
        results: list[GenerationResult] = []
        for i, req in enumerate(requests):
            row = by_id.get(f"req-{i}")
            if row is None:
                raise RuntimeError(f"missing batch result for req-{i}")
            resp = (row.get("response") or {}).get("body") or {}
            err = row.get("error")
            if err:
                text = json.dumps({"fate": "RETAINED", "strength": 0, "rationale": f"api_error: {err}", "situation": "none"})
                n_out = 0
                n_in = 0
                finish = "error"
            else:
                choices = resp.get("choices") or []
                msg = (choices[0].get("message") if choices else {}) or {}
                text = msg.get("content") or ""
                usage = resp.get("usage") or {}
                n_in = int(usage.get("prompt_tokens") or 0)
                n_out = int(usage.get("completion_tokens") or 0)
                finish = str((choices[0].get("finish_reason") if choices else None) or "stop")
            result = GenerationResult(
                text_final=text,
                text_reasoning=None,
                n_prompt_tokens=n_in,
                n_output_tokens=n_out,
                n_reasoning_tokens=0,
                finish_reason=finish,
                latency_s=per,
                flags=[],
            )
            results.append(apply_thinking_token_policy(req.config_id, result))

        self.last_cost = BatchCost(
            input_tokens=total_in,
            cached_input_tokens=total_cached,
            output_tokens=total_out,
            usd=total_usd,
            batch_id=batch.id,
            file_ids=[uploaded.id, out_file_id],
        )
        (self.work_dir / f"{self.job_id}_cost.json").write_text(
            json.dumps(
                {
                    "batch_id": batch.id,
                    "input_tokens": total_in,
                    "cached_input_tokens": total_cached,
                    "output_tokens": total_out,
                    "usd": total_usd,
                    "n_requests": len(requests),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return results
