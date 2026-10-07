"""Phase 7 main-run Modal orchestrator (detach tests + olmo-final canary).

Usage:
  # Detach-test (Part 3):
  uv run modal run --detach modal_apps/phase7_main.py::detach_test --rounds 3

  # Canary (Part 4):
  uv run modal run --detach modal_apps/phase7_main.py::canary
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import modal

APP_NAME = "rc-phase7-main"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
VLLM_VERSION = "0.30.0"
SMOKE_ID = "qwen35_08b_smoke"
CANARY_CONFIG = "olmo3_7b_final"
MAIN_RUN_TAG = "main_v1"
DETACH_RUN_TAG = "detach_test_v1"
BUDGET_STOP_RUN_TAG = "detach_test_budget_v1"

app = modal.App(APP_NAME)
hf_vol = modal.Volume.from_name(HF_VOLUME, create_if_missing=True)
runs_vol = modal.Volume.from_name(RUNS_VOLUME, create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04",
        add_python="3.11",
    )
    .entrypoint([])
    .apt_install("git")
    .pip_install(
        f"vllm=={VLLM_VERSION}",
        "huggingface_hub>=0.26",
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
        "openai>=1.60",
        "httpx>=0.28",
        "textstat>=0.7.13",
    )
    .env(
        {
            "HF_HOME": HF_CACHE,
            "HUGGINGFACE_HUB_CACHE": f"{HF_CACHE}/hub",
            "TRANSFORMERS_CACHE": f"{HF_CACHE}/hub",
            "CUDA_HOME": "/usr/local/cuda",
        }
    )
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
    .add_local_file("pyproject.toml", remote_path=f"{REMOTE_REPO}/pyproject.toml")
)

cpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
        "openai>=1.60",
        "httpx>=0.28",
        "huggingface_hub>=0.26",
    )
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
    .add_local_file("pyproject.toml", remote_path=f"{REMOTE_REPO}/pyproject.toml")
)


def _link_runs() -> Path:
    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)
    return Path(REMOTE_REPO)


def _status_path(run_tag: str) -> Path:
    return Path(REMOTE_RUNS) / run_tag / "STATUS.json"


def _write_status(run_tag: str, **payload) -> None:
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from rc.phase7_status import write_status

    write_status(_status_path(run_tag), {"run_tag": run_tag, **payload})
    runs_vol.commit()


def _usd_so_far(gpu: str, elapsed_s: float, *, cpu: float = 4.0, mem: float = 16.0) -> float:
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from rc.budget import estimate_modal_usd

    return estimate_modal_usd(gpu, max(1, int(elapsed_s)), cpu_cores=cpu, memory_gib=mem)


@app.function(
    image=image,
    gpu="L4",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=86400,  # 24h Modal max
    scaledown_window=2,
    cpu=4,
    memory=16384,
)
def generate_config(
    config_id: str,
    run_tag: str,
    *,
    protocols: list[str],
    conditions: list[str],
    forced_chains: list[int],
    forced_rounds: int,
    permissive_chains: list[int],
    permissive_rounds: int,
    stage_cap_usd: float,
    git_sha_value: str = "",
    gpu_name: str = "L4",
) -> dict:
    """Generate one config's main-run (or detach-test) cells with resume + budget stop."""
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from huggingface_hub import snapshot_download

    from rc.budget import estimate_modal_usd
    from rc.chain_runner import Unit, run_config
    from rc.config import load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for
    from rc.phase7_status import write_status

    started = time.perf_counter()
    status_path = Path(REMOTE_RUNS) / run_tag / "STATUS.json"
    prev_completed = 0
    if status_path.exists():
        try:
            prev = json.loads(status_path.read_text(encoding="utf-8"))
            prev_completed = int(prev.get("rounds_completed") or 0)
        except (json.JSONDecodeError, TypeError, ValueError):
            prev_completed = 0

    units: list[Unit] = []
    rounds_total = 0
    if "FORCED" in protocols:
        for cond in conditions:
            for ch in forced_chains:
                units.append(Unit("FORCED", cond, "STRUCTURED", ch))
        rounds_total = max(rounds_total, forced_rounds)
    if "PERMISSIVE" in protocols:
        for cond in conditions:
            for ch in permissive_chains:
                units.append(Unit("PERMISSIVE", cond, "STRUCTURED", ch))
        rounds_total = max(rounds_total, permissive_rounds)

    summaries: list = []
    budget_stopped = False
    # Kill-switch headroom (D57): stop before the cap with ≥ (one model load + one
    # round batch) cost remaining. Conservative priors until measured.
    LOAD_PRIOR_S = 420.0
    ROUND_PRIOR_S = 120.0
    load_usd_est = estimate_modal_usd(
        gpu_name, int(LOAD_PRIOR_S), cpu_cores=4.0, memory_gib=16.0, root=root
    )
    round_usd_est = estimate_modal_usd(
        gpu_name, int(ROUND_PRIOR_S), cpu_cores=4.0, memory_gib=16.0, root=root
    )
    headroom_usd = load_usd_est + round_usd_est

    def _elapsed_usd() -> tuple[float, float]:
        elapsed = time.perf_counter() - started
        usd = estimate_modal_usd(
            gpu_name, max(1, int(elapsed)), cpu_cores=4.0, memory_gib=16.0, root=root
        )
        return elapsed, usd

    def _budget_stop_now(*, rounds_completed: int, n_rounds: int, reason: str) -> None:
        nonlocal budget_stopped
        budget_stopped = True
        elapsed, usd = _elapsed_usd()
        write_status(
            Path(REMOTE_RUNS) / run_tag / "STATUS.json",
            {
                "run_tag": run_tag,
                "stage": "generate",
                "state": "budget_stop",
                "config_id": config_id,
                "rounds_completed": rounds_completed,
                "rounds_total": n_rounds,
                "elapsed_gpu_seconds": elapsed,
                "usd_so_far": usd,
                "usd_projected_total": usd,
                "stage_cap_usd": stage_cap_usd,
                "budget_headroom_usd": headroom_usd,
                "budget_stop_reason": reason,
            },
        )
        runs_vol.commit()
        raise RuntimeError("budget_stop")

    # Pre-load gate: refuse to start if load+one-round alone would breach the cap.
    if headroom_usd > stage_cap_usd:
        write_status(
            status_path,
            {
                "run_tag": run_tag,
                "stage": "generate",
                "state": "budget_stop",
                "config_id": config_id,
                "rounds_completed": prev_completed,
                "rounds_total": rounds_total,
                "elapsed_gpu_seconds": 0.0,
                "usd_so_far": 0.0,
                "usd_projected_total": 0.0,
                "stage_cap_usd": stage_cap_usd,
                "budget_headroom_usd": headroom_usd,
                "budget_stop_reason": "pre_load_headroom",
            },
        )
        runs_vol.commit()
        return {
            "state": "budget_stop",
            "config_id": config_id,
            "summaries": summaries,
            "elapsed_s": 0.0,
            "usd_so_far": 0.0,
            "budget_stop_reason": "pre_load_headroom",
        }

    write_status(
        status_path,
        {
            "run_tag": run_tag,
            "stage": "generate",
            "state": "loading_model",
            "config_id": config_id,
            "rounds_completed": prev_completed,
            "rounds_total": rounds_total,
            "elapsed_gpu_seconds": 0.0,
            "usd_so_far": 0.0,
            "stage_cap_usd": stage_cap_usd,
            "budget_headroom_usd": headroom_usd,
        },
    )
    runs_vol.commit()
    repo, rev = load_lock_revision(config_id, root)
    model_path = snapshot_download(
        repo_id=repo, revision=rev, cache_dir=HF_CACHE, local_files_only=True
    )
    vllm_cfg = load_vllm(root)
    mlen = max_model_len_for(config_id, root)
    if config_id == SMOKE_ID:
        mlen = min(4096, mlen)
    backend = VLLMBackend(
        config_id,
        model_path=model_path,
        revision=None,
        max_model_len=mlen,
        gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
        enforce_eager=False,
        max_num_seqs=vllm_cfg.max_num_seqs,
        root=root,
    )

    def _commit_and_status(t: int, protocol: str, n_rounds: int) -> None:
        nonlocal round_usd_est, headroom_usd
        runs_vol.commit()
        elapsed, usd = _elapsed_usd()
        # Refresh round-cost estimate from observed post-load burn / rounds done.
        if t >= 0 and elapsed > LOAD_PRIOR_S:
            per = (usd - load_usd_est) / max(t + 1, 1)
            if per > 0:
                round_usd_est = max(round_usd_est, per)
                headroom_usd = load_usd_est + round_usd_est
        write_status(
            Path(REMOTE_RUNS) / run_tag / "STATUS.json",
            {
                "run_tag": run_tag,
                "stage": "generate",
                "state": "running",
                "config_id": config_id,
                "protocol": protocol,
                "rounds_completed": t + 1,
                "rounds_total": n_rounds,
                "parse_failures": None,
                "resamples": None,
                "censored_chains": None,
                "elapsed_gpu_seconds": elapsed,
                "usd_so_far": usd,
                "usd_projected_total": None,
                "batch_ids": None,
                "stage_cap_usd": stage_cap_usd,
                "budget_headroom_usd": headroom_usd,
            },
        )
        runs_vol.commit()
        # Stop before starting another round if remaining budget < one round.
        if usd + round_usd_est > stage_cap_usd:
            _budget_stop_now(
                rounds_completed=t + 1,
                n_rounds=n_rounds,
                reason="post_round_headroom",
            )

    # Post-load gate: measured load cost updates headroom; stop if next round won't fit.
    elapsed0, usd0 = _elapsed_usd()
    load_usd_est = max(load_usd_est, usd0)
    headroom_usd = load_usd_est + round_usd_est
    write_status(
        Path(REMOTE_RUNS) / run_tag / "STATUS.json",
        {
            "run_tag": run_tag,
            "stage": "generate",
            "state": "model_ready",
            "config_id": config_id,
            "rounds_completed": prev_completed,
            "rounds_total": rounds_total,
            "elapsed_gpu_seconds": elapsed0,
            "usd_so_far": usd0,
            "stage_cap_usd": stage_cap_usd,
            "budget_headroom_usd": headroom_usd,
        },
    )
    runs_vol.commit()
    if usd0 + round_usd_est > stage_cap_usd:
        try:
            _budget_stop_now(
                rounds_completed=prev_completed,
                n_rounds=rounds_total,
                reason="post_load_headroom",
            )
        except RuntimeError as exc:
            if "budget_stop" not in str(exc):
                raise
            return {
                "state": "budget_stop",
                "config_id": config_id,
                "summaries": summaries,
                "elapsed_s": time.perf_counter() - started,
                "usd_so_far": usd0,
                "budget_stop_reason": "post_load_headroom",
            }

    try:
        if "FORCED" in protocols:
            forced_units = [u for u in units if u.protocol == "FORCED"]

            def _after_f(t: int) -> None:
                _commit_and_status(t, "FORCED", forced_rounds)

            summaries.append(
                run_config(
                    backend,
                    config_id,
                    forced_units,
                    rounds=forced_rounds,
                    run_tag=run_tag,
                    root=root,
                    after_round_commit=_after_f,
                )
            )
        if "PERMISSIVE" in protocols and not budget_stopped:
            perm_units = [u for u in units if u.protocol == "PERMISSIVE"]

            def _after_p(t: int) -> None:
                _commit_and_status(t, "PERMISSIVE", permissive_rounds)

            summaries.append(
                run_config(
                    backend,
                    config_id,
                    perm_units,
                    rounds=permissive_rounds,
                    run_tag=run_tag,
                    root=root,
                    after_round_commit=_after_p,
                )
            )
    except RuntimeError as exc:
        if "budget_stop" not in str(exc):
            raise
        return {
            "state": "budget_stop",
            "config_id": config_id,
            "summaries": summaries,
            "elapsed_s": time.perf_counter() - started,
        }

    elapsed = time.perf_counter() - started
    usd = estimate_modal_usd(
        gpu_name, max(1, int(elapsed)), cpu_cores=4.0, memory_gib=16.0, root=root
    )
    from rc.chain_runner import verify_run_consistency

    gate = verify_run_consistency(run_tag, config_id, root=root)
    if not gate.get("ok"):
        write_status(
            Path(REMOTE_RUNS) / run_tag / "STATUS.json",
            {
                "run_tag": run_tag,
                "stage": "generate",
                "state": "failed",
                "config_id": config_id,
                "rounds_completed": rounds_total,
                "rounds_total": rounds_total,
                "elapsed_gpu_seconds": elapsed,
                "usd_so_far": usd,
                "error": f"consistency_gate n_failed={gate.get('n_failed')}",
                "stage_cap_usd": stage_cap_usd,
            },
        )
        runs_vol.commit()
        return {
            "state": "failed",
            "config_id": config_id,
            "summaries": summaries,
            "elapsed_s": elapsed,
            "usd_so_far": usd,
            "consistency": gate,
        }
    write_status(
        Path(REMOTE_RUNS) / run_tag / "STATUS.json",
        {
            "run_tag": run_tag,
            "stage": "generate",
            "state": "generate_done",
            "config_id": config_id,
            "rounds_completed": rounds_total,
            "rounds_total": rounds_total,
            "elapsed_gpu_seconds": elapsed,
            "usd_so_far": usd,
            "usd_projected_total": usd,
            "stage_cap_usd": stage_cap_usd,
            "consistency_ok": True,
        },
    )
    runs_vol.commit()
    return {
        "state": "generate_done",
        "config_id": config_id,
        "summaries": summaries,
        "elapsed_s": elapsed,
        "usd_so_far": usd,
    }


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("openai-key"),
        modal.Secret.from_name("openrouter-key"),
    ],
    timeout=86400,
    cpu=2,
    memory=8192,
)
def code_canary(
    run_tag: str,
    config_id: str,
    stage_api_cap_usd: float,
    git_sha_value: str = "",
    max_gpt: int | None = None,
    max_mimo: int | None = None,
    skip_canary_checks: bool = False,
) -> dict:
    """GPT-5.4 Batch + MiMo subsample + integrity + canary_checks (operational only)."""
    import os
    import sys

    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from rc.budget import spent_api_usd
    from rc.main_run_coding import (
        code_gpt54,
        code_mimo_subsample,
        extract_main_transitions,
        integrity_for_judge,
    )
    from rc.judging import judge_fate_batch
    from rc.openrouter_backend import OpenRouterBackend
    from rc.phase7_status import write_status

    write_status(
        Path(REMOTE_RUNS) / run_tag / "STATUS.json",
        {
            "run_tag": run_tag,
            "stage": "coding",
            "state": "running",
            "config_id": config_id,
        },
    )
    runs_vol.commit()

    try:
        from rc.chain_runner import verify_run_consistency

        gate = verify_run_consistency(run_tag, config_id, root=root)
        if not gate.get("ok"):
            write_status(
                Path(REMOTE_RUNS) / run_tag / "STATUS.json",
                {
                    "run_tag": run_tag,
                    "stage": "coding",
                    "state": "failed",
                    "config_id": config_id,
                    "error": f"consistency_gate n_failed={gate.get('n_failed')}",
                    "consistency": {"n_failed": gate.get("n_failed"), "n_chains": gate.get("n_chains")},
                },
            )
            runs_vol.commit()
            raise RuntimeError(f"consistency_gate_failed n_failed={gate.get('n_failed')}")

        all_t = extract_main_transitions(run_tag, root=root)
        # Restrict to this config
        transitions = [t for t in all_t if t.get("config_id") == config_id]
        # D49 coding set: all FORCED per-round (+absorbed); FORCED cum; PERMISSIVE cum
        gpt_set = [
            t
            for t in transitions
            if (
                t.get("protocol") == "FORCED"
                and t.get("kind") in {"per_round", "per_round_absorbed", "cumulative"}
            )
            or (t.get("protocol") == "PERMISSIVE" and t.get("kind") == "cumulative")
        ]
        if max_gpt is not None:
            gpt_set = gpt_set[: max(0, int(max_gpt))]

        api0 = spent_api_usd(root)
        gpt_rows, gpt_meta = code_gpt54(
            gpt_set, run_tag=run_tag, root=root, job_id=f"phase7a-canary-gpt54-{config_id}"
        )
        if max_mimo is not None:
            # Smoke path: direct MiMo on ≤5 transitions (not design-grid subsample).
            mimo_src = [
                t
                for t in transitions
                if t.get("protocol") == "FORCED" and t.get("kind") == "per_round"
            ][: int(max_mimo)]
            for t in mimo_src:
                t.setdefault("source", "pilot")
                t.setdefault("rewrite", t.get("revised") or t.get("rewrite"))
            work_dir = root / "runs" / run_tag / "coding" / "mimo_batch"
            mimo_backend = OpenRouterBackend(
                "mimo_v26_pro",
                work_dir=work_dir,
                root=root,
                job_id=f"phase7a-smoke-mimo-{config_id}",
            )
            mimo_rows = judge_fate_batch(
                mimo_backend,
                "mimo_v26_pro",
                mimo_src,
                root=root,
                rubric_version="v2",
                seed_base=20261004 + 17,
            )
            mimo_meta = {"n": len(mimo_rows), "api_usd": getattr(mimo_backend.last_cost, "usd", None)}
            n_miss = 0
        else:
            mimo_rows, mimo_meta, n_miss = code_mimo_subsample(
                [t for t in transitions if t.get("protocol") == "FORCED"],
                run_tag=run_tag,
                root=root,
                job_id=f"phase7a-canary-mimo-{config_id}",
                config_id=config_id,
            )
        api1 = spent_api_usd(root)
        api_spend = api1 - api0

        gates_gpt = integrity_for_judge(
            gpt_set,
            gpt_rows,
            out_path=root / "runs" / run_tag / "coding" / "integrity_gpt54.json",
            root=root,
        )
        gates_mimo = integrity_for_judge(
            mimo_rows,
            mimo_rows,
            out_path=root / "runs" / run_tag / "coding" / "integrity_mimo.json",
            root=root,
        )
    except Exception as exc:
        write_status(
            Path(REMOTE_RUNS) / run_tag / "STATUS.json",
            {
                "run_tag": run_tag,
                "stage": "coding",
                "state": "failed",
                "config_id": config_id,
                "error": f"{type(exc).__name__}: {exc}"[:500],
            },
        )
        runs_vol.commit()
        raise

    # Operational canary checks only (no category rates).
    if skip_canary_checks:
        checks = {
            "skip_canary_checks": True,
            "all_pass": bool(gates_gpt.get("ok")) and bool(gates_mimo.get("ok")),
            "C3_judge_integrity": {
                "pass": bool(gates_gpt.get("ok")) and bool(gates_mimo.get("ok")),
                "gpt54_ok": gates_gpt.get("ok"),
                "mimo_ok": gates_mimo.get("ok"),
            },
            "api_spend_usd": api_spend,
            "gpt_meta": gpt_meta,
            "mimo_meta": mimo_meta,
        }
    else:
        checks = _compute_canary_checks(
            root=root,
            run_tag=run_tag,
            config_id=config_id,
            gpt_meta=gpt_meta,
            mimo_meta=mimo_meta,
            gates_gpt=gates_gpt,
            gates_mimo=gates_mimo,
            api_spend=api_spend,
            stage_api_cap_usd=stage_api_cap_usd,
            n_mimo_missing=n_miss,
        )
    out = root / "runs" / run_tag / "canary_checks.json"
    out.write_text(json.dumps(checks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_status(
        Path(REMOTE_RUNS) / run_tag / "STATUS.json",
        {
            "run_tag": run_tag,
            "stage": "done",
            "state": "done" if checks.get("all_pass") else "canary_fail",
            "config_id": config_id,
            "batch_ids": {"gpt54": gpt_meta.get("batch_id")},
            "usd_so_far": None,
            "checks_pass": checks.get("all_pass"),
        },
    )
    runs_vol.commit()
    return checks


def _compute_canary_checks(
    *,
    root: Path,
    run_tag: str,
    config_id: str,
    gpt_meta: dict,
    mimo_meta: dict,
    gates_gpt: dict,
    gates_mimo: dict,
    api_spend: float,
    stage_api_cap_usd: float,
    n_mimo_missing: int,
) -> dict:
    """C1–C6 operational checks (no hypothesis metrics)."""
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from rc.budget import estimate_modal_usd, spent_modal_usd
    from rc.d49_power_g4 import project_g4_d49
    from rc.io_utils import sha256_file

    base = root / "runs" / run_tag / config_id
    n_chains = n_ok = n_censored = n_rounds_ok = n_rounds_fail = 0
    dup_rounds = False
    for chain_dir in sorted(base.rglob("chain_*")) if base.exists() else []:
        if not chain_dir.is_dir():
            continue
        n_chains += 1
        meta_path = chain_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if meta.get("censored_at_round") is not None:
            n_censored += 1
        else:
            n_ok += 1
        rounds = []
        rp = chain_dir / "rounds.jsonl"
        if rp.exists():
            seen = set()
            for line in rp.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                r = int(row["round"])
                if row.get("parse_status") == "ok":
                    n_rounds_ok += 1
                    if r in seen:
                        dup_rounds = True
                    seen.add(r)
                    rounds.append(r)
                else:
                    n_rounds_fail += 1
    parse_rate = n_rounds_ok / max(n_rounds_ok + n_rounds_fail, 1)
    censor_frac = n_censored / max(n_chains, 1)

    # C2: G4 projection for this config at L4 rates (operational).
    g4 = project_g4_d49(25, root=root)
    # Prefer per-config breakdown if present; else scale total/7.
    at = g4.get("at_chosen_n") or {}
    modal_proj_total = float(at.get("modal_generation_usd") or at.get("modal_usd") or 66.51)
    # OLMo share ≈ 1/7 of gen if no breakdown; refine with pilot timings ratio later.
    modal_proj_config = modal_proj_total / 7.0
    # Actual from STATUS
    status = {}
    sp = root / "runs" / run_tag / "STATUS.json"
    if sp.exists():
        status = json.loads(sp.read_text(encoding="utf-8"))
    modal_actual = float(status.get("usd_so_far") or 0.0)

    gpt_n = int(gpt_meta.get("n") or 0)
    gpt_usd = float(gpt_meta.get("api_usd") or 0.0)
    per_tx = (gpt_usd / gpt_n) if gpt_n else None
    # Pilot gpt54 per-transition projection
    pilot_meta = root / "runs" / "pilot_v1_coding_v3" / "coding_v3" / "gpt54_meta.json"
    proj_per = None
    if pilot_meta.exists():
        pm = json.loads(pilot_meta.read_text(encoding="utf-8"))
        proj_per = float(pm["api_usd"]) / int(pm["n"])

    c1 = parse_rate >= 0.98 and censor_frac <= 0.05
    c2 = modal_actual <= 1.2 * modal_proj_config if modal_proj_config > 0 else False
    c3 = bool(gates_gpt.get("ok")) and bool(gates_mimo.get("ok"))
    c4 = (per_tx is not None and proj_per is not None and per_tx <= 1.2 * proj_per)
    c5 = (not dup_rounds) and n_chains > 0
    # C6 forecast
    spent_m = spent_modal_usd(root) + modal_actual
    # Rescale full-run Modal gen by canary actual / projection for this config
    scale = (modal_actual / modal_proj_config) if modal_proj_config > 0 else 1.0
    proj_full_modal = spent_m - modal_actual + modal_proj_total * scale
    # H3 placeholder mid
    proj_full_modal += 12.0
    api_proj = float(at.get("api_usd") or 30.29) * (scale if scale == scale else 1.0)
    spent_api = float(api_spend)
    proj_full_api = spent_api + api_proj * 0.85  # rough remaining
    c6 = proj_full_modal <= 130.0 and proj_full_api <= 40.0

    checks = {
        "C1_subject_parsing": {
            "pass": c1,
            "parse_rate": parse_rate,
            "censor_frac": censor_frac,
            "n_chains": n_chains,
        },
        "C2_modal_cost": {
            "pass": c2,
            "actual_usd": modal_actual,
            "projected_config_usd": modal_proj_config,
            "ratio_cap": 1.2,
        },
        "C3_judge_integrity": {
            "pass": c3,
            "gpt54_ok": gates_gpt.get("ok"),
            "mimo_ok": gates_mimo.get("ok"),
        },
        "C4_api_cost": {
            "pass": c4,
            "usd_per_transition": per_tx,
            "projected_usd_per_transition": proj_per,
        },
        "C5_storage": {
            "pass": c5,
            "duplicate_rounds": dup_rounds,
            "n_chains": n_chains,
            "mimo_slots_missing": n_mimo_missing,
        },
        "C6_full_run_forecast": {
            "pass": c6,
            "proj_modal_usd": proj_full_modal,
            "proj_api_usd": proj_full_api,
            "modal_cap": 130.0,
            "api_cap": 40.0,
            "scale_from_canary": scale,
        },
        "all_pass": all([c1, c2, c3, c4, c5, c6]),
        "stage_api_cap_usd": stage_api_cap_usd,
        "api_spend_usd": api_spend,
    }
    return checks


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=600,
)
def orchestrate_detach(
    rounds: int,
    stage_cap_usd: float = 0.50,
    git_sha_value: str = "",
    run_tag: str = DETACH_RUN_TAG,
) -> dict:
    """Detach-test orchestrator: smoke FORCED SELF, 2 chains."""
    result = generate_config.remote(
        SMOKE_ID,
        run_tag,
        protocols=["FORCED"],
        conditions=["SELF_REFLECT"],
        forced_chains=[0, 1],
        forced_rounds=rounds,
        permissive_chains=[],
        permissive_rounds=0,
        stage_cap_usd=stage_cap_usd,
        git_sha_value=git_sha_value,
        gpu_name="L4",
    )
    return result


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=86400,
)
def orchestrate_canary(
    git_sha_value: str = "",
    *,
    code_only: bool = False,
    stage_cap_usd: float = 8.0,
    stage_api_cap_usd: float = 6.0,
    run_tag: str = MAIN_RUN_TAG,
) -> dict:
    """Canary: generate olmo3_7b_final full cells → consistency → code → checks."""
    import traceback

    try:
        gen: dict | None = None
        if not code_only:
            gen = generate_config.remote(
                CANARY_CONFIG,
                run_tag,
                protocols=["FORCED", "PERMISSIVE"],
                conditions=["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"],
                forced_chains=list(range(25)),
                forced_rounds=20,
                permissive_chains=list(range(5)),
                permissive_rounds=10,
                stage_cap_usd=stage_cap_usd,
                git_sha_value=git_sha_value,
                gpu_name="L4",
            )
            if gen.get("state") in {"budget_stop", "failed"}:
                return {"state": gen.get("state"), "generate": gen}
        checks = code_canary.remote(
            run_tag, CANARY_CONFIG, stage_api_cap_usd, git_sha_value=git_sha_value
        )
        return {"state": "done", "generate": gen, "checks": checks}
    except Exception as exc:
        import sys

        sys.path.insert(0, f"{REMOTE_REPO}/src")
        from rc.phase7_status import write_status

        write_status(
            Path(REMOTE_RUNS) / run_tag / "STATUS.json",
            {
                "run_tag": run_tag,
                "stage": "orchestrate",
                "state": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": traceback.format_exc()[-4000:],
            },
        )
        runs_vol.commit()
        raise


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=86400,
)
def orchestrate_smoke_d59(git_sha_value: str = "") -> dict:
    """D59 §3.6: L4 smoke 2 chains × 4 rounds, stop/resume, consistency, tiny Batch+MiMo."""
    import traceback

    smoke_tag = "d59_smoke_v1"
    try:
        # First leg: 2 rounds
        generate_config.remote(
            SMOKE_ID,
            smoke_tag,
            protocols=["FORCED"],
            conditions=["SELF_REFLECT"],
            forced_chains=[0, 1],
            forced_rounds=2,
            permissive_chains=[],
            permissive_rounds=0,
            stage_cap_usd=0.45,
            git_sha_value=git_sha_value,
            gpu_name="L4",
        )
        # Resume to 4 rounds (simulates remote stop + relaunch)
        gen = generate_config.remote(
            SMOKE_ID,
            smoke_tag,
            protocols=["FORCED"],
            conditions=["SELF_REFLECT"],
            forced_chains=[0, 1],
            forced_rounds=4,
            permissive_chains=[],
            permissive_rounds=0,
            stage_cap_usd=0.45,
            git_sha_value=git_sha_value,
            gpu_name="L4",
        )
        if gen.get("state") == "failed":
            return {"state": "failed", "generate": gen}
        # Tiny real coding: ≤10 GPT Batch + ≤5 MiMo via canary coder restricted below
        checks = code_canary.remote(
            smoke_tag,
            SMOKE_ID,
            0.10,
            git_sha_value=git_sha_value,
            max_gpt=10,
            max_mimo=5,
            skip_canary_checks=True,
        )
        return {"state": "done", "generate": gen, "checks": checks}
    except Exception as exc:
        import sys

        sys.path.insert(0, f"{REMOTE_REPO}/src")
        from rc.phase7_status import write_status

        write_status(
            Path(REMOTE_RUNS) / smoke_tag / "STATUS.json",
            {
                "run_tag": smoke_tag,
                "stage": "orchestrate",
                "state": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": traceback.format_exc()[-4000:],
            },
        )
        runs_vol.commit()
        raise


@app.local_entrypoint()
def main(mode: str = "canary", rounds: int = 3, stage_cap_usd: float = 0.50) -> None:
    """mode=detach_test|canary|canary_d59|canary_code|budget_stop_test|smoke_d59"""
    from rc.budget import preflight, spent_modal_usd
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace, check_modal_hf_secret
    from rc.io_utils import git_sha

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    sha = git_sha(root) or ""

    if mode == "detach_test":
        # Smoke 2 chains × rounds is short; preflight wall-clock kept under stage $0.50.
        max_s = max(600, int(rounds) * 180)
        preflight(
            "L4",
            max_s,
            phase="7a",
            job_id=f"phase7a-detach-{rounds}",
            hard_cap_usd=spent_modal_usd(root) + 0.50,
            override_job_cap_usd=0.50,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        call = orchestrate_detach.spawn(rounds, stage_cap_usd, git_sha_value=sha)
        print(f"DETACH_TEST spawned object_id={call.object_id} rounds={rounds}")
    elif mode == "budget_stop_test":
        preflight(
            "L4",
            600,
            phase="7a",
            job_id="phase7a-budget-stop",
            hard_cap_usd=spent_modal_usd(root) + 0.50,
            override_job_cap_usd=0.50,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        call = orchestrate_detach.spawn(
            3, 0.01, git_sha_value=sha, run_tag=BUDGET_STOP_RUN_TAG
        )
        print(
            f"BUDGET_STOP_TEST spawned object_id={call.object_id} "
            f"run_tag={BUDGET_STOP_RUN_TAG} cap=0.01"
        )
    elif mode == "canary":
        preflight(
            "L4",
            20_000,
            phase="7a",
            job_id="phase7a-canary-olmo-final",
            hard_cap_usd=spent_modal_usd(root) + 8.0,
            override_job_cap_usd=8.0,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        call = orchestrate_canary.spawn(git_sha_value=sha)
        print(f"CANARY spawned object_id={call.object_id} run_tag={MAIN_RUN_TAG}")
        print(f"launch_time_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    elif mode == "canary_code":
        # Generation already on Volume; coding is CPU + API only.
        from rc.budget import spent_api_usd as _spent_api

        preflight(
            "L4",
            60,
            phase="7a",
            job_id="phase7a-canary-code-only",
            hard_cap_usd=spent_modal_usd(root) + 0.50,
            override_job_cap_usd=0.50,
            cpu_cores=2.0,
            memory_gib=8.0,
            root=root,
        )
        _ = _spent_api(root)  # ensure ledger readable
        call = orchestrate_canary.spawn(git_sha_value=sha, code_only=True)
        print(
            f"CANARY_CODE spawned object_id={call.object_id} run_tag={MAIN_RUN_TAG}"
        )
        print(f"launch_time_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    elif mode == "canary_d59":
        # D59: regenerate stale suffixes on main_v1 then code. Modal +$4; API residual.
        from rc.budget import spent_api_usd as _spent_api

        api_spent = _spent_api(root)
        api_cap = max(0.5, 6.0 - api_spent)
        preflight(
            "L4",
            12_000,  # sized so estimate ≤ $4 stage top-up
            phase="7a2",
            job_id="phase7a2-canary-d59",
            hard_cap_usd=spent_modal_usd(root) + 4.0,
            override_job_cap_usd=4.0,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        call = orchestrate_canary.spawn(
            git_sha_value=sha,
            code_only=False,
            stage_cap_usd=4.0,
            stage_api_cap_usd=api_cap,
            run_tag=MAIN_RUN_TAG,
        )
        print(f"CANARY_D59 spawned object_id={call.object_id} run_tag={MAIN_RUN_TAG}")
        print(f"stage_api_cap_usd={api_cap:.4f} (6.0 - spent {api_spent:.4f})")
        print(f"launch_time_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    elif mode == "smoke_d59":
        # Wall-clock prior sized so preflight estimate ≤ $0.50 (two short L4 legs).
        preflight(
            "L4",
            1400,
            phase="7a2",
            job_id="phase7a2-smoke-d59",
            hard_cap_usd=spent_modal_usd(root) + 0.50,
            override_job_cap_usd=0.50,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        call = orchestrate_smoke_d59.spawn(git_sha_value=sha)
        print(f"SMOKE_D59 spawned object_id={call.object_id}")
        print(f"launch_time_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    else:
        raise SystemExit(f"unknown mode {mode!r}")
