"""STATUS.json helpers for Phase 7 (operational metrics only; D55 blinding)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["last_update_utc"] = utc_now()
    # Hard guard: never write hypothesis-relevant keys.
    banned_exact = {
        "erosion",
        "hazard",
        "cor_rate",
        "agent_rate",
        "hr",
        "category_fate",
        "hypothesis",
        "aar",
        "urr",
    }
    banned_substr = ("erosion_", "hazard_", "fate_by_", "cor_vs_", "agent_vs_")
    for k in list(body):
        lk = str(k).lower()
        if lk in banned_exact or any(b in lk for b in banned_substr):
            raise ValueError(f"STATUS key {k!r} violates analysis blinding (D55)")
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_status(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_status(payload: dict[str, Any]) -> str:
    lines = [
        f"stage={payload.get('stage')} state={payload.get('state')}",
        f"run_tag={payload.get('run_tag')} config={payload.get('config_id')}",
        f"rounds_completed={payload.get('rounds_completed')} / {payload.get('rounds_total')}",
        f"parse_failures={payload.get('parse_failures')} resamples={payload.get('resamples')}",
        f"censored_chains={payload.get('censored_chains')}",
        f"elapsed_gpu_s={payload.get('elapsed_gpu_seconds')}",
        f"usd_so_far={payload.get('usd_so_far')} usd_projected_total={payload.get('usd_projected_total')}",
        f"batch_ids={payload.get('batch_ids')}",
        f"last_update_utc={payload.get('last_update_utc')}",
    ]
    return "\n".join(lines)
