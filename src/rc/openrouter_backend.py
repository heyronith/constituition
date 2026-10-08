"""OpenRouter chat backend for D48 second judges (MiMo / GLM). Never logs API keys."""

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


@dataclass
class OpenRouterCost:
    usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str | None = None
    provider: str | None = None
    generation_ids: list[str] = field(default_factory=list)


def preflight_openrouter(
    est_usd: float,
    job_id: str,
    *,
    root: Path | None = None,
) -> None:
    root = root or repo_root()
    budget = load_budget(root)
    already_or = spent_api_usd(root, platform="openrouter")
    already_all = spent_api_usd(root)  # openai + anthropic + openrouter
    or_cap = float(budget.openrouter_hard_cap_usd)
    api_cap = float(budget.api_hard_cap_usd)
    if already_or + est_usd > or_cap:
        raise BudgetExceeded(
            f"job {job_id} would bring OpenRouter spend to "
            f"${already_or + est_usd:.4f} > OpenRouter cap ${or_cap:.2f}"
        )
    if already_all + est_usd > api_cap:
        raise BudgetExceeded(
            f"job {job_id} would bring total API spend to "
            f"${already_all + est_usd:.4f} > API hard cap ${api_cap:.2f}"
        )


class OpenRouterBackend:
    """Synchronous OpenAI-compatible chat completions via OpenRouter."""

    def __init__(
        self,
        judge_id: str,
        *,
        work_dir: Path,
        root: Path | None = None,
        job_id: str = "openrouter",
        est_usd_per_request: float = 0.002,
    ) -> None:
        self.judge_id = judge_id
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.root = root or repo_root()
        self.job_id = job_id
        self.est_usd_per_request = est_usd_per_request
        self.load_s = 0.0
        self.last_cost = OpenRouterCost()
        judge = load_judges(self.root).by_id(judge_id)
        self.api_model = judge.api_model or ""
        if not self.api_model:
            raise ValueError(f"{judge_id} missing api_model")
        self.max_tokens = int(judge.max_tokens)
        self.temperature = float((judge.sampling or {}).get("temperature", 0.0))
        self.reasoning_effort = (judge.chat_template_kwargs or {}).get("reasoning_effort")
        self.provider_order = list(judge.openrouter_provider_order or [])
        self.allow_fallbacks = bool(judge.allow_fallbacks) if judge.allow_fallbacks is not None else False
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY not set")
        self._client = None  # raw httpx used in generate(); SDK optional

    def generate(self, requests: list[GenerationRequest]) -> list[GenerationResult]:
        if not requests:
            return []
        preflight_openrouter(
            self.est_usd_per_request * len(requests),
            self.job_id,
            root=self.root,
        )
        results: list[GenerationResult] = []
        total_usd = 0.0
        total_in = total_out = 0
        providers: list[str] = []
        models: list[str] = []
        gen_ids: list[str] = []
        meta_path = self.work_dir / f"{self.job_id}_generations.jsonl"
        with meta_path.open("w", encoding="utf-8") as meta_fh:
            for i, req in enumerate(requests):
                if i % 25 == 0:
                    print(
                        f"[openrouter] {self.job_id} {i}/{len(requests)} usd={total_usd:.4f}",
                        flush=True,
                    )
                messages: list[dict[str, str]] = []
                if req.system_prompt:
                    messages.append({"role": "system", "content": req.system_prompt})
                messages.append({"role": "user", "content": req.prompt})
                body: dict[str, Any] = {
                    "model": self.api_model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": req.max_tokens or self.max_tokens,
                }
                # Prefer json_object over json_schema: several OpenRouter providers
                # (notably Z.AI) drop endpoints when strict json_schema is requested.
                if req.json_schema is not None:
                    body["response_format"] = {"type": "json_object"}
                # Build full OpenRouter JSON body. Do NOT pass provider/reasoning as
                # OpenAI SDK kwargs — older SDKs reject them (seen on Modal).
                payload: dict[str, Any] = dict(body)
                if self.reasoning_effort is not None:
                    payload["reasoning"] = {"effort": self.reasoning_effort}
                if self.provider_order:
                    payload["provider"] = {
                        "order": self.provider_order,
                        "allow_fallbacks": self.allow_fallbacks,
                    }
                started = time.perf_counter()
                # Prefer raw HTTP so OpenRouter-only fields are never SDK kwargs.
                import httpx

                last_err: Exception | None = None
                raw: dict[str, Any] | None = None
                latency = 0.0
                # D63: exponential backoff on 429 / 5xx (keep Xiaomi pinned; no provider fallback).
                for attempt in range(8):
                    try:
                        http_resp = httpx.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "https://github.com/heyronith/constituition",
                                "X-Title": "reflective-corrigibility-phase4",
                            },
                            json=payload,
                            timeout=httpx.Timeout(60.0, connect=20.0),
                        )
                        latency = time.perf_counter() - started
                        code = http_resp.status_code
                        if code in {429} or code >= 500:
                            raise RuntimeError(
                                f"OpenRouter HTTP {code}: {http_resp.text[:500]}"
                            )
                        if code >= 400:
                            raise RuntimeError(
                                f"OpenRouter HTTP {code}: {http_resp.text[:500]}"
                            )
                        raw = http_resp.json()
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = exc
                        # 2^attempt seconds, capped at 120s
                        time.sleep(min(120.0, 2.0**attempt))
                if raw is None:
                    raise RuntimeError(f"OpenRouter failed after retries: {last_err}")
                choices = raw.get("choices") or []
                choice0 = choices[0] if choices else {}
                message = choice0.get("message") or {}
                text = message.get("content") or ""
                usage = raw.get("usage") or {}
                n_in = int(usage.get("prompt_tokens") or 0)
                n_out = int(usage.get("completion_tokens") or 0)
                cost = usage.get("cost")
                if cost is None:
                    # Xiaomi MiMo list price ≈ $0.435/M in + $0.87/M out
                    cost = n_in / 1e6 * 0.435 + n_out / 1e6 * 0.87
                cost_f = float(cost)
                total_usd += cost_f
                total_in += n_in
                total_out += n_out
                served_model = raw.get("model") or self.api_model
                models.append(str(served_model))
                provider = raw.get("provider") or raw.get("provider_name")
                if provider:
                    providers.append(str(provider))
                gid = raw.get("id")
                if gid:
                    gen_ids.append(str(gid))
                meta_fh.write(
                    json.dumps(
                        {
                            "i": i,
                            "id": gid,
                            "model": served_model,
                            "provider": provider,
                            "prompt_tokens": n_in,
                            "completion_tokens": n_out,
                            "cost_usd": cost_f,
                            "finish_reason": choice0.get("finish_reason"),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                meta_fh.flush()
                result = GenerationResult(
                    text_final=text,
                    text_reasoning=None,
                    n_prompt_tokens=n_in,
                    n_output_tokens=n_out,
                    n_reasoning_tokens=0,
                    finish_reason=str(choice0.get("finish_reason") or "stop"),
                    latency_s=latency,
                    flags=[],
                )
                results.append(apply_thinking_token_policy(req.config_id, result))

        self.last_cost = OpenRouterCost(
            usd=total_usd,
            prompt_tokens=total_in,
            completion_tokens=total_out,
            model=models[0] if models else self.api_model,
            provider=providers[0] if providers else (
                self.provider_order[0] if self.provider_order else None
            ),
            generation_ids=gen_ids,
        )
        (self.work_dir / f"{self.job_id}_cost.json").write_text(
            json.dumps(
                {
                    "usd": total_usd,
                    "prompt_tokens": total_in,
                    "completion_tokens": total_out,
                    "n_requests": len(requests),
                    "model": self.last_cost.model,
                    "provider": self.last_cost.provider,
                    "served_models": sorted(set(models)),
                    "served_providers": sorted(set(providers)),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return results
