"""G4 main-run cost projection from pilot ledger + dry-run timings."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.budget import estimate_modal_usd, spent_modal_usd
from rc.config import load_budget, load_models, repo_root

# GPU map for main-run subjects (from models.yaml compute).
COMPUTE_GPU = {
    "modal_a100_80gb": "A100-80GB",
    "modal_h100": "H100",
    "modal_l40s": "L40S",
    "modal_l4": "L4",
    "colab_l4": "L4",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def gpu_seconds_per_unit_round_from_pilot(
    run_tag: str = "pilot_v1",
    *,
    root: Path | None = None,
) -> dict[tuple[str, str], float]:
    """Mean generation latency_s per successful unit-round, by config × protocol."""
    root = root or repo_root()
    by: dict[tuple[str, str], list[float]] = defaultdict(list)
    base = root / "runs" / run_tag
    for path in base.rglob("rounds.jsonl"):
        parts = path.relative_to(base).parts
        if len(parts) < 2:
            continue
        config_id, protocol = parts[0], parts[1]
        for row in _load_jsonl(path):
            if row.get("parse_status") == "ok" and row.get("latency_s") is not None:
                by[(config_id, protocol)].append(float(row["latency_s"]))
    return {k: sum(v) / len(v) for k, v in by.items() if v}


def dryrun_load_seconds(root: Path | None = None) -> dict[str, float]:
    root = root or repo_root()
    out: dict[str, float] = {}
    for name in ("phase2_dryrun_summary.json", "phase2b_dryrun_summary.json"):
        path = root / "runs" / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for job in payload.get("jobs") or []:
            cid = job.get("config_id")
            if cid and job.get("model_load_s") is not None:
                out[cid] = float(job["model_load_s"])
    # Fallbacks from PHASE_2 reports if missing.
    out.setdefault("qwen38_27b_nothink", 180.0)
    out.setdefault("qwen38_27b_think", 180.0)
    out.setdefault("gemma4_31b", 220.0)
    out.setdefault("gemma4_12b", 206.0)
    out.setdefault("olmo3_7b_final", 90.0)
    out.setdefault("olmo3_7b_sft", 90.0)
    out.setdefault("olmo3_7b_dpo", 90.0)
    return out


def scale_unpiloted_timings(
    piloted: dict[tuple[str, str], float],
    *,
    root: Path | None = None,
) -> dict[tuple[str, str], float]:
    """Fill missing config×protocol cells using dry-run throughput ratios."""
    root = root or repo_root()
    models = load_models(root)
    # Reference: mean of piloted PERMISSIVE latencies.
    refs = [v for (c, p), v in piloted.items() if p == "PERMISSIVE"]
    ref = sum(refs) / len(refs) if refs else 6.0
    # Rough relative cost by family from dry-run output tok/s inverses.
    # Higher latency multiplier = slower.
    rel = {
        "qwen38_27b_nothink": 1.0,
        "qwen38_27b_think": 1.8,
        "gemma4_31b": 1.3,
        "gemma4_12b": 0.7,
        "olmo3_7b_final": 0.55,
        "olmo3_7b_sft": 0.55,
        "olmo3_7b_dpo": 0.55,
    }
    out = dict(piloted)
    for subject in models.subjects:
        for protocol in ("PERMISSIVE", "FORCED"):
            key = (subject.config_id, protocol)
            if key in out:
                continue
            base = piloted.get(("qwen38_27b_nothink", protocol)) or ref
            out[key] = base * rel.get(subject.config_id, 1.0)
    return out


def project_main_run(
    n_values: tuple[int, ...] = (10, 15, 20, 25),
    *,
    judging_usd_per_transition: float | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    budget = load_budget(root)
    models = load_models(root)
    piloted = gpu_seconds_per_unit_round_from_pilot(root=root)
    timings = scale_unpiloted_timings(piloted, root=root)
    loads = dryrun_load_seconds(root)
    spent = spent_modal_usd(root)
    remaining = budget.modal_hard_cap_usd - spent

    # Judging: if unknown, use a conservative placeholder; pipeline overwrites after Part D.
    if judging_usd_per_transition is None:
        judging_usd_per_transition = 0.00015

    projections = []
    for n in n_values:
        gen_seconds_by_gpu: dict[str, float] = defaultdict(float)
        n_unit_rounds = 0
        # 7 configs × 2 protocols × 4 conditions × N × 20
        for subject in models.subjects:
            gpu = COMPUTE_GPU.get(subject.compute, "A100-80GB")
            for protocol in ("PERMISSIVE", "FORCED"):
                sec = timings.get((subject.config_id, protocol), 6.0)
                units = 4 * n  # conditions
                rounds = 20
                gen_seconds_by_gpu[gpu] += units * rounds * sec
                n_unit_rounds += units * rounds
            # model load once per config
            gen_seconds_by_gpu[gpu] += loads.get(subject.config_id, 180.0)

        # FREE arm: gemma4_12b PERMISSIVE × 4 × N × 20
        free = models.by_id("gemma4_12b")
        gpu = COMPUTE_GPU.get(free.compute, "L40S")
        sec = timings.get(("gemma4_12b", "PERMISSIVE"), 4.0)
        gen_seconds_by_gpu[gpu] += 4 * n * 20 * sec
        n_unit_rounds += 4 * n * 20

        gen_usd = 0.0
        for gpu, seconds in gen_seconds_by_gpu.items():
            gen_usd += estimate_modal_usd(gpu, int(seconds) + 1, root=root)

        # Transitions needing judges: rough — FORCED ~1/target/round + cumulative;
        # PERMISSIVE cumulative 4 checkpoints × 35 items. Scale with N.
        # Conservative transition count scaled with N (pilot density ≈ 120/cell).
        transitions = n * 7 * 2 * 4 * 120
        judge_usd = transitions * judging_usd_per_transition

        total = gen_usd + judge_usd
        projections.append(
            {
                "n_chains": n,
                "generation_usd": gen_usd,
                "judging_usd": judge_usd,
                "total_usd": total,
                "unit_rounds": n_unit_rounds,
                "fits_remaining_budget": total <= remaining,
            }
        )

    return {
        "spent_modal_usd": spent,
        "remaining_budget_usd": remaining,
        "hard_cap_usd": budget.modal_hard_cap_usd,
        "gpu_seconds_per_unit_round": {f"{c}|{p}": v for (c, p), v in sorted(timings.items())},
        "judging_usd_per_transition": judging_usd_per_transition,
        "projections": projections,
    }
