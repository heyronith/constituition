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

image = (
    modal.Image.debian_slim(python_version="3.11")
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
        }
    )
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
)


def _execute_dryrun(config_ids: list[str], gpu: str) -> dict:
    """Shared worker body (runs inside a GPU container)."""
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)

    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)

    from huggingface_hub import snapshot_download

    from rc.chain_runner import run_cell, run_endorsement, run_realism_audit
    from rc.config import load_models, load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for

    root = Path(REMOTE_REPO)
    load_models(root)
    vllm_cfg = load_vllm(root)
    conditions = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
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
        backend = VLLMBackend(
            engine_cid,
            model_path=model_path,
            revision=None,
            max_model_len=max_model_len_for(engine_cid, root),
            gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
            root=root,
        )
        load_s = time.perf_counter() - load_started

        for cid in cids:
            backend.config_id = cid
            job: dict = {
                "config_id": cid,
                "model_load_s": load_s,
                "cells": [],
                "endorsement": None,
                "realism": None,
            }
            for cond in conditions:
                job["cells"].append(
                    run_cell(
                        backend,
                        cid,
                        cond,
                        "STRUCTURED",
                        chain_indices=[0],
                        rounds=2,
                        run_tag="phase2_dryrun",
                        root=root,
                    )
                )
            if cid == "gemma4_12b":
                for cond in ("SELF_REFLECT", "PARAPHRASE"):
                    job["cells"].append(
                        run_cell(
                            backend,
                            cid,
                            cond,
                            "FREE",
                            chain_indices=[0],
                            rounds=2,
                            run_tag="phase2_dryrun",
                            root=root,
                        )
                    )
            run_endorsement(
                backend, cid, reps=1, forms=("A", "B"), run_tag="phase2_dryrun", root=root
            )
            job["endorsement"] = "ok"
            run_realism_audit(
                backend, cid, reps=3, run_tag="phase2_realism_audit", root=root
            )
            job["realism"] = "ok"
            summaries["jobs"].append(job)
            runs_vol.commit()

        del backend

    Path(REMOTE_RUNS, "phase2_dryrun_summary.json").write_text(
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
def run_l40s(config_ids: list[str]) -> dict:
    return _execute_dryrun(config_ids, "L40S")


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
def run_a100(config_ids: list[str]) -> dict:
    return _execute_dryrun(config_ids, "A100-80GB")


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
    from rc.config import load_models, repo_root
    from rc.guards import assert_modal_workspace, check_modal_hf_secret

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
    res = COMPUTE_RESERVATIONS[compute]

    timeouts = {
        "gemma4_12b": 1800,
        "qwen38_27b_nothink": 1500,
        "qwen38_27b_think": 2700,
        "gemma4_31b": 1800,
    }
    max_seconds = sum(timeouts.get(c, 1800) for c in config_ids)
    if set(config_ids) == {"qwen38_27b_nothink", "qwen38_27b_think"}:
        max_seconds = 3600

    job_id = "phase2-dryrun-" + "-".join(config_ids)
    est = estimate_modal_usd(
        gpu, max_seconds, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"], root=root
    )
    from rc.budget import gpu_price

    gpu_only = gpu_price(gpu, root) * max_seconds
    print(f"job={job_id} gpu={gpu} max_seconds={max_seconds}")
    print(f"estimate_full_usd=${est:.4f} estimate_gpu_only_usd=${gpu_only:.4f}")
    if est > 2.50:
        print(
            f"NOTE: full estimate ${est:.4f} exceeds $2.50 advisory "
            f"(GPU-only ${gpu_only:.4f}). See PHASE_2.md."
        )
        if gpu_only > 2.50:
            raise SystemExit(
                f"STOP: GPU-only estimate ${gpu_only:.4f} > $2.50; split the job."
            )

    try:
        preflight(
            gpu,
            max_seconds,
            phase=2,
            job_id=job_id,
            platform="modal",
            override_job_cap_usd=max(est + 0.5, 2.5),
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        )
    except BudgetExceeded as exc:
        raise SystemExit(f"preflight blocked: {exc}") from exc

    started = time.perf_counter()
    if gpu == "L40S":
        summary = run_l40s.with_options(timeout=max_seconds).remote(config_ids)
    else:
        summary = run_a100.with_options(timeout=max_seconds).remote(config_ids)
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
        phase=2,
        platform="modal",
        gpu=gpu,
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note=json.dumps({"configs": config_ids}),
        root=root,
    )
    print(json.dumps(summary, indent=2)[:4000])
    print(f"done elapsed_s={elapsed:.1f} actual_usd_est=${actual:.4f}")
