"""Modal GPU generation for Phase 2 dry run (and later pilots).

Local entrypoint: assert_modal_workspace → preflight → remote job → pull → record_actual.
Weights come from Volume rc-hf-cache (never downloaded on the GPU container).
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import modal

APP_NAME = "rc-generate"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
VLLM_VERSION = "0.30.0"

app = modal.App(APP_NAME)
hf_vol = modal.Volume.from_name(HF_VOLUME, create_if_missing=True)
runs_vol = modal.Volume.from_name(RUNS_VOLUME, create_if_missing=True)

# vLLM 0.30 flashinfer JIT needs nvcc. Use NVIDIA devel + pip vllm==0.30.0
# (same pin on Colab). CUDA 12.8 is within Modal host driver compatibility.
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
)


def _execute_dryrun(config_ids: list[str], gpu: str, git_sha_value: str = "") -> dict:
    """Shared worker body (runs inside a GPU container)."""
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)

    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)

    from huggingface_hub import snapshot_download

    from rc.chain_runner import Unit, run_config, run_endorsement, run_realism_audit
    from rc.config import load_models, load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for

    root = Path(REMOTE_REPO)
    load_models(root)
    vllm_cfg = load_vllm(root)
    summaries: dict = {"gpu": gpu, "config_ids": config_ids, "jobs": []}

    groups: dict[tuple[str, str], list[str]] = {}
    for cid in config_ids:
        repo, rev = load_lock_revision(cid, root)
        groups.setdefault((repo, rev), []).append(cid)

    for (repo, rev), cids in groups.items():
        model_path = snapshot_download(
            repo_id=repo,
            revision=rev,
            cache_dir=HF_CACHE,
            local_files_only=True,
        )
        engine_cid = "qwen38_27b_think" if "qwen38_27b_think" in cids else cids[0]
        load_started = time.perf_counter()
        max_seqs = 32 if engine_cid == "gemma4_31b" else vllm_cfg.max_num_seqs
        backend = VLLMBackend(
            engine_cid,
            model_path=model_path,
            revision=None,
            max_model_len=max_model_len_for(engine_cid, root),
            gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
            enforce_eager=False,
            max_num_seqs=max_seqs,
            root=root,
        )
        load_s = time.perf_counter() - load_started

        for cid in cids:
            backend.config_id = cid
            job: dict = {
                "config_id": cid,
                "model_load_s": getattr(backend, "load_s", load_s),
                "graph_capture_s": getattr(backend, "graph_capture_s", None),
                "cells": [],
                "endorsement": None,
                "realism": None,
            }
            units = [
                Unit(protocol, cond, "STRUCTURED", 0)
                for protocol in ("PERMISSIVE", "FORCED")
                for cond in (
                    "SELF_REFLECT",
                    "OTHER_REFLECT",
                    "PARAPHRASE",
                    "NEUTRAL_EDIT",
                )
            ]
            job["cells"].append(
                run_config(
                    backend,
                    cid,
                    units,
                    rounds=2,
                    run_tag="phase2b_dryrun",
                    root=root,
                )
            )
            runs_vol.commit()
            endorse_path = (
                Path(REMOTE_REPO) / "runs" / "phase2b_dryrun" / cid / "endorsement" / "calls.jsonl"
            )
            if endorse_path.exists() and endorse_path.stat().st_size > 0:
                job["endorsement"] = "skipped_existing"
            else:
                run_endorsement(
                    backend,
                    cid,
                    reps=1,
                    forms=("A", "B"),
                    run_tag="phase2b_dryrun",
                    root=root,
                )
                job["endorsement"] = "ok"
            runs_vol.commit()
            run_realism_audit(backend, cid, reps=3, run_tag="phase2b_realism_audit", root=root)
            job["realism"] = "ok"
            summaries["jobs"].append(job)
            runs_vol.commit()

        del backend

    Path(REMOTE_RUNS, "phase2b_dryrun_summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return summaries


@app.function(
    image=image,
    gpu="L40S",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=1800,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def run_l40s(config_ids: list[str], git_sha_value: str = "") -> dict:
    return _execute_dryrun(config_ids, "L40S", git_sha_value=git_sha_value)


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=3600,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def run_a100(config_ids: list[str], git_sha_value: str = "") -> dict:
    return _execute_dryrun(config_ids, "A100-80GB", git_sha_value=git_sha_value)


SMOKE_ID = "qwen35_08b_smoke"


@app.function(
    image=image,
    gpu="L4",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=1200,
    scaledown_window=2,
    cpu=4,
    memory=16384,
)
def run_l4_smoke(git_sha_value: str = "") -> dict:
    """D23 tiny-model end-to-end smoke. Same image/run_config/parsers as subjects."""
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)

    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)

    from huggingface_hub import snapshot_download

    from rc.chain_runner import (
        Unit,
        run_config,
        run_endorsement,
        run_realism_audit,
        run_schema_smoke_extras,
    )
    from rc.config import load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for

    root = Path(REMOTE_REPO)
    repo, rev = load_lock_revision(SMOKE_ID, root)
    model_path = snapshot_download(
        repo_id=repo, revision=rev, cache_dir=HF_CACHE, local_files_only=True
    )
    vllm_cfg = load_vllm(root)
    started = time.perf_counter()
    backend = VLLMBackend(
        SMOKE_ID,
        model_path=model_path,
        revision=None,
        max_model_len=min(4096, max_model_len_for(SMOKE_ID, root)),
        gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
        enforce_eager=False,
        max_num_seqs=vllm_cfg.max_num_seqs,
        root=root,
    )
    run_tag = "phase3_l4_smoke"
    units = [
        Unit("PERMISSIVE", cond, "STRUCTURED", 0)
        for cond in ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT")
    ]
    units.append(Unit("PERMISSIVE", "SELF_REFLECT", "FREE", 0))
    units.extend(
        Unit("FORCED", cond, "STRUCTURED", 0)
        for cond in ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT")
    )
    summary = run_config(backend, SMOKE_ID, units, rounds=1, run_tag=run_tag, root=root)
    run_endorsement(backend, SMOKE_ID, reps=1, forms=("A", "B"), run_tag=run_tag, root=root)
    run_realism_audit(backend, SMOKE_ID, reps=1, run_tag=run_tag, root=root)
    schema_extras = run_schema_smoke_extras(backend, SMOKE_ID, run_tag=run_tag, root=root)
    marker = {
        "ok": True,
        "load_s": backend.load_s,
        "graph_capture_s": backend.graph_capture_s,
        "engine_init_s": time.perf_counter() - started,
        "summary": summary,
        "guided_decoding": True,
        "schema_extras": schema_extras,
    }
    Path(REMOTE_RUNS, run_tag, "PASSED.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return marker


def _pull_volume(local_root: Path) -> None:
    import subprocess

    local_runs = local_root / "runs"
    local_runs.mkdir(parents=True, exist_ok=True)
    dest = local_runs / "_modal_pull"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    result = subprocess.run(
        ["modal", "volume", "get", RUNS_VOLUME, "/", str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"modal volume get failed: {result.stderr or result.stdout}")
    for child in dest.iterdir():
        target = local_runs / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))
    shutil.rmtree(dest, ignore_errors=True)


@app.local_entrypoint()
def main(*args: str) -> None:
    """Usage: modal run modal_apps/generate.py -- gemma4_12b"""
    from rc.budget import BudgetExceeded, estimate_modal_usd, preflight, record_actual
    from rc.compute_map import COMPUTE_RESERVATIONS, modal_gpu
    from rc.config import load_budget, load_models, repo_root
    from rc.guards import (
        assert_large_gpu_allowed,
        assert_modal_workspace,
        check_modal_hf_secret,
        l4_smoke_marker,
    )

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    models = load_models(root)

    config_ids = list(args) if args else ["gemma4_12b"]
    computes = {models.by_id(c).compute for c in config_ids}
    if len(computes) != 1:
        raise SystemExit(f"all configs in one job must share compute; got {computes}")
    compute = next(iter(computes))
    gpu = modal_gpu(compute)
    if gpu != "L4" and not l4_smoke_marker(root).exists():
        raise SystemExit(
            f"D23: run the Modal L4 tiny-model smoke first (missing {l4_smoke_marker(root)})."
        )
    assert_large_gpu_allowed(gpu, root=root)
    res = COMPUTE_RESERVATIONS[compute]

    timeouts = {
        "gemma4_12b": 1800,
        "qwen38_27b_nothink": 1500,
        "qwen38_27b_think": 2700,
        "gemma4_31b": 1800,
    }
    max_seconds = sum(timeouts.get(c, 1800) for c in config_ids)
    # Cap Modal jobs by remaining Phase 2/2B dry-run budget ($11 cumulative).
    from rc.budget import spent_modal_usd

    remaining = load_budget(root).phase2_dryrun_hard_cap_usd - spent_modal_usd(root)
    rate = estimate_modal_usd(
        gpu, 1, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"], root=root
    )
    # Leave a small buffer for ledger/pull overhead.
    budget_seconds = max(120, int((remaining - 0.05) / rate)) if remaining > 0.05 else 0
    if budget_seconds <= 0:
        raise SystemExit(f"STOP: no phase-2 budget remaining (spent leaves ${remaining:.4f})")
    job_seconds = max(60, int(1.50 / rate)) if rate > 0 else max_seconds
    if max_seconds > job_seconds:
        print(f"capping max_seconds {max_seconds} → {job_seconds} ($1.50 job threshold)")
        max_seconds = job_seconds
    if max_seconds > budget_seconds:
        print(
            f"capping max_seconds {max_seconds} → {budget_seconds} (budget left ${remaining:.2f})"
        )
        max_seconds = budget_seconds

    job_id = "phase2b-dryrun-" + "-".join(config_ids)
    est = estimate_modal_usd(
        gpu, max_seconds, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"], root=root
    )
    from rc.budget import gpu_price

    gpu_only = gpu_price(gpu, root) * max_seconds
    print(f"job={job_id} gpu={gpu} max_seconds={max_seconds}")
    print(f"estimate_full_usd=${est:.4f} estimate_gpu_only_usd=${gpu_only:.4f}")
    if est > 1.50:
        raise SystemExit(f"STOP: estimated ${est:.4f} > $1.50 per-job Phase 2B threshold.")

    try:
        preflight(
            gpu,
            max_seconds,
            phase="2b",
            job_id=job_id,
            platform="modal",
            override_job_cap_usd=1.50,
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        )
    except BudgetExceeded as exc:
        raise SystemExit(f"preflight blocked: {exc}") from exc

    from rc.io_utils import git_sha as local_git_sha

    sha = local_git_sha(root)
    started = time.perf_counter()
    try:
        if gpu == "L40S":
            summary = run_l40s.with_options(timeout=max_seconds).remote(config_ids, sha)
        else:
            summary = run_a100.with_options(timeout=max_seconds).remote(config_ids, sha)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        actual = estimate_modal_usd(
            gpu,
            int(elapsed) + 1,
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        )
        note = "timeout" if "timeout" in str(exc).lower() else "code_failure"
        try:
            _pull_volume(root)
        except Exception:
            pass
        record_actual(
            job_id=job_id,
            phase="2b",
            platform="modal",
            gpu=gpu,
            max_seconds=max_seconds,
            actual_seconds=elapsed,
            est_usd=est,
            actual_usd=actual,
            note=note,
            root=root,
        )
        raise SystemExit(f"{note}: {exc}") from exc
    elapsed = time.perf_counter() - started

    _pull_volume(root)
    actual = estimate_modal_usd(
        gpu,
        int(elapsed) + 1,
        cpu_cores=res["cpu_cores"],
        memory_gib=res["memory_gib"],
        root=root,
    )
    record_actual(
        job_id=job_id,
        phase="2b",
        platform="modal",
        gpu=gpu,
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note=f"ok | {json.dumps({'configs': config_ids, 'run_tag': 'phase2b_dryrun'})}",
        root=root,
    )
    print(json.dumps(summary, indent=2)[:4000])
    print(f"done elapsed_s={elapsed:.1f} actual_usd_est=${actual:.4f}")


@app.local_entrypoint()
def smoke() -> None:
    """D23 L4 tiny-model smoke with guided decoding.

    Usage: modal run modal_apps/generate.py::smoke
    """
    from rc.budget import estimate_modal_usd, preflight, record_actual
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    max_seconds = 1200
    est = estimate_modal_usd("L4", max_seconds, cpu_cores=4.0, memory_gib=16.0, root=root)
    if est > 2.50:
        raise SystemExit(f"STOP: L4 smoke estimate ${est:.4f} > $2.50")
    preflight(
        "L4",
        max_seconds,
        phase="3",
        job_id="phase3-l4-smoke",
        platform="modal",
        override_job_cap_usd=2.50,
        cpu_cores=4.0,
        memory_gib=16.0,
        root=root,
    )
    started = time.perf_counter()
    try:
        result = run_l4_smoke.with_options(timeout=max_seconds).remote(local_git_sha(root))
    except Exception as exc:
        elapsed = time.perf_counter() - started
        actual = estimate_modal_usd(
            "L4", int(elapsed) + 1, cpu_cores=4.0, memory_gib=16.0, root=root
        )
        note = "timeout" if "timeout" in str(exc).lower() else "code_failure"
        record_actual(
            job_id="phase3-l4-smoke",
            phase="3",
            platform="modal",
            gpu="L4",
            max_seconds=max_seconds,
            actual_seconds=elapsed,
            est_usd=est,
            actual_usd=actual,
            note=note,
            root=root,
        )
        raise SystemExit(f"{note}: {exc}") from exc
    elapsed = time.perf_counter() - started
    actual = estimate_modal_usd("L4", int(elapsed) + 1, cpu_cores=4.0, memory_gib=16.0, root=root)
    record_actual(
        job_id="phase3-l4-smoke",
        phase="3",
        platform="modal",
        gpu="L4",
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note="ok | phase3_l4_smoke guided_decoding",
        root=root,
    )
    marker_path = root / "runs" / "phase3_l4_smoke" / "PASSED.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("ok", "load_s", "graph_capture_s") if k in result}))


def _execute_pilot(config_ids: list[str], gpu: str, git_sha_value: str = "") -> dict:
    """Pilot generation: chains 100–102 × 10 rounds + endorsement + eval-awareness."""
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)

    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)

    from huggingface_hub import snapshot_download

    from rc.chain_runner import Unit, run_config, run_endorsement, run_eval_awareness
    from rc.config import load_models, load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for
    from rc.pilot import sample_eval_awareness_records

    root = Path(REMOTE_REPO)
    load_models(root)
    vllm_cfg = load_vllm(root)
    run_tag = "pilot_v1"
    chains = [100, 101, 102]
    conditions = ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT")
    summaries: dict = {"gpu": gpu, "config_ids": config_ids, "run_tag": run_tag, "jobs": []}

    for cid in config_ids:
        repo, rev = load_lock_revision(cid, root)
        model_path = snapshot_download(
            repo_id=repo, revision=rev, cache_dir=HF_CACHE, local_files_only=True
        )
        backend = VLLMBackend(
            cid,
            model_path=model_path,
            revision=None,
            max_model_len=max_model_len_for(cid, root),
            gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
            enforce_eager=False,
            max_num_seqs=vllm_cfg.max_num_seqs,
            root=root,
        )
        units = [
            Unit(protocol, cond, "STRUCTURED", chain)
            for protocol in ("PERMISSIVE", "FORCED")
            for cond in conditions
            for chain in chains
        ]
        cell = run_config(backend, cid, units, rounds=10, run_tag=run_tag, root=root)
        runs_vol.commit()
        run_endorsement(backend, cid, reps=5, forms=("A", "B"), run_tag=run_tag, root=root)
        runs_vol.commit()
        records = sample_eval_awareness_records(run_tag, cid, root=root, fraction=0.10)
        run_eval_awareness(backend, cid, records, run_tag=run_tag, root=root)
        runs_vol.commit()
        summaries["jobs"].append(
            {
                "config_id": cid,
                "cells": [cell],
                "n_eval_awareness": len(records),
                "model_load_s": backend.load_s,
                "graph_capture_s": backend.graph_capture_s,
            }
        )
        del backend

    Path(REMOTE_RUNS, "pilot_v1_summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return summaries


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=3600,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def run_pilot_a100(config_ids: list[str], git_sha_value: str = "") -> dict:
    return _execute_pilot(config_ids, "A100-80GB", git_sha_value=git_sha_value)


@app.local_entrypoint()
def pilot(*args: str) -> None:
    """Phase 3 pilot. Usage: modal run modal_apps/generate.py::pilot -- qwen38_27b_nothink"""
    from rc.budget import BudgetExceeded, estimate_modal_usd, preflight, record_actual
    from rc.compute_map import COMPUTE_RESERVATIONS, modal_gpu
    from rc.config import load_budget, load_models, repo_root
    from rc.guards import assert_large_gpu_allowed, assert_modal_workspace, check_modal_hf_secret
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    models = load_models(root)
    config_ids = list(args) if args else ["qwen38_27b_nothink"]
    computes = {models.by_id(c).compute for c in config_ids}
    if len(computes) != 1:
        raise SystemExit(f"all configs in one job must share compute; got {computes}")
    compute = next(iter(computes))
    gpu = modal_gpu(compute)
    assert_large_gpu_allowed(gpu, root=root)
    res = COMPUTE_RESERVATIONS[compute]

    from rc.budget import spent_modal_usd

    remaining = load_budget(root).phase3_hard_cap_usd - spent_modal_usd(root)
    rate = estimate_modal_usd(
        gpu, 1, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"], root=root
    )
    budget_seconds = max(120, int((remaining - 0.05) / rate)) if remaining > 0.05 else 0
    if budget_seconds <= 0:
        raise SystemExit(f"STOP: no phase-3 budget remaining (${remaining:.4f})")
    job_seconds = max(60, int(2.50 / rate)) if rate > 0 else 3600
    max_seconds = min(3600, job_seconds, budget_seconds)
    job_id = "phase3-pilot-" + "-".join(config_ids)
    est = estimate_modal_usd(
        gpu, max_seconds, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"], root=root
    )
    print(f"job={job_id} gpu={gpu} max_seconds={max_seconds} est=${est:.4f}")
    if est > 2.50:
        raise SystemExit(f"STOP: estimated ${est:.4f} > $2.50 per-job Phase 3 threshold.")
    try:
        preflight(
            gpu,
            max_seconds,
            phase="3",
            job_id=job_id,
            platform="modal",
            override_job_cap_usd=2.50,
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        )
    except BudgetExceeded as exc:
        raise SystemExit(f"preflight blocked: {exc}") from exc

    started = time.perf_counter()
    try:
        summary = run_pilot_a100.with_options(timeout=max_seconds).remote(
            config_ids, local_git_sha(root)
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        actual = estimate_modal_usd(
            gpu,
            int(elapsed) + 1,
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        )
        note = "timeout" if "timeout" in str(exc).lower() else "code_failure"
        try:
            _pull_volume(root)
        except Exception:
            pass
        record_actual(
            job_id=job_id,
            phase="3",
            platform="modal",
            gpu=gpu,
            max_seconds=max_seconds,
            actual_seconds=elapsed,
            est_usd=est,
            actual_usd=actual,
            note=note,
            root=root,
        )
        raise SystemExit(f"{note}: {exc}") from exc
    elapsed = time.perf_counter() - started
    _pull_volume(root)
    actual = estimate_modal_usd(
        gpu,
        int(elapsed) + 1,
        cpu_cores=res["cpu_cores"],
        memory_gib=res["memory_gib"],
        root=root,
    )
    record_actual(
        job_id=job_id,
        phase="3",
        platform="modal",
        gpu=gpu,
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note=f"ok | {json.dumps({'configs': config_ids, 'run_tag': 'pilot_v1'})}",
        root=root,
    )
    print(json.dumps(summary, indent=2)[:4000])
    print(f"done elapsed_s={elapsed:.1f} actual_usd_est=${actual:.4f}")
