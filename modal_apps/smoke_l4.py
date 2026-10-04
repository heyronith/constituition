"""Modal L4 tiny-model smoke (D23). Same image, run_config, parsers as subject jobs."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import modal
from modal_apps.generate import (
    HF_CACHE,
    REMOTE_REPO,
    REMOTE_RUNS,
    app,
    hf_vol,
    image,
    runs_vol,
)

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
    units = [
        Unit("PERMISSIVE", cond, "STRUCTURED", 0)
        for cond in ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT")
    ]
    units.append(Unit("PERMISSIVE", "SELF_REFLECT", "FREE", 0))
    summary = run_config(
        backend, SMOKE_ID, units, rounds=1, run_tag="phase2b_l4_smoke", root=root
    )
    run_endorsement(
        backend, SMOKE_ID, reps=1, forms=("A", "B"), run_tag="phase2b_l4_smoke", root=root
    )
    run_realism_audit(backend, SMOKE_ID, reps=1, run_tag="phase2b_l4_smoke", root=root)
    marker = {
        "ok": True,
        "load_s": backend.load_s,
        "graph_capture_s": backend.graph_capture_s,
        "engine_init_s": time.perf_counter() - started,
        "summary": summary,
    }
    Path(REMOTE_RUNS, "phase2b_l4_smoke", "PASSED.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return marker


@app.local_entrypoint()
def smoke() -> None:
    from rc.budget import estimate_modal_usd, preflight, record_actual
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    max_seconds = 1200
    est = estimate_modal_usd("L4", max_seconds, cpu_cores=4.0, memory_gib=16.0, root=root)
    if est > 1.50:
        raise SystemExit(f"STOP: L4 smoke estimate ${est:.4f} > $1.50")
    preflight(
        "L4",
        max_seconds,
        phase="2b",
        job_id="phase2b-l4-smoke",
        platform="modal",
        override_job_cap_usd=1.50,
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
        record_actual(
            job_id="phase2b-l4-smoke",
            phase="2b",
            platform="modal",
            gpu="L4",
            max_seconds=max_seconds,
            actual_seconds=elapsed,
            est_usd=est,
            actual_usd=actual,
            note="code_failure",
            root=root,
        )
        raise SystemExit(f"code_failure: {exc}") from exc
    elapsed = time.perf_counter() - started
    actual = estimate_modal_usd("L4", int(elapsed) + 1, cpu_cores=4.0, memory_gib=16.0, root=root)
    record_actual(
        job_id="phase2b-l4-smoke",
        phase="2b",
        platform="modal",
        gpu="L4",
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=est,
        actual_usd=actual,
        note="l4 tiny-model smoke",
        root=root,
    )
    print(json.dumps({k: result[k] for k in ("ok", "load_s", "graph_capture_s") if k in result}))
