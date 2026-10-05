"""Pilot helpers: stratified eval-awareness sampling and descriptive gates."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import load_experiment, repo_root


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sample_eval_awareness_records(
    run_tag: str,
    config_id: str,
    *,
    root: Path | None = None,
    fraction: float = 0.10,
) -> list[dict[str, Any]]:
    """Stratified 10% of successful (unit, round) records, balanced on protocol×condition."""
    if fraction <= 0:
        return []
    root = root or repo_root()
    exp = load_experiment(root)
    base = root / "runs" / run_tag / config_id
    if not base.exists():
        return []

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in base.rglob("rounds.jsonl"):
        parts = path.relative_to(base).parts
        # protocol / condition / fmt / chain_N / rounds.jsonl
        if len(parts) < 4:
            continue
        protocol, condition, fmt, chain = parts[0], parts[1], parts[2], parts[3]
        if fmt != "STRUCTURED":
            continue
        for row in _load_jsonl(path):
            if row.get("parse_status") != "ok":
                continue
            buckets[(protocol, condition)].append(
                {
                    "protocol": protocol,
                    "condition": condition,
                    "fmt": fmt,
                    "chain": chain,
                    "round": row["round"],
                    "unit_key": f"{protocol}|{condition}|{fmt}|{chain}|{row['round']}",
                    "prompt": row.get("prompt") or "",
                    "response": row.get("text_final") or "",
                }
            )

    seed_payload = f"{exp.master_seed}|EVALAWARE_SAMPLE|{run_tag}|{config_id}".encode()
    seed_int = int(hashlib.sha256(seed_payload).hexdigest()[:16], 16)
    rng = random.Random(seed_int)
    selected: list[dict[str, Any]] = []
    for key in sorted(buckets):
        rows = list(buckets[key])
        rng.shuffle(rows)
        n = max(1, int(round(len(rows) * fraction))) if rows else 0
        # Keep total near 10%: if a bucket is tiny, still take at least 1 when fraction>0.
        if rows and fraction >= 0.10:
            n = max(1, int(round(len(rows) * fraction)))
        selected.extend(rows[:n])
    return selected
