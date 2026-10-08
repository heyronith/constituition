"""Probe OpenAI organization costs via Modal openai-key secret (D70)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import modal

app = modal.App("rc-s4-openai-costs")
image = modal.Image.debian_slim(python_version="3.11").pip_install("httpx")
secret = modal.Secret.from_name("openai-key")


@app.function(image=image, secrets=[secret], timeout=120)
def fetch_costs() -> dict:
    import os

    import httpx

    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    key_names = sorted(k for k in os.environ if "OPENAI" in k.upper())
    if not key:
        for k in key_names:
            if "KEY" in k.upper() or "TOKEN" in k.upper():
                key = os.environ[k]
                break
    headers = {"Authorization": f"Bearer {key}"}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    out: dict = {"has_key": bool(key), "key_env_names": key_names}
    r = httpx.get(
        "https://api.openai.com/v1/organization/costs",
        headers={**headers, "Content-Type": "application/json"},
        params={
            "start_time": int(start.timestamp()),
            "limit": 180,
            "bucket_width": "1d",
        },
        timeout=60,
    )
    out["costs_status"] = r.status_code
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": r.text[:4000]}
    out["costs"] = payload
    # Sum amount values if present
    total = 0.0
    buckets = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for b in data:
            amt = 0.0
            for res in b.get("results") or []:
                # amount object: {"value": ..., "currency": "usd"}
                a = res.get("amount") or {}
                if isinstance(a, dict) and a.get("value") is not None:
                    amt += float(a["value"])
                elif res.get("amount_value") is not None:
                    amt += float(res["amount_value"])
            total += amt
            buckets.append({"start_time": b.get("start_time"), "amount_usd": amt})
    out["total_usd"] = total
    out["n_buckets"] = len(buckets)
    out["buckets_tail"] = buckets[-14:]
    return out


@app.local_entrypoint()
def main() -> None:
    result = fetch_costs.remote()
    Path("results/phase7b_s4_openai_costs_probe.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "has_key": result.get("has_key"),
                "costs_status": result.get("costs_status"),
                "total_usd": result.get("total_usd"),
                "n_buckets": result.get("n_buckets"),
                "buckets_tail": result.get("buckets_tail"),
                "error": (result.get("costs") or {}).get("error")
                if isinstance(result.get("costs"), dict)
                else None,
            },
            indent=2,
        )
    )
