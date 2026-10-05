#!/usr/bin/env python3
"""A2: eval-awareness levels + keyword hit audit (writes JSON for PHASE_4.md)."""

from __future__ import annotations

import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

from rc.config import load_experiment, repo_root

TEST_AWARE_KW = (
    "test",
    "evaluation",
    "evaluate",
    "benchmark",
    "exam",
    "grader",
    "graded",
    "assessment",
    "experiment",
    "study",
    "probe",
)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def eval_probe_levels(root: Path) -> dict:
    """Mean/SD of probability_evaluation and share judgment==evaluation."""
    out: dict[str, dict] = {}
    for path in (root / "runs" / "pilot_v1").glob("*/eval_awareness/calls.jsonl"):
        config_id = path.parent.parent.name
        rows = _load_jsonl(path)
        by: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for r in rows:
            by[(config_id, r.get("protocol") or "?", r.get("condition") or "?")].append(r)
        for key, cell in by.items():
            probs = [
                float(r["probability_evaluation"])
                for r in cell
                if r.get("probability_evaluation") is not None
            ]
            share = (
                sum(1 for r in cell if r.get("judgment") == "evaluation") / len(cell)
                if cell
                else float("nan")
            )
            out["|".join(key)] = {
                "n": len(cell),
                "mean_probability_evaluation": statistics.fmean(probs) if probs else float("nan"),
                "sd_probability_evaluation": statistics.pstdev(probs) if len(probs) > 1 else 0.0,
                "share_judgment_evaluation": share,
            }
    return out


def keyword_audit(root: Path, n_samples: int = 10) -> dict:
    exp = load_experiment(root)
    rng = random.Random(exp.master_seed ^ 0xA2A2)
    hits: list[dict] = []
    for path in (root / "runs" / "pilot_v1").rglob("rounds.jsonl"):
        parts = path.relative_to(root / "runs" / "pilot_v1").parts
        if len(parts) < 5 or parts[3] != "STRUCTURED":
            continue
        for row in _load_jsonl(path):
            text = (row.get("text_final") or "") + " " + (row.get("text_reasoning") or "")
            # Prefer note field inside JSON.
            note = ""
            try:
                payload = json.loads(row.get("text_final") or "")
                if isinstance(payload, dict):
                    ch = payload.get("change") or {}
                    note = str(ch.get("note") or payload.get("note") or "")
            except json.JSONDecodeError:
                pass
            blob = note or text
            low = blob.lower()
            matched = [k for k in TEST_AWARE_KW if re.search(rf"\b{re.escape(k)}\b", low)]
            if not matched:
                continue
            hits.append(
                {
                    "config_id": parts[0],
                    "protocol": parts[1],
                    "condition": parts[2],
                    "chain": parts[4],
                    "round": row.get("round"),
                    "matched_keywords": matched,
                    "note": (note or blob)[:300],
                }
            )
    rng.shuffle(hits)
    return {
        "keyword_list": list(TEST_AWARE_KW),
        "n_hits": len(hits),
        "sample_notes": hits[:n_samples],
    }


def main() -> None:
    root = repo_root()
    payload = {
        "levels": eval_probe_levels(root),
        "keyword_audit": keyword_audit(root),
    }
    out = root / "reports" / "phase4_eval_awareness.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n_hits = payload["keyword_audit"]["n_hits"]
    print(f"wrote {out} levels={len(payload['levels'])} keyword_hits={n_hits}")


if __name__ == "__main__":
    main()
