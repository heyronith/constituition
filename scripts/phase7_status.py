#!/usr/bin/env python3
"""One-shot Phase 7 STATUS aggregator (no loop). D55/D63."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CONFIGS = [
    "olmo3_7b_final",
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
]


def _get_volume_json(remote: str) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "status.json"
        proc = subprocess.run(
            ["modal", "volume", "get", "rc-runs", remote, str(dest), "--force"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dest.exists():
            return None
        return json.loads(dest.read_text(encoding="utf-8"))


def _is_stale(payload: dict) -> bool:
    from rc.phase7b import is_stale_status

    return is_stale_status(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tag", default="main_v1")
    parser.add_argument(
        "--local",
        type=Path,
        default=None,
        help="Local runs/<run_tag> directory instead of Modal volume",
    )
    args = parser.parse_args()

    rows = []
    for config_id in CONFIGS:
        if args.local is not None:
            # Prefer per-config STATUS; fall back to shared STATUS.json for canary.
            p1 = args.local / f"STATUS_{config_id}.json"
            p0 = args.local / "STATUS.json"
            path = p1 if p1.exists() else (p0 if config_id == "olmo3_7b_final" and p0.exists() else None)
            payload = json.loads(path.read_text(encoding="utf-8")) if path else None
        else:
            payload = _get_volume_json(f"{args.run_tag}/STATUS_{config_id}.json")
            if payload is None and config_id == "olmo3_7b_final":
                payload = _get_volume_json(f"{args.run_tag}/STATUS.json")
        if payload is None:
            rows.append(
                {
                    "config_id": config_id,
                    "stage": None,
                    "state": "missing",
                    "stale": True,
                }
            )
            continue
        stale = _is_stale(payload)
        rows.append(
            {
                "config_id": config_id,
                "stage": payload.get("stage"),
                "state": ("STALE" if stale else payload.get("state")),
                "rounds_completed": payload.get("rounds_completed"),
                "rounds_total": payload.get("rounds_total"),
                "parse_failures": payload.get("parse_failures"),
                "censored_chains": payload.get("censored_chains"),
                "usd_so_far": payload.get("usd_so_far"),
                "batch_ids": payload.get("batch_ids"),
                "batch_state": payload.get("batch_state") or payload.get("batch_status"),
                "last_update_utc": payload.get("last_update_utc"),
                "stale": stale,
            }
        )

    print(json.dumps({"run_tag": args.run_tag, "configs": rows}, indent=2, sort_keys=True))
    print()
    hdr = f"{'config':<22} {'stage':<12} {'state':<16} {'rounds':<10} {'usd':>8} {'batch':<12} {'updated'}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        rounds = f"{r.get('rounds_completed')}/{r.get('rounds_total')}"
        usd = r.get("usd_so_far")
        usd_s = f"{usd:.3f}" if isinstance(usd, (int, float)) else "-"
        batch = "-"
        bids = r.get("batch_ids") or {}
        if isinstance(bids, dict) and bids.get("gpt54"):
            batch = str(bids["gpt54"])[:10]
        elif r.get("batch_state"):
            batch = str(r["batch_state"])[:12]
        print(
            f"{r['config_id']:<22} {str(r.get('stage') or '-'):<12} "
            f"{str(r.get('state') or '-'):<16} {rounds:<10} {usd_s:>8} {batch:<12} "
            f"{r.get('last_update_utc') or '-'}"
        )


if __name__ == "__main__":
    main()
