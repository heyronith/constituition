"""Append-only spend ledger and preflight caps."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from rc.config import load_budget, repo_root
from rc.io_utils import append_jsonl, git_sha

Platform = Literal["modal", "colab"]


class BudgetExceeded(RuntimeError):
    pass


def ledger_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "budget" / "ledger.jsonl"


def _parse_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed ledger line {line_no} in {path}") from exc
    return rows


def spent_modal_usd(root: Path | None = None) -> float:
    total = 0.0
    for row in _parse_ledger(ledger_path(root)):
        if row.get("platform") != "modal":
            continue
        actual = row.get("actual_usd")
        if actual is not None:
            total += float(actual)
            continue
        est = row.get("est_usd")
        if est is not None:
            total += float(est)
    return total


def spent_colab_cu(root: Path | None = None) -> float:
    total = 0.0
    for row in _parse_ledger(ledger_path(root)):
        if row.get("platform") != "colab":
            continue
        actual = row.get("actual_cu")
        if actual is not None:
            total += float(actual)
            continue
        est = row.get("est_cu")
        if est is not None:
            total += float(est)
    return total


def gpu_price(gpu: str, root: Path | None = None) -> float:
    budget = load_budget(root)
    try:
        return budget.gpu_prices_usd_per_second[gpu]
    except KeyError as exc:
        raise KeyError(
            f"unknown gpu {gpu!r}; prices={list(budget.gpu_prices_usd_per_second)}"
        ) from exc


def estimate_modal_usd(
    gpu: str,
    max_seconds: int,
    *,
    cpu_cores: float | None = None,
    memory_gib: float | None = None,
    root: Path | None = None,
) -> float:
    """GPU + reserved CPU + reserved memory (Modal bills all three)."""
    budget = load_budget(root)
    cores = budget.default_cpu_cores if cpu_cores is None else cpu_cores
    mem = budget.default_memory_gib if memory_gib is None else memory_gib
    gpu_cost = gpu_price(gpu, root) * max_seconds
    if gpu == "cpu":
        # Smoke tests: treat gpu key as CPU billing only.
        return budget.cpu_usd_per_core_second * max(cores, 0.125) * max_seconds
    cpu_cost = budget.cpu_usd_per_core_second * cores * max_seconds
    mem_cost = budget.memory_usd_per_gib_second * mem * max_seconds
    return gpu_cost + cpu_cost + mem_cost


def preflight(
    gpu: str,
    max_seconds: int,
    phase: int | str,
    job_id: str,
    *,
    platform: Platform = "modal",
    override_job_cap_usd: float | None = None,
    hard_cap_usd: float | None = None,
    cpu_cores: float | None = None,
    memory_gib: float | None = None,
    root: Path | None = None,
) -> int:
    """Estimate cost and refuse to start if caps would be exceeded.

    Returns `max_seconds` for use as the Modal function timeout.
    """
    root = root or repo_root()
    budget = load_budget(root)
    if platform == "modal":
        estimate = estimate_modal_usd(
            gpu, max_seconds, cpu_cores=cpu_cores, memory_gib=memory_gib, root=root
        )
        job_cap = (
            override_job_cap_usd
            if override_job_cap_usd is not None
            else budget.modal_per_job_default_cap_usd
        )
        if override_job_cap_usd is not None:
            logging.getLogger("rc.budget").warning(
                "override_job_cap_usd=%s for job_id=%s phase=%s",
                override_job_cap_usd,
                job_id,
                phase,
            )
        if estimate > job_cap:
            raise BudgetExceeded(
                f"job {job_id} estimate ${estimate:.4f} exceeds per-job cap ${job_cap:.2f}"
            )
        already = spent_modal_usd(root)
        project_cap = hard_cap_usd if hard_cap_usd is not None else budget.modal_hard_cap_usd
        # Phase-2 dry run also enforces its own $6 hard stop.
        if str(phase) in {"2", "2b", "phase2", "phase2b", "phase2_dryrun"}:
            project_cap = min(project_cap, budget.phase2_dryrun_hard_cap_usd)
        if hard_cap_usd is not None:
            project_cap = hard_cap_usd
        if already + estimate > project_cap:
            raise BudgetExceeded(
                f"job {job_id} would bring Modal spend to "
                f"${already + estimate:.4f} > hard cap ${project_cap:.2f}"
            )
    else:
        if budget.colab_l4_cu_per_hour is None:
            estimate = 0.0
        else:
            estimate = budget.colab_l4_cu_per_hour * (max_seconds / 3600.0)
        already = spent_colab_cu(root)
        if already + estimate > budget.colab_cu_cap:
            raise BudgetExceeded(
                f"job {job_id} would bring Colab spend to "
                f"{already + estimate:.4f} CU > cap {budget.colab_cu_cap:.1f} CU"
            )
    return max_seconds


def record_actual(
    *,
    job_id: str,
    phase: int | str,
    platform: Platform,
    gpu: str,
    max_seconds: int,
    actual_seconds: float,
    note: str = "",
    est_usd: float | None = None,
    est_cu: float | None = None,
    actual_usd: float | None = None,
    actual_cu: float | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    record = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "job_id": job_id,
        "phase": phase,
        "platform": platform,
        "gpu": gpu,
        "est_usd": est_usd,
        "est_cu": est_cu,
        "max_seconds": max_seconds,
        "actual_seconds": actual_seconds,
        "actual_usd": actual_usd,
        "actual_cu": actual_cu,
        "git_sha": git_sha(root),
        "note": note,
    }
    append_jsonl(ledger_path(root), record)
    return record


def summary(root: Path | None = None) -> str:
    root = root or repo_root()
    budget = load_budget(root)
    modal_spent = spent_modal_usd(root)
    colab_spent = spent_colab_cu(root)
    lines = [
        f"Modal: ${modal_spent:.4f} / ${budget.modal_hard_cap_usd:.2f} hard cap "
        f"(per-job default ${budget.modal_per_job_default_cap_usd:.2f}; "
        f"phase2 dry-run ${budget.phase2_dryrun_hard_cap_usd:.2f})",
        f"Colab: {colab_spent:.4f} / {budget.colab_cu_cap:.1f} CU "
        f"(L4 CU/hour={budget.colab_l4_cu_per_hour})",
    ]
    text = "\n".join(lines)
    print(text)
    return text
