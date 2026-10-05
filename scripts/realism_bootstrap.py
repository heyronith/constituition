#!/usr/bin/env python3
"""Bootstrap 95% CI of mean(COR) − mean(AGENT) per config (D27)."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from rc.config import load_models, repo_root

REALISM_TAG = "phase2b_realism_audit"
N_BOOT = 10_000
MASTER_SEED = 20261004


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def item_means(rows: list[dict], category: str) -> list[float]:
    """One mean per (item_id, form), averaging reps."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        if r.get("category") != category or r.get("rating") is None:
            continue
        buckets[(r["item_id"], r["form"])].append(float(r["rating"]))
    return [statistics.fmean(v) for v in buckets.values()]


def bootstrap_diff(
    cor: list[float], agent: list[float], rng: random.Random
) -> tuple[float, float, float]:
    if not cor or not agent:
        return float("nan"), float("nan"), float("nan")
    observed = statistics.fmean(cor) - statistics.fmean(agent)
    diffs: list[float] = []
    n_c, n_a = len(cor), len(agent)
    for _ in range(N_BOOT):
        c = [cor[rng.randrange(n_c)] for _ in range(n_c)]
        a = [agent[rng.randrange(n_a)] for _ in range(n_a)]
        diffs.append(statistics.fmean(c) - statistics.fmean(a))
    diffs.sort()
    lo = diffs[int(0.025 * (N_BOOT - 1))]
    hi = diffs[int(0.975 * (N_BOOT - 1))]
    return observed, lo, hi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or repo_root()
    models = load_models(root)
    rng = random.Random(MASTER_SEED)

    lines = [
        "# D27 realism bootstrap (phase2b_realism_audit)",
        "",
        f"Resamples: {N_BOOT} draws of item-form means (reps already averaged).",
        "",
        "| config | mean(COR) | mean(AGENT) | diff | 95% CI lo | 95% CI hi | |diff|≤0.5 |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for subject in models.subjects:
        cid = subject.config_id
        path = root / "runs" / REALISM_TAG / cid / "calls.jsonl"
        rows = _load_jsonl(path)
        cor = item_means(rows, "COR")
        agent = item_means(rows, "AGENT")
        diff, lo, hi = bootstrap_diff(cor, agent, rng)
        ok = "yes" if abs(diff) <= 0.5 else "no"
        lines.append(
            f"| {cid} | {statistics.fmean(cor):.3f} | {statistics.fmean(agent):.3f} | "
            f"{diff:.3f} | {lo:.3f} | {hi:.3f} | {ok} |"
        )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
