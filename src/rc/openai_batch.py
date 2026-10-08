"""OpenAI Batch API backend for frontier judges (gpt54). Never logs API keys.

D60: when a Batch stalls (≥95% done with no progress for ``stall_progress_s``, or
still open after ``stall_wall_s``), cancel it, keep completed outputs, and finish
remaining requests via synchronous Chat Completions with byte-identical bodies.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from rc.budget import BudgetExceeded, record_actual, spent_api_usd
from rc.config import load_budget, load_judges, repo_root
from rc.generation import GenerationRequest, GenerationResult, apply_thinking_token_policy

# Batch pricing (half of standard GPT-5.4): USD per 1M tokens.
BATCH_INPUT_USD_PER_M = 1.25
BATCH_CACHED_INPUT_USD_PER_M = 0.125
BATCH_OUTPUT_USD_PER_M = 7.50
# Standard (sync) GPT-5.4 prices = 2× batch.
SYNC_INPUT_USD_PER_M = 2.50
SYNC_CACHED_INPUT_USD_PER_M = 0.25
SYNC_OUTPUT_USD_PER_M = 15.00

DEFAULT_STALL_FRAC = 0.95
DEFAULT_STALL_PROGRESS_S = 3600.0
DEFAULT_STALL_WALL_S = 8 * 3600.0
SYNC_MAX_RETRIES = 5


@dataclass
class BatchCost:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    batch_id: str | None = None
    file_ids: list[str] = field(default_factory=list)
    n_batch: int = 0
    n_sync: int = 0
    batch_usd: float = 0.0
    sync_usd: float = 0.0


class OpenAIClientProto(Protocol):
    """Minimal surface used by OpenAIBatchBackend (real client or test double)."""

    @property
    def files(self) -> Any: ...

    @property
    def batches(self) -> Any: ...

    @property
    def chat(self) -> Any: ...


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


def request_body_sha256(body: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _usage_usd(
    usage: dict[str, Any], *, sync: bool = False
) -> tuple[int, int, int, float]:
    inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    uncached = max(inp - cached, 0)
    if sync:
        usd = (
            uncached / 1e6 * SYNC_INPUT_USD_PER_M
            + cached / 1e6 * SYNC_CACHED_INPUT_USD_PER_M
            + out / 1e6 * SYNC_OUTPUT_USD_PER_M
        )
    else:
        usd = (
            uncached / 1e6 * BATCH_INPUT_USD_PER_M
            + cached / 1e6 * BATCH_CACHED_INPUT_USD_PER_M
            + out / 1e6 * BATCH_OUTPUT_USD_PER_M
        )
    return inp, cached, out, usd


def build_chat_body(
    req: GenerationRequest,
    *,
    api_model: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    messages.append({"role": "user", "content": req.prompt})
    body: dict[str, Any] = {
        "model": api_model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": req.max_tokens or max_tokens,
        "reasoning_effort": reasoning_effort,
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
    return body


def _row_to_result(
    row: dict[str, Any] | None,
    *,
    req: GenerationRequest,
    latency_s: float,
    submit_mode: str,
    body_sha: str,
) -> GenerationResult:
    if row is None:
        text = json.dumps(
            {
                "fate": "RETAINED",
                "strength": 0,
                "rationale": "missing_batch_row",
                "situation": "none",
            }
        )
        result = GenerationResult(
            text_final=text,
            text_reasoning=None,
            n_prompt_tokens=0,
            n_output_tokens=0,
            n_reasoning_tokens=0,
            finish_reason="error",
            latency_s=latency_s,
            flags=["missing_batch_row"],
            submit_mode=submit_mode,
            request_body_sha256=body_sha,
        )
        return apply_thinking_token_policy(req.config_id, result)

    resp = (row.get("response") or {}).get("body") or {}
    err = row.get("error")
    if err:
        text = json.dumps(
            {
                "fate": "RETAINED",
                "strength": 0,
                "rationale": f"api_error: {err}",
                "situation": "none",
            }
        )
        n_out = n_in = 0
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
        latency_s=latency_s,
        flags=[],
        submit_mode=submit_mode,
        request_body_sha256=body_sha,
    )
    return apply_thinking_token_policy(req.config_id, result)


class OpenAIBatchBackend:
    """Submit chat-completion Batch jobs; D60 sync-straggler fallback."""

    def __init__(
        self,
        judge_id: str,
        *,
        work_dir: Path,
        root: Path | None = None,
        poll_seconds: float = 30.0,
        job_id: str = "openai-batch",
        client: Any | None = None,
        stall_frac: float = DEFAULT_STALL_FRAC,
        stall_progress_s: float = DEFAULT_STALL_PROGRESS_S,
        stall_wall_s: float = DEFAULT_STALL_WALL_S,
        time_fn: Any | None = None,
        sleep_fn: Any | None = None,
        skip_preflight: bool = False,
        resume_batch_id: str | None = None,
    ) -> None:
        self.judge_id = judge_id
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.root = root or repo_root()
        self.poll_seconds = poll_seconds
        self.job_id = job_id
        self.load_s = 0.0
        self.last_cost = BatchCost()
        self.stall_frac = stall_frac
        self.stall_progress_s = stall_progress_s
        self.stall_wall_s = stall_wall_s
        self._time = time_fn or time.time
        self._sleep = sleep_fn or time.sleep
        self.skip_preflight = skip_preflight
        self.resume_batch_id = resume_batch_id
        self._created_new_batch = False
        judge = load_judges(self.root).by_id(judge_id)
        self.api_model = judge.api_model or judge.revision
        if not self.api_model:
            raise ValueError(f"{judge_id} missing api_model/revision")
        self.max_tokens = int(judge.max_tokens)
        self.temperature = float((judge.sampling or {}).get("temperature", 0.0))
        self.reasoning_effort = (judge.chat_template_kwargs or {}).get("reasoning_effort", "none")
        if client is not None:
            self._client = client
        else:
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY not set")
            from openai import OpenAI

            self._client = OpenAI(api_key=key)

    def _batch_meta_path(self) -> Path:
        return self.work_dir / f"{self.job_id}_batch.json"

    def _input_path(self) -> Path:
        return self.work_dir / f"{self.job_id}_input.jsonl"

    def _write_batch_meta(self, payload: dict[str, Any]) -> None:
        self._batch_meta_path().write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

    def _build_input_rows(
        self, requests: list[GenerationRequest]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        body_shas: list[str] = []
        for i, req in enumerate(requests):
            body = build_chat_body(
                req,
                api_model=self.api_model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )
            sha = request_body_sha256(body)
            body_shas.append(sha)
            rows.append(
                {
                    "custom_id": f"req-{i}",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": body,
                }
            )
        return rows, body_shas

    def _download_file(self, file_id: str | None, dest: Path) -> bool:
        if not file_id:
            return False
        content = self._client.files.content(file_id)
        raw_bytes = content.read() if hasattr(content, "read") else content
        if isinstance(raw_bytes, str):
            raw_bytes = raw_bytes.encode("utf-8")
        dest.write_bytes(raw_bytes)
        return True

    def _parse_output_jsonl(self, path: Path) -> dict[str, dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        if not path.exists():
            return by_id
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cid = row.get("custom_id")
            if cid:
                by_id[str(cid)] = row
        return by_id

    def _should_stall(
        self,
        *,
        status: str,
        completed: int,
        total: int,
        submitted_at: float,
        last_progress_at: float,
        now: float,
    ) -> bool:
        if status in {"completed", "failed", "expired", "cancelled"}:
            return False
        if total <= 0:
            return False
        frac = completed / total
        if frac >= self.stall_frac and (now - last_progress_at) >= self.stall_progress_s:
            return True
        if (now - submitted_at) >= self.stall_wall_s:
            return True
        return False

    def _sync_one(self, body: dict[str, Any]) -> dict[str, Any]:
        """Synchronous chat.completions.create; returns a batch-shaped result row."""
        last_err: Exception | None = None
        delay = 1.0
        for attempt in range(SYNC_MAX_RETRIES):
            try:
                resp = self._client.chat.completions.create(**body)
                # Normalize to batch output shape.
                if hasattr(resp, "model_dump"):
                    body_out = resp.model_dump()
                elif isinstance(resp, dict):
                    body_out = resp
                else:
                    body_out = json.loads(resp.model_dump_json())
                return {"response": {"status_code": 200, "body": body_out}, "error": None}
            except Exception as exc:  # noqa: BLE001 — retryable API errors
                last_err = exc
                if attempt + 1 >= SYNC_MAX_RETRIES:
                    break
                self._sleep(delay)
                delay = min(delay * 2, 60.0)
        return {
            "response": {"status_code": 0, "body": {}},
            "error": {"message": str(last_err) if last_err else "sync_failed"},
        }

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        if not requests:
            return []
        if not self.skip_preflight:
            preflight_openai_batch(len(requests), self.job_id, root=self.root)

        input_rows, body_shas = self._build_input_rows(requests)
        in_path = self._input_path()
        with in_path.open("w", encoding="utf-8") as fh:
            for row in input_rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

        meta_path = self._batch_meta_path()
        batch_id: str | None = None
        uploaded_id: str | None = None
        if meta_path.exists():
            try:
                prev = json.loads(meta_path.read_text(encoding="utf-8"))
                batch_id = prev.get("batch_id")
                uploaded_id = prev.get("input_file_id")
            except (json.JSONDecodeError, TypeError, ValueError):
                batch_id = None
        if not batch_id and self.resume_batch_id:
            batch_id = self.resume_batch_id

        # D60 resume: if a prior merged output already covers every request, reuse it
        # without creating or re-submitting a Batch.
        merged_path = self.work_dir / f"{self.job_id}_merged_output.jsonl"
        if merged_path.exists() and batch_id:
            by_id_prev = self._parse_output_jsonl(merged_path)
            if all(f"req-{i}" in by_id_prev for i in range(len(requests))):
                elapsed = 1e-6
                per = elapsed / max(len(requests), 1)
                results = [
                    _row_to_result(
                        by_id_prev[f"req-{i}"],
                        req=req,
                        latency_s=per,
                        submit_mode=str(
                            by_id_prev[f"req-{i}"].get("_submit_mode")
                            or ("sync" if by_id_prev[f"req-{i}"].get("_sync") else "batch")
                        ),
                        body_sha=body_shas[i],
                    )
                    for i, req in enumerate(requests)
                ]
                self.last_cost = BatchCost(
                    batch_id=batch_id,
                    n_batch=sum(
                        1
                        for i in range(len(requests))
                        if (by_id_prev[f"req-{i}"].get("_submit_mode") or "batch") == "batch"
                    ),
                    n_sync=sum(
                        1
                        for i in range(len(requests))
                        if (by_id_prev[f"req-{i}"].get("_submit_mode") or "batch") == "sync"
                    ),
                )
                return results

        if batch_id:
            batch = self._client.batches.retrieve(batch_id)
            self._created_new_batch = False
        else:
            with in_path.open("rb") as fh:
                uploaded = self._client.files.create(file=fh, purpose="batch")
            uploaded_id = uploaded.id
            batch = self._client.batches.create(
                input_file_id=uploaded.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"job_id": self.job_id, "judge_id": self.judge_id},
            )
            batch_id = batch.id
            self._created_new_batch = True
            self._write_batch_meta(
                {
                    "batch_id": batch.id,
                    "input_file_id": uploaded.id,
                    "n_requests": len(requests),
                    "status": batch.status,
                    "submitted_at_unix": self._time(),
                }
            )

        # Preserve submitted_at across polls.
        submitted_at = self._time()
        if meta_path.exists():
            try:
                submitted_at = float(
                    json.loads(meta_path.read_text(encoding="utf-8")).get(
                        "submitted_at_unix", submitted_at
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        started = self._time()
        last_completed = -1
        last_progress_at = started
        stalled = False
        while True:
            batch = self._client.batches.retrieve(batch_id)
            status = batch.status
            counts = getattr(batch, "request_counts", None)
            completed = int(getattr(counts, "completed", 0) or 0) if counts else 0
            total = int(getattr(counts, "total", len(requests)) or len(requests)) if counts else len(requests)
            if counts is not None and hasattr(counts, "model_dump"):
                counts_payload: Any = counts.model_dump()
            else:
                counts_payload = str(counts) if counts is not None else None
            now = self._time()
            if completed != last_completed:
                last_completed = completed
                last_progress_at = now
            self._write_batch_meta(
                {
                    "batch_id": batch_id,
                    "input_file_id": uploaded_id,
                    "n_requests": len(requests),
                    "status": status,
                    "request_counts": counts_payload,
                    "submitted_at_unix": submitted_at,
                    "last_progress_at_unix": last_progress_at,
                }
            )
            if status in {"completed", "failed", "expired", "cancelled", "cancelling"}:
                # Wait out cancelling → cancelled and for output_file_id to appear.
                if status in {"cancelled", "cancelling"}:
                    # OpenAI can take a long time to finalize cancel + expose output.
                    for _ in range(360):
                        batch = self._client.batches.retrieve(batch_id)
                        status = batch.status
                        if status == "cancelled" and getattr(batch, "output_file_id", None):
                            break
                        if status in {"completed", "failed", "expired"}:
                            break
                        self._sleep(max(self.poll_seconds, 15.0))
                break
            if self._should_stall(
                status=status,
                completed=completed,
                total=total,
                submitted_at=submitted_at,
                last_progress_at=last_progress_at,
                now=now,
            ):
                stalled = True
                try:
                    batch = self._client.batches.cancel(batch_id)
                except Exception:
                    batch = self._client.batches.retrieve(batch_id)
                # Wait for terminal cancel.
                for _ in range(120):
                    batch = self._client.batches.retrieve(batch_id)
                    if batch.status in {"cancelled", "completed", "failed", "expired"}:
                        break
                    self._sleep(min(self.poll_seconds, 5.0))
                status = batch.status
                self._write_batch_meta(
                    {
                        "batch_id": batch_id,
                        "input_file_id": uploaded_id,
                        "n_requests": len(requests),
                        "status": status,
                        "stalled": True,
                        "stall_reason": "d60_straggler",
                        "submitted_at_unix": submitted_at,
                    }
                )
                break
            self._sleep(self.poll_seconds)

        out_path = self.work_dir / f"{self.job_id}_output.jsonl"
        err_path = self.work_dir / f"{self.job_id}_errors.jsonl"
        out_file_id = getattr(batch, "output_file_id", None)
        err_file_id = getattr(batch, "error_file_id", None)
        self._download_file(out_file_id, out_path)
        self._download_file(err_file_id, err_path)
        by_id = self._parse_output_jsonl(out_path)
        # Merge error-file rows that lack a successful response.
        for cid, row in self._parse_output_jsonl(err_path).items():
            if cid not in by_id:
                by_id[cid] = row

        if status == "failed" and not by_id and not stalled:
            raise RuntimeError(f"OpenAI batch {batch_id} ended with status={status}")

        # Sync stragglers for missing custom_ids (D60).
        missing = [i for i in range(len(requests)) if f"req-{i}" not in by_id]
        sync_usd = 0.0
        sync_in = sync_cached = sync_out = 0
        for i in missing:
            body = input_rows[i]["body"]
            sync_row = self._sync_one(body)
            sync_row["custom_id"] = f"req-{i}"
            sync_row["_submit_mode"] = "sync"
            sync_row["_sync"] = True
            by_id[f"req-{i}"] = sync_row
            usage = ((sync_row.get("response") or {}).get("body") or {}).get("usage") or {}
            if usage:
                inp, cached, out_t, usd = _usage_usd(usage, sync=True)
                sync_in += inp
                sync_cached += cached
                sync_out += out_t
                sync_usd += usd

        for i in range(len(requests)):
            if i not in missing:
                by_id[f"req-{i}"]["_submit_mode"] = "batch"

        # Persist merged output (batch + sync) for resume audits.
        with merged_path.open("w", encoding="utf-8") as fh:
            for i in range(len(requests)):
                fh.write(json.dumps(by_id[f"req-{i}"], sort_keys=True) + "\n")

        batch_usd = 0.0
        batch_in = batch_cached = batch_out = 0
        n_batch = 0
        for i in range(len(requests)):
            if i in missing:
                continue
            row = by_id[f"req-{i}"]
            resp = (row.get("response") or {}).get("body") or {}
            usage = resp.get("usage") or {}
            if usage:
                inp, cached, out_t, usd = _usage_usd(usage, sync=False)
                batch_in += inp
                batch_cached += cached
                batch_out += out_t
                batch_usd += usd
                n_batch += 1

        elapsed = max(self._time() - started, 1e-6)
        per = elapsed / max(len(requests), 1)
        results: list[GenerationResult] = []
        for i, req in enumerate(requests):
            mode = "sync" if i in missing else "batch"
            results.append(
                _row_to_result(
                    by_id.get(f"req-{i}"),
                    req=req,
                    latency_s=per,
                    submit_mode=mode,
                    body_sha=body_shas[i],
                )
            )

        total_usd = batch_usd + sync_usd
        self.last_cost = BatchCost(
            input_tokens=batch_in + sync_in,
            cached_input_tokens=batch_cached + sync_cached,
            output_tokens=batch_out + sync_out,
            usd=total_usd,
            batch_id=batch_id,
            file_ids=[x for x in [uploaded_id, out_file_id, err_file_id] if x],
            n_batch=n_batch,
            n_sync=len(missing),
            batch_usd=batch_usd,
            sync_usd=sync_usd,
        )
        cost_payload = {
            "batch_id": batch_id,
            "input_tokens": batch_in + sync_in,
            "cached_input_tokens": batch_cached + sync_cached,
            "output_tokens": batch_out + sync_out,
            "usd": total_usd,
            "batch_usd": batch_usd,
            "sync_usd": sync_usd,
            "n_requests": len(requests),
            "n_batch": n_batch,
            "n_sync": len(missing),
            "stalled": stalled,
            "status": status,
        }
        (self.work_dir / f"{self.job_id}_cost.json").write_text(
            json.dumps(cost_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if batch_usd > 0:
            record_actual(
                job_id=self.job_id,
                phase="7",
                platform="openai",
                gpu="none",
                max_seconds=0,
                actual_seconds=0,
                actual_usd=batch_usd,
                note=f"batch_prices batch_id={batch_id} n={n_batch}",
                root=self.root,
            )
        if sync_usd > 0 or missing:
            record_actual(
                job_id=self.job_id,
                phase="7",
                platform="openai",
                gpu="none",
                max_seconds=0,
                actual_seconds=0,
                actual_usd=sync_usd,
                note=f"sync_straggler batch_id={batch_id} n={len(missing)}",
                root=self.root,
            )
        return results
