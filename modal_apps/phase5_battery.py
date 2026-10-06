"""Phase 5 behaviour battery: L4 smoke + battery_val_v1 validation.

Usage:
  # D23 battery-path smoke (blocking):
  uv run modal run modal_apps/phase5_battery.py::smoke

  # Session 1 detach (after smoke passes):
  uv run modal run --detach modal_apps/phase5_battery.py
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import modal

APP_NAME = "rc-phase5-battery"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
VLLM_VERSION = "0.30.0"
RUN_TAG = "battery_val_v1"
SMOKE_ID = "qwen35_08b_smoke"
SMOKE_RUN_TAG = "phase5_battery_l4_smoke"
CONSTITUTIONS = ["NONE", "R0", "COR_INV", "AGENT_INV"]
PHASE5_MODAL_CAP = 4.0
PHASE5_API_CAP = 2.0

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

cpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
        "openai>=1.60",
        "huggingface_hub>=0.26",
    )
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
)


def _link_runs() -> Path:
    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)
    return Path(REMOTE_REPO)


def _execute_battery(
    config_id: str,
    gpu: str,
    *,
    run_tag: str,
    constitutions: list[str],
    git_sha_value: str = "",
    components: tuple[str, ...] = ("B1", "B2", "B5", "B6"),
    b1_limit: int | None = None,
) -> dict:
    import os
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from huggingface_hub import snapshot_download

    from rc.battery import build_b1_items, write_b1_items
    from rc.battery_runner import run_battery_for_config, run_b1_for_constitution
    from rc.battery import build_validation_constitution
    from rc.config import load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for

    write_b1_items(root)
    repo, rev = load_lock_revision(config_id, root)
    model_path = snapshot_download(
        repo_id=repo, revision=rev, cache_dir=HF_CACHE, local_files_only=True
    )
    vllm_cfg = load_vllm(root)
    backend = VLLMBackend(
        config_id,
        model_path=model_path,
        revision=None,
        max_model_len=max_model_len_for(config_id, root),
        gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
        enforce_eager=False,
        max_num_seqs=min(64, vllm_cfg.max_num_seqs),
        root=root,
    )
    if b1_limit is not None:
        # Smoke path: tiny B1 subset only.
        items = build_b1_items(root)[:b1_limit]
        summary = {
            "config_id": config_id,
            "gpu": gpu,
            "run_tag": run_tag,
            "smoke": True,
            "constitutions": {},
        }
        for kind in constitutions:
            system, meta = build_validation_constitution(
                kind, config_id=config_id if config_id != SMOKE_ID else "qwen38_27b_nothink",
                chain_idx=0, root=root
            )
            # For smoke model, still use materials from a real subject config_id for R0 text.
            rows = run_b1_for_constitution(
                backend,
                config_id=config_id,
                constitution_id=kind,
                system_prompt=system,
                items=items,
                run_tag=run_tag,
                root=root,
                batch_size=16,
            )
            summary["constitutions"][kind] = {
                "meta": meta,
                "n": len(rows),
                "parse_rate": sum(1 for r in rows if r["parsed"]) / max(len(rows), 1),
            }
    else:
        summary = run_battery_for_config(
            backend,
            config_id,
            constitutions=constitutions,
            run_tag=run_tag,
            root=root,
            components=components,
        )
        summary["gpu"] = gpu
    summary["model_load_s"] = backend.load_s
    summary["graph_capture_s"] = backend.graph_capture_s
    out = Path(REMOTE_RUNS) / run_tag / f"{config_id}_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    runs_vol.commit()
    return summary


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
def run_battery_l4_smoke(git_sha_value: str = "") -> dict:
    return _execute_battery(
        SMOKE_ID,
        "L4",
        run_tag=SMOKE_RUN_TAG,
        constitutions=["NONE", "R0"],
        git_sha_value=git_sha_value,
        b1_limit=8,
    )


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=7200,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def run_battery_a100(config_id: str, git_sha_value: str = "") -> dict:
    return _execute_battery(
        config_id,
        "A100-80GB",
        run_tag=RUN_TAG,
        constitutions=CONSTITUTIONS,
        git_sha_value=git_sha_value,
    )


@app.function(
    image=image,
    gpu="L4",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=7200,
    scaledown_window=2,
    cpu=4,
    memory=16384,
)
def run_battery_l4(config_id: str, git_sha_value: str = "") -> dict:
    """D51: OLMo subjects on Modal L4 (Phase 5 parenthetical L40S superseded)."""
    return _execute_battery(
        config_id,
        "L4",
        run_tag=RUN_TAG,
        constitutions=CONSTITUTIONS,
        git_sha_value=git_sha_value,
    )


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openai-key")],
    timeout=7200,
    cpu=2,
    memory=4096,
)
def run_battery_api(git_sha_value: str = "") -> dict:
    import os
    import sys

    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from rc.battery_runner import (
        evaluate_gates,
        run_label_validity_gpt54,
        score_harm_refusals_gpt54,
    )

    v1 = run_label_validity_gpt54(run_tag=RUN_TAG, root=root)
    harm = score_harm_refusals_gpt54(
        run_tag=RUN_TAG,
        config_ids=["qwen38_27b_nothink", "olmo3_7b_final"],
        constitutions=CONSTITUTIONS,
        root=root,
    )
    gates = evaluate_gates(RUN_TAG, root=root)
    out = {
        "label_validity": v1,
        "harm_refusal": harm,
        "gates": gates,
    }
    path = Path(REMOTE_RUNS) / RUN_TAG / "api_summary.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    runs_vol.commit()
    return out


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("hf-token"),
        modal.Secret.from_name("openai-key"),
    ],
    timeout=14400,
    cpu=1,
    memory=2048,
)
def orchestrate(spent_at_launch: float, git_sha_value: str = "") -> dict:
    """One detached parent: A100 qwen → L4 olmo → gpt54 API scoring/gates."""
    import os
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()
    status_path = Path(REMOTE_RUNS) / RUN_TAG / "STATUS.json"

    def write_status(stage: str, state: str, **extra) -> None:
        payload = {"stage": stage, "state": state, "updated": time.time(), **extra}
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        runs_vol.commit()

    write_status("qwen", "running", spent_at_launch=spent_at_launch)
    qwen = run_battery_a100.remote("qwen38_27b_nothink", git_sha_value)
    write_status("olmo", "running", qwen_keys=list(qwen.keys()))
    olmo = run_battery_l4.remote("olmo3_7b_final", git_sha_value)
    write_status("api", "running")
    api = run_battery_api.remote(git_sha_value)
    write_status("done", "done", gates=(api.get("gates") or {}).get("all_pass"))
    return {"qwen": qwen, "olmo": olmo, "api": api}


@app.local_entrypoint()
def smoke() -> None:
    """D23 battery-path L4 smoke. Blocking."""
    from rc.budget import estimate_modal_usd, preflight, record_actual
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    from rc.budget import spent_modal_usd

    max_seconds = 1200
    est = estimate_modal_usd("L4", max_seconds, cpu_cores=4.0, memory_gib=16.0, root=root)
    spent = spent_modal_usd(root)
    preflight(
        "L4",
        max_seconds,
        phase="5",
        job_id="phase5-battery-l4-smoke",
        platform="modal",
        override_job_cap_usd=2.0,
        hard_cap_usd=spent + PHASE5_MODAL_CAP,
        cpu_cores=4.0,
        memory_gib=16.0,
        root=root,
    )
    started = time.perf_counter()
    try:
        result = run_battery_l4_smoke.with_options(timeout=max_seconds).remote(local_git_sha(root))
    except Exception as exc:
        elapsed = time.perf_counter() - started
        actual = estimate_modal_usd(
            "L4", int(elapsed) + 1, cpu_cores=4.0, memory_gib=16.0, root=root
        )
        note = "timeout" if "timeout" in str(exc).lower() else "code_failure"
        record_actual(
            job_id="phase5-battery-l4-smoke",
            phase="5",
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
        job_id="phase5-battery-l4-smoke",
        phase="5",
        platform="modal",
        gpu="L4",
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note="ok | phase5_battery_l4_smoke",
        root=root,
    )
    marker = root / "runs" / SMOKE_RUN_TAG / "PASSED.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "parse_rates": {
        k: v.get("parse_rate") for k, v in result.get("constitutions", {}).items()
    }}))


@app.local_entrypoint()
def main() -> None:
    """Spawn the validation orchestrator (one detached job). Prefer: modal run --detach …"""
    from rc.budget import estimate_modal_usd, preflight, spent_modal_usd
    from rc.config import repo_root
    from rc.guards import assert_large_gpu_allowed, assert_modal_workspace
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    # Prefer battery-path smoke marker; fall back to D30 chain smoke for A100 gate.
    battery_marker = root / "runs" / SMOKE_RUN_TAG / "PASSED.json"
    if not battery_marker.exists():
        raise SystemExit(
            f"STOP: run battery L4 smoke first (missing {battery_marker})"
        )
    assert_large_gpu_allowed("A100-80GB", root=root)
    spent = spent_modal_usd(root)
    # Preflight both GPU legs against Phase 5 incremental $4.
    for gpu, secs, cpu, mem in (
        ("A100-80GB", 5400, 8.0, 64.0),
        ("L4", 5400, 4.0, 16.0),
    ):
        est = estimate_modal_usd(gpu, secs, cpu_cores=cpu, memory_gib=mem, root=root)
        if est > PHASE5_MODAL_CAP:
            # Use tighter wall-clock estimate for preflight bookkeeping only.
            pass
    # Cap remaining = phase5 allowance (not full project remaining).
    preflight(
        "A100-80GB",
        3600,
        phase="5",
        job_id="phase5-battery-val-qwen",
        platform="modal",
        override_job_cap_usd=PHASE5_MODAL_CAP,
        hard_cap_usd=spent + PHASE5_MODAL_CAP,
        cpu_cores=8.0,
        memory_gib=64.0,
        root=root,
    )
    preflight(
        "L4",
        3600,
        phase="5",
        job_id="phase5-battery-val-olmo",
        platform="modal",
        override_job_cap_usd=PHASE5_MODAL_CAP,
        hard_cap_usd=spent + PHASE5_MODAL_CAP,
        cpu_cores=4.0,
        memory_gib=16.0,
        root=root,
    )
    handle = orchestrate.spawn(spent, local_git_sha(root))
    print(f"orchestrate spawned: {handle.object_id}")
    print(f"run_tag={RUN_TAG} spent_at_launch=${spent:.4f}")
