"""Phase 7B: one isolated Modal app per remaining main-run config (D62/D63).

Launch via scripts/launch_7b.py (detached). Each config owns STATUS_<config>.json
and budget/ledger_main_v1_<config>.jsonl on the Volume.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import modal

APP_NAME = "rc-phase7b"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
VLLM_VERSION = "0.30.0"
MAIN_RUN_TAG = "main_v1"
CANARY = "olmo3_7b_final"
SMOKE_ID = "qwen35_08b_smoke"

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
    # Budget ledgers for cross-app API guard also under Volume.
    budget_link = Path(REMOTE_REPO) / "budget"
    vol_budget = Path(REMOTE_RUNS) / MAIN_RUN_TAG / "budget"
    vol_budget.mkdir(parents=True, exist_ok=True)
    if budget_link.is_symlink() or budget_link.is_file():
        budget_link.unlink()
    elif budget_link.exists():
        # Keep image-local ledger.jsonl if present; merge via phase7b.sum_ledgers.
        pass
    else:
        budget_link.mkdir(parents=True, exist_ok=True)
    return Path(REMOTE_REPO)


def _status_path(config_id: str, run_tag: str = MAIN_RUN_TAG) -> Path:
    return Path(REMOTE_RUNS) / run_tag / f"STATUS_{config_id}.json"


def _write_cfg_status(config_id: str, *, run_tag: str = MAIN_RUN_TAG, **payload) -> None:
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from rc.phase7_status import write_status

    if config_id == CANARY and run_tag == MAIN_RUN_TAG:
        raise PermissionError("D63: refusing STATUS write for canary config")
    write_status(
        _status_path(config_id, run_tag),
        {"run_tag": run_tag, "config_id": config_id, **payload},
    )
    runs_vol.commit()


def _generate_impl(
    config_id: str,
    *,
    run_tag: str,
    protocols: list[str],
    conditions: list[str],
    forced_chains: list[int],
    forced_rounds: int,
    permissive_chains: list[int],
    permissive_rounds: int,
    stage_cap_usd: float,
    git_sha_value: str,
    gpu_name: str,
    parse_tripwire: bool = True,
) -> dict:
    import os
    import sys

    if config_id == CANARY and run_tag == MAIN_RUN_TAG:
        raise PermissionError("D63: canary tree is read-only on main_v1")

    os.environ.setdefault("HF_HOME", HF_CACHE)
    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from huggingface_hub import snapshot_download

    from rc.budget import estimate_modal_usd
    from rc.canary_checks import assert_canary_inputs
    from rc.chain_runner import Unit, run_config, verify_run_consistency
    from rc.config import load_vllm
    from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for
    from rc.phase7b import (
        count_protocol_unit_rounds,
        estimate_permissive_usd,
        forced_protocol_complete,
        parse_tripwire_stats,
        status_path,
    )

    assert_canary_inputs(root=root)

    started = time.perf_counter()
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

    n_units = max(len(units), 1)
    headroom_usd = estimate_modal_usd(
        gpu_name, 600, cpu_cores=4.0, memory_gib=16.0, root=root
    )
    round_usd_est = estimate_modal_usd(
        gpu_name, 120 * n_units, cpu_cores=4.0, memory_gib=16.0, root=root
    )

    def usd_so_far() -> float:
        return estimate_modal_usd(
            gpu_name,
            max(1, int(time.perf_counter() - started)),
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )

    if usd_so_far() + headroom_usd + round_usd_est > stage_cap_usd:
        _write_cfg_status(
            config_id,
            run_tag=run_tag,
            stage="generate",
            state="budget_stop",
            rounds_completed=0,
            rounds_total=rounds_total * n_units,
            usd_so_far=usd_so_far(),
            budget_stop_reason="pre_load_headroom",
        )
        return {"state": "budget_stop", "config_id": config_id}

    repo, rev = load_lock_revision(config_id, root=root)
    try:
        model_path = snapshot_download(
            repo_id=repo, revision=rev, cache_dir=HF_CACHE, local_files_only=True
        )
    except Exception:
        model_path = snapshot_download(
            repo_id=repo,
            revision=rev,
            cache_dir=HF_CACHE,
            token=os.environ.get("HF_TOKEN"),
        )
    vllm_cfg = load_vllm(root)
    max_len = max_model_len_for(config_id, root=root)
    if config_id == SMOKE_ID:
        max_len = min(4096, max_len)
    backend = VLLMBackend(
        config_id,
        model_path=model_path,
        revision=None,
        max_model_len=max_len,
        gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
        enforce_eager=False,
        max_num_seqs=vllm_cfg.max_num_seqs,
        root=root,
    )

    def _commit_and_status(t: int, protocol: str, n_rounds: int) -> None:
        runs_vol.commit()
        # Approximate unit-rounds completed
        done = t + 1
        _write_cfg_status(
            config_id,
            run_tag=run_tag,
            stage="generate",
            state="running",
            protocol=protocol,
            rounds_completed=done,
            rounds_total=n_rounds,
            usd_so_far=usd_so_far(),
        )
        if parse_tripwire and protocol == "FORCED" and t >= 3:
            # D65: gemma4_12b trips only on harness-frac; other configs keep D63 legacy.
            tw_mode = "harness_frac" if config_id == "gemma4_12b" else "legacy"
            stats = parse_tripwire_stats(
                run_tag, config_id, root=root, after_round=3, mode=tw_mode
            )
            if stats.get("trip"):
                out = (
                    Path(REMOTE_RUNS)
                    / run_tag
                    / config_id
                    / "_parse_hold_samples.json"
                )
                out.write_text(
                    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                _write_cfg_status(
                    config_id,
                    run_tag=run_tag,
                    stage="generate",
                    state="parse_hold",
                    rounds_completed=done,
                    rounds_total=n_rounds,
                    usd_so_far=usd_so_far(),
                    parse_tripwire=stats,
                )
                runs_vol.commit()
                raise RuntimeError("parse_hold")

    # FORCED first (skip entirely when already complete — D64 resume).
    if "FORCED" in protocols:
        forced_units = [u for u in units if u.protocol == "FORCED"]
        forced_done = forced_protocol_complete(
            run_tag,
            config_id,
            forced_chains=forced_chains,
            conditions=conditions,
            forced_rounds=forced_rounds,
            root=root,
        )
        n_forced_rows_before = count_protocol_unit_rounds(
            run_tag, config_id, "FORCED", root=root
        )
        if forced_done:
            # Resume: generate nothing for FORCED.
            n_forced_rows_after = count_protocol_unit_rounds(
                run_tag, config_id, "FORCED", root=root
            )
            if n_forced_rows_after != n_forced_rows_before:
                raise RuntimeError(
                    f"FORCED resume mutated rows: {n_forced_rows_before} -> {n_forced_rows_after}"
                )
            _write_cfg_status(
                config_id,
                run_tag=run_tag,
                stage="generate",
                state="running",
                protocol="FORCED",
                note="forced_complete_skip_resume",
                forced_rows=n_forced_rows_before,
                usd_so_far=usd_so_far(),
            )
        else:
            if usd_so_far() + round_usd_est > stage_cap_usd:
                _write_cfg_status(
                    config_id,
                    run_tag=run_tag,
                    stage="generate",
                    state="budget_stop",
                    usd_so_far=usd_so_far(),
                    budget_stop_reason="pre_forced",
                )
                return {"state": "budget_stop", "config_id": config_id}
            try:
                run_config(
                    backend,
                    config_id,
                    forced_units,
                    rounds=forced_rounds,
                    run_tag=run_tag,
                    root=root,
                    after_round_commit=lambda t: _commit_and_status(
                        t, "FORCED", forced_rounds
                    ),
                )
            except RuntimeError as exc:
                if "parse_hold" in str(exc):
                    return {"state": "parse_hold", "config_id": config_id}
                if "budget_stop" in str(exc):
                    return {"state": "budget_stop", "config_id": config_id}
                raise

    # Consistency gate after FORCED (incl. resume skip) before PERMISSIVE.
    gate_f = verify_run_consistency(run_tag, config_id, root=root)
    if not gate_f.get("ok"):
        _write_cfg_status(
            config_id,
            run_tag=run_tag,
            stage="generate",
            state="failed",
            error=f"consistency_after_forced n_failed={gate_f.get('n_failed')}",
        )
        runs_vol.commit()
        return {"state": "failed", "config_id": config_id, "gate": gate_f}

    # Global Modal projection check before PERMISSIVE — hold, do not drop (D64).
    if "PERMISSIVE" in protocols:
        forced_unit_rounds = max(
            count_protocol_unit_rounds(run_tag, config_id, "FORCED", root=root),
            len(forced_chains) * len(conditions) * max(forced_rounds, 1),
        )
        perm_unit_rounds = max(
            len(permissive_chains) * len(conditions) * max(permissive_rounds, 1), 1
        )
        # Prefer STATUS usd from completed FORCED (resume); else this container clock.
        forced_usd = usd_so_far()
        sp = status_path(run_tag, config_id, root=root)
        if sp.exists():
            try:
                prev = json.loads(sp.read_text(encoding="utf-8"))
                if prev.get("usd_so_far") is not None and prev.get("state") in {
                    "budget_hold",
                    "generate_done",
                    "running",
                }:
                    forced_usd = max(float(prev["usd_so_far"]), forced_usd)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        perm_est = estimate_permissive_usd(
            forced_modal_usd=forced_usd,
            forced_unit_rounds=forced_unit_rounds,
            permissive_unit_rounds=perm_unit_rounds,
        )
        if usd_so_far() + perm_est > stage_cap_usd:
            _write_cfg_status(
                config_id,
                run_tag=run_tag,
                stage="generate",
                state="budget_hold",
                usd_so_far=usd_so_far(),
                perm_est_usd=perm_est,
                forced_usd_for_est=forced_usd,
                forced_unit_rounds=forced_unit_rounds,
                perm_unit_rounds=perm_unit_rounds,
                note="before_permissive D64; human decides per prereg §3.4",
            )
            runs_vol.commit()
            return {"state": "budget_hold", "config_id": config_id}
        perm_units = [u for u in units if u.protocol == "PERMISSIVE"]
        run_config(
            backend,
            config_id,
            perm_units,
            rounds=permissive_rounds,
            run_tag=run_tag,
            root=root,
            after_round_commit=lambda t: _commit_and_status(
                t, "PERMISSIVE", permissive_rounds
            ),
        )
        gate_p = verify_run_consistency(run_tag, config_id, root=root)
        if not gate_p.get("ok"):
            _write_cfg_status(
                config_id,
                run_tag=run_tag,
                stage="generate",
                state="failed",
                error=f"consistency_after_permissive n_failed={gate_p.get('n_failed')}",
            )
            runs_vol.commit()
            return {"state": "failed", "config_id": config_id, "gate": gate_p}

    _write_cfg_status(
        config_id,
        run_tag=run_tag,
        stage="generate",
        state="generate_done",
        usd_so_far=usd_so_far(),
        rounds_completed=rounds_total,
        rounds_total=rounds_total,
    )
    runs_vol.commit()
    return {"state": "generate_done", "config_id": config_id, "usd_so_far": usd_so_far()}


def _gen_kwargs(
    config_id: str,
    *,
    run_tag: str,
    forced_rounds: int,
    permissive_rounds: int,
    forced_chains: list[int] | None,
    permissive_chains: list[int] | None,
    conditions: list[str] | None,
    stage_cap_usd: float,
    git_sha_value: str,
    parse_tripwire: bool,
    protocols: list[str] | None,
    gpu_name: str,
) -> dict:
    return dict(
        run_tag=run_tag,
        protocols=protocols or ["FORCED", "PERMISSIVE"],
        conditions=conditions
        or ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"],
        forced_chains=forced_chains if forced_chains is not None else list(range(25)),
        forced_rounds=forced_rounds,
        permissive_chains=permissive_chains
        if permissive_chains is not None
        else list(range(5)),
        permissive_rounds=permissive_rounds,
        stage_cap_usd=stage_cap_usd,
        git_sha_value=git_sha_value,
        gpu_name=gpu_name,
        parse_tripwire=parse_tripwire,
    )


@app.function(
    image=image,
    gpu="L4",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=86400,
    retries=3,
    scaledown_window=2,
    cpu=4,
    memory=16384,
)
def generate_l4(
    config_id: str,
    run_tag: str = MAIN_RUN_TAG,
    forced_rounds: int = 20,
    permissive_rounds: int = 10,
    forced_chains: list[int] | None = None,
    permissive_chains: list[int] | None = None,
    conditions: list[str] | None = None,
    stage_cap_usd: float = 15.0,
    git_sha_value: str = "",
    parse_tripwire: bool = True,
    protocols: list[str] | None = None,
) -> dict:
    return _generate_impl(
        config_id,
        **_gen_kwargs(
            config_id,
            run_tag=run_tag,
            forced_rounds=forced_rounds,
            permissive_rounds=permissive_rounds,
            forced_chains=forced_chains,
            permissive_chains=permissive_chains,
            conditions=conditions,
            stage_cap_usd=stage_cap_usd,
            git_sha_value=git_sha_value,
            parse_tripwire=parse_tripwire,
            protocols=protocols,
            gpu_name="L4",
        ),
    )


@app.function(
    image=image,
    gpu="L40S",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=86400,
    retries=3,
    scaledown_window=2,
    cpu=4,
    memory=16384,
)
def generate_l40s(
    config_id: str,
    run_tag: str = MAIN_RUN_TAG,
    forced_rounds: int = 20,
    permissive_rounds: int = 10,
    forced_chains: list[int] | None = None,
    permissive_chains: list[int] | None = None,
    conditions: list[str] | None = None,
    stage_cap_usd: float = 15.0,
    git_sha_value: str = "",
    parse_tripwire: bool = True,
    protocols: list[str] | None = None,
) -> dict:
    return _generate_impl(
        config_id,
        **_gen_kwargs(
            config_id,
            run_tag=run_tag,
            forced_rounds=forced_rounds,
            permissive_rounds=permissive_rounds,
            forced_chains=forced_chains,
            permissive_chains=permissive_chains,
            conditions=conditions,
            stage_cap_usd=stage_cap_usd,
            git_sha_value=git_sha_value,
            parse_tripwire=parse_tripwire,
            protocols=protocols,
            gpu_name="L40S",
        ),
    )


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=86400,
    retries=3,
    scaledown_window=2,
    cpu=4,
    memory=32768,
)
def generate_a100(
    config_id: str,
    run_tag: str = MAIN_RUN_TAG,
    forced_rounds: int = 20,
    permissive_rounds: int = 10,
    forced_chains: list[int] | None = None,
    permissive_chains: list[int] | None = None,
    conditions: list[str] | None = None,
    stage_cap_usd: float = 15.0,
    git_sha_value: str = "",
    parse_tripwire: bool = True,
    protocols: list[str] | None = None,
) -> dict:
    return _generate_impl(
        config_id,
        **_gen_kwargs(
            config_id,
            run_tag=run_tag,
            forced_rounds=forced_rounds,
            permissive_rounds=permissive_rounds,
            forced_chains=forced_chains,
            permissive_chains=permissive_chains,
            conditions=conditions,
            stage_cap_usd=stage_cap_usd,
            git_sha_value=git_sha_value,
            parse_tripwire=parse_tripwire,
            protocols=protocols,
            gpu_name="A100-80GB",
        ),
    )

@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("openai-key"),
        modal.Secret.from_name("openrouter-key"),
    ],
    timeout=86400,
    retries=3,
    cpu=2,
    memory=8192,
)
def code_config(
    config_id: str,
    run_tag: str = MAIN_RUN_TAG,
    stage_api_cap_usd: float = 10.0,
    git_sha_value: str = "",
    max_gpt: int | None = None,
    max_mimo: int | None = None,
) -> dict:
    """Consistency → GPT Batch (D60) → MiMo → integrity → C1/C3/C5."""
    import os
    import sys
    import traceback

    if git_sha_value:
        os.environ["RC_GIT_SHA"] = git_sha_value
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from rc.canary_checks import assert_canary_inputs, compute_canary_checks
    from rc.chain_runner import verify_run_consistency
    from rc.main_run_coding import (
        code_gpt54,
        code_mimo_subsample,
        extract_main_transitions,
        integrity_for_judge,
    )
    from rc.openai_batch import estimate_batch_usd
    from rc.phase7b import (
        CodingStatusHeartbeat,
        acquire_batch_submit_lock,
        api_submission_allowed,
        append_config_ledger,
        classify_openai_batch_error,
        release_batch_submit_lock,
        wait_for_provider_billing,
    )

    if config_id == CANARY and run_tag == MAIN_RUN_TAG:
        raise PermissionError("D63: refusing to code into canary path")

    assert_canary_inputs(root=root)
    coding_subdir = config_id

    def _st(**payload):
        _write_cfg_status(config_id, run_tag=run_tag, **payload)

    hb = CodingStatusHeartbeat(_st)
    hb.pulse("start", force=True)

    try:
        hb.pulse("consistency", force=True)
        gate = verify_run_consistency(run_tag, config_id, root=root)
        if not gate.get("ok"):
            _st(
                stage="coding",
                state="failed",
                error=f"consistency_gate n_failed={gate.get('n_failed')}",
            )
            raise RuntimeError("consistency_gate_failed")

        all_t = extract_main_transitions(run_tag, root=root)
        transitions = [t for t in all_t if t.get("config_id") == config_id]
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
            gpt_set = gpt_set[: int(max_gpt)]

        est = estimate_batch_usd(max(len(gpt_set), 1))
        ok, reason = api_submission_allowed(est, platform="openai", root=root)
        if not ok:
            # D62/D63/D67: project-cap guard is a hard hold — never auto-retried.
            _st(stage="coding", state="api_budget_hold", error=reason)
            runs_vol.commit()
            return {"state": "api_budget_hold", "reason": reason}

        acquire_batch_submit_lock(config_id, root=root)
        runs_vol.commit()

        job_id = f"phase7b-gpt54-{config_id}"
        gpt_rows = None
        gpt_meta = None
        last_err: Exception | None = None

        def _on_batch_progress(info: dict) -> None:
            sub = str(info.get("substage") or "batch_poll")
            hb.pulse(sub, batch_id=info.get("batch_id"), batch_status=info.get("batch_status"),
                     batch_completed=info.get("completed"), batch_total=info.get("total"),
                     sync_done=info.get("sync_done"), sync_total=info.get("sync_total"))

        try:
            for attempt in range(12):
                try:
                    hb.pulse("batch_poll", force=True, batch_attempt=attempt + 1)
                    gpt_rows, gpt_meta = code_gpt54(
                        gpt_set,
                        run_tag=run_tag,
                        root=root,
                        job_id=job_id,
                        coding_subdir=coding_subdir,
                        on_progress=_on_batch_progress,
                    )
                    last_err = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    kind = classify_openai_batch_error(exc)
                    if kind == "billing":
                        # D67: provider billing → api_billing_wait + probe; resume when OK.
                        def _billing_status(payload: dict) -> None:
                            _st(
                                stage="coding",
                                batch_attempt=attempt + 1,
                                **payload,
                            )
                            runs_vol.commit()

                        recovered = wait_for_provider_billing(
                            error=str(exc),
                            on_status=_billing_status,
                        )
                        if recovered:
                            acquire_batch_submit_lock(config_id, root=root)
                            continue
                        return {
                            "state": "api_billing_wait",
                            "error": str(exc)[:500],
                            "exhausted": True,
                        }
                    if kind == "rate_limit":
                        _st(
                            stage="coding",
                            state="api_wait",
                            error=str(exc)[:500],
                            batch_attempt=attempt + 1,
                        )
                        runs_vol.commit()
                        time.sleep(1800)
                        acquire_batch_submit_lock(config_id, root=root)
                        continue
                    _st(
                        stage="coding",
                        state="failed",
                        error=str(exc)[:500],
                        batch_attempt=attempt + 1,
                    )
                    runs_vol.commit()
                    raise
        finally:
            # D68: always release submit lock after Batch attempt path.
            release_batch_submit_lock(config_id, root=root)
            runs_vol.commit()

        if gpt_rows is None or gpt_meta is None:
            raise RuntimeError(f"OpenAI Batch exhausted 12 attempts: {last_err}")

        append_config_ledger(
            run_tag=run_tag,
            config_id=config_id,
            platform="openai",
            actual_usd=float(gpt_meta.get("api_usd") or 0),
            job_id=job_id,
            note=f"gpt54 batch_id={gpt_meta.get('batch_id')} n_batch={gpt_meta.get('n_batch')} n_sync={gpt_meta.get('n_sync')}",
            root=root,
        )

        skip_mimo = max_mimo is not None and int(max_mimo) <= 0
        if skip_mimo:
            mimo_rows, mimo_meta, n_miss = [], {"n": 0, "api_usd": 0.0, "skipped": True}, 0
        else:
            hb.pulse("mimo", force=True)

            def _run_mimo() -> tuple[list, dict, int]:
                if max_mimo is not None:
                    from rc.judging import judge_fate_batch
                    from rc.openrouter_backend import OpenRouterBackend

                    mimo_src = [
                        t
                        for t in transitions
                        if t.get("protocol") == "FORCED" and t.get("kind") == "per_round"
                    ][: int(max_mimo)]
                    for t in mimo_src:
                        t.setdefault("source", "pilot")
                        t.setdefault("rewrite", t.get("revised") or t.get("rewrite"))
                    backend = OpenRouterBackend(
                        "mimo_v26_pro",
                        work_dir=root
                        / "runs"
                        / run_tag
                        / "coding"
                        / coding_subdir
                        / "mimo_batch",
                        root=root,
                        job_id=f"phase7b-mimo-{config_id}",
                    )
                    rows = judge_fate_batch(
                        backend, "mimo_v26_pro", mimo_src, root=root, rubric_version="v2"
                    )
                    meta = {
                        "n": len(rows),
                        "api_usd": getattr(backend.last_cost, "usd", 0),
                    }
                    return rows, meta, 0
                return code_mimo_subsample(
                    [t for t in transitions if t.get("protocol") == "FORCED"],
                    run_tag=run_tag,
                    root=root,
                    job_id=f"phase7b-mimo-{config_id}",
                    config_id=config_id,
                    coding_subdir=coding_subdir,
                )

            # D63: MiMo — if provider unavailable >2 h, mimo_wait + hourly retries ≤24 h.
            mimo_started = time.time()
            mimo_rows = None
            mimo_meta = None
            n_miss = 0
            while True:
                try:
                    hb.pulse("mimo")
                    mimo_rows, mimo_meta, n_miss = _run_mimo()
                    break
                except Exception as exc:  # noqa: BLE001
                    elapsed = time.time() - mimo_started
                    text = str(exc).lower()
                    provider_down = any(
                        s in text
                        for s in (
                            "429",
                            "503",
                            "502",
                            "500",
                            "unavailable",
                            "no endpoints",
                            "provider",
                            "capacity",
                        )
                    )
                    if not provider_down:
                        raise
                    if elapsed < 7200:
                        hb.pulse("mimo")
                        time.sleep(min(300.0, 30.0 + elapsed / 10.0))
                        continue
                    if elapsed > 86400:
                        _st(
                            stage="coding",
                            state="failed",
                            error=f"mimo unavailable >24h: {exc}"[:500],
                        )
                        runs_vol.commit()
                        raise
                    _st(
                        stage="coding",
                        state="mimo_wait",
                        error=str(exc)[:500],
                        mimo_elapsed_s=elapsed,
                    )
                    runs_vol.commit()
                    time.sleep(3600)

            append_config_ledger(
                run_tag=run_tag,
                config_id=config_id,
                platform="openrouter",
                actual_usd=float(mimo_meta.get("api_usd") or 0),
                job_id=f"phase7b-mimo-{config_id}",
                note=f"mimo n={mimo_meta.get('n')}",
                root=root,
            )

        hb.pulse("checks", force=True)
        coding_base = root / "runs" / run_tag / "coding" / coding_subdir
        coding_base.mkdir(parents=True, exist_ok=True)
        gates_gpt = integrity_for_judge(
            gpt_set,
            gpt_rows,
            out_path=coding_base / "integrity_gpt54.json",
            root=root,
        )
        if skip_mimo or run_tag != MAIN_RUN_TAG:
            # Smoke / precheck: GPT Batch path only; skip full C1–C5 / MiMo gates.
            slim = {
                "smoke_or_precheck": True,
                "all_pass": bool(gates_gpt.get("ok")),
                "gates_gpt": gates_gpt,
                "gpt_meta": gpt_meta,
                "mimo_meta": mimo_meta,
            }
            out = root / "runs" / run_tag / config_id / "config_checks.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _st(
                stage="done",
                state="done" if slim["all_pass"] else "checks_fail",
                checks_pass=slim["all_pass"],
                batch_ids={"gpt54": gpt_meta.get("batch_id")},
                batch_state="done",
            )
            runs_vol.commit()
            return slim

        gates_mimo = integrity_for_judge(
            mimo_rows,
            mimo_rows,
            out_path=coding_base / "integrity_mimo.json",
            root=root,
        )
        checks = compute_canary_checks(
            root=root,
            run_tag=run_tag,
            config_id=config_id,
            gpt_meta=gpt_meta,
            mimo_meta=mimo_meta,
            gates_gpt=gates_gpt,
            gates_mimo=gates_mimo,
            api_spend=float(gpt_meta.get("api_usd") or 0)
            + float(mimo_meta.get("api_usd") or 0),
            stage_api_cap_usd=stage_api_cap_usd,
            n_mimo_missing=n_miss,
            modal_actual_usd=0.0,
        )
        # D65: C1 reported not gating; proceed on C3+C5 (technical success).
        slim = {
            "C1": {**checks["C1_subject_parsing"], "gating": False},
            "C3": checks["C3_judge_integrity"],
            "C5": checks["C5_storage"],
            "all_pass": bool(
                checks["C3_judge_integrity"]["pass"] and checks["C5_storage"]["pass"]
            ),
            "d65_c1_reported_not_gating": True,
            "gpt_meta": gpt_meta,
            "mimo_meta": mimo_meta,
        }
        out = root / "runs" / run_tag / config_id / "config_checks.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _st(
            stage="done",
            state="done" if slim["all_pass"] else "checks_fail",
            checks_pass=slim["all_pass"],
            batch_ids={"gpt54": gpt_meta.get("batch_id")},
            batch_state="done",
        )
        runs_vol.commit()
        return slim
    except Exception as exc:
        _st(
            stage="coding",
            state="failed",
            error=f"{type(exc).__name__}: {exc}"[:500],
            traceback=traceback.format_exc()[-2000:],
        )
        runs_vol.commit()
        raise


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("hf-token"),
        modal.Secret.from_name("openai-key"),
        modal.Secret.from_name("openrouter-key"),
    ],
    timeout=86400,
    retries=3,
)
def orchestrate_config(
    config_id: str,
    gpu_name: str,
    stage_cap_usd: float,
    stage_api_cap_usd: float = 10.0,
    git_sha_value: str = "",
    run_tag: str = MAIN_RUN_TAG,
    forced_rounds: int = 20,
    permissive_rounds: int = 10,
    forced_chains: list[int] | None = None,
    permissive_chains: list[int] | None = None,
    conditions: list[str] | None = None,
    protocols: list[str] | None = None,
    parse_tripwire: bool = True,
    code_only: bool = False,
    max_gpt: int | None = None,
    max_mimo: int | None = None,
) -> dict:
    """Full per-config pipeline: generate → consistency/code."""
    import sys
    import traceback

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from rc.canary_checks import assert_canary_inputs

    assert_canary_inputs(root=Path(REMOTE_REPO))
    gen_fn = {"L4": generate_l4, "L40S": generate_l40s, "A100-80GB": generate_a100}[
        gpu_name
    ]
    try:
        gen: dict | None = None
        if not code_only:
            gen = gen_fn.remote(
                config_id,
                run_tag=run_tag,
                forced_rounds=forced_rounds,
                permissive_rounds=permissive_rounds,
                forced_chains=forced_chains,
                permissive_chains=permissive_chains,
                conditions=conditions,
                protocols=protocols,
                stage_cap_usd=stage_cap_usd,
                git_sha_value=git_sha_value,
                parse_tripwire=parse_tripwire,
            )
            if gen.get("state") in {
                "budget_stop",
                "budget_hold",
                "parse_hold",
                "failed",
            }:
                return {"state": gen.get("state"), "generate": gen}
        checks = code_config.remote(
            config_id,
            run_tag=run_tag,
            stage_api_cap_usd=stage_api_cap_usd,
            git_sha_value=git_sha_value,
            max_gpt=max_gpt,
            max_mimo=max_mimo,
        )
        return {"state": "done", "generate": gen, "checks": checks}
    except Exception as exc:
        _write_cfg_status(
            config_id,
            run_tag=run_tag,
            stage="orchestrate",
            state="failed",
            error=f"{type(exc).__name__}: {exc}"[:500],
            traceback=traceback.format_exc()[-2000:],
        )
        runs_vol.commit()
        raise


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=600,
)
def verify_precheck(config_id: str, run_tag: str = "precheck_7b") -> dict:
    """Confirm parse, consistency, and (for qwen-think) reasoning storage."""
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    root = _link_runs()
    from rc.chain_runner import verify_run_consistency
    from rc.config import load_models
    from rc.generation import max_model_len_for

    gate = verify_run_consistency(run_tag, config_id, root=root)
    subject = load_models(root).by_id(config_id)
    max_len = max_model_len_for(config_id, root=root)
    reasoning_effort = (subject.chat_template_kwargs or {}).get("reasoning_effort")
    n_with_reasoning = 0
    n_ok = 0
    n_rows = 0
    base = root / "runs" / run_tag / config_id
    for rp in base.rglob("rounds.jsonl"):
        for line in rp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = __import__("json").loads(line)
            if int(row.get("round", -1)) < 1:
                continue
            n_rows += 1
            if row.get("parse_status") == "ok":
                n_ok += 1
            if (row.get("text_reasoning") or "").strip():
                n_with_reasoning += 1
    out = {
        "config_id": config_id,
        "consistency_ok": bool(gate.get("ok")),
        "max_model_len": max_len,
        "reasoning_effort": reasoning_effort,
        "n_gen_rows": n_rows,
        "n_parse_ok": n_ok,
        "n_with_reasoning": n_with_reasoning,
        "guided_json_ok": n_rows > 0 and n_ok == n_rows,
    }
    if config_id == "qwen38_27b_think":
        out["think_ok"] = (
            reasoning_effort == "medium" and n_with_reasoning > 0 and out["guided_json_ok"]
        )
        out["ok"] = bool(out["think_ok"] and out["consistency_ok"])
    else:
        out["ok"] = bool(out["guided_json_ok"] and out["consistency_ok"])
    return out


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=7200,
)
def download_weights(config_ids: list[str]) -> dict:
    import os
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    from huggingface_hub import snapshot_download

    from rc.generation import load_lock_revision

    out = {}
    for cid in config_ids:
        repo, rev = load_lock_revision(cid)
        snapshot_download(repo, revision=rev, token=os.environ.get("HF_TOKEN"))
        out[cid] = {"repo": repo, "revision": rev}
    return out


@app.local_entrypoint()
def main(
    mode: str = "config",
    config_id: str = "olmo3_7b_sft",
    stage_cap_usd: float = 15.0,
    detach: bool = True,
    code_only: bool = False,
) -> None:
    from rc.budget import preflight, spent_modal_usd
    from rc.config import repo_root
    from rc.guards import assert_modal_workspace, check_modal_hf_secret
    from rc.io_utils import git_sha
    from rc.phase7b import REMAINING_CONFIGS, SMOKE_ID, gpu_for_config

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    sha = git_sha(root) or ""
    if mode == "download":
        print(download_weights.remote(list(REMAINING_CONFIGS) + [SMOKE_ID]))
        return

    if mode == "smoke":
        # D23 L4 smoke: 1 chain × 2 conditions × 3 rounds → GPT Batch ≤6 reqs.
        # Budget ≤ $0.30 actual; preflight seconds sized so estimate ≤ cap.
        gpu = "L4"
        stage_cap_usd = min(stage_cap_usd, 0.30)
        preflight(
            gpu,
            900,
            phase="7b_smoke",
            job_id="phase7b-smoke",
            hard_cap_usd=spent_modal_usd(root) + stage_cap_usd,
            override_job_cap_usd=stage_cap_usd,
            cpu_cores=4.0,
            memory_gib=16.0,
            root=root,
        )
        result = orchestrate_config.remote(
            SMOKE_ID,
            gpu,
            stage_cap_usd,
            stage_api_cap_usd=0.25,
            git_sha_value=sha,
            run_tag="smoke_7b",
            forced_rounds=3,
            permissive_rounds=0,
            forced_chains=[0],
            permissive_chains=[],
            conditions=["SELF_REFLECT", "OTHER_REFLECT"],
            protocols=["FORCED"],
            parse_tripwire=False,
            max_gpt=6,
            max_mimo=0,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    if mode == "precheck":
        # A100 (qwen-think) + L40S (gemma4_12b): 2 rounds, 1 chain, run_tag=precheck_7b.
        # Total budget ≤ $2; preflight wall-clock sized so estimate ≤ per-job cap.
        budget_left = 2.0
        results = {}
        for cid, gpu in (
            ("qwen38_27b_think", "A100-80GB"),
            ("gemma4_12b", "L40S"),
        ):
            cap = min(1.0, budget_left)
            # ~15–20 min estimate window fits under $1 on A100/L40S.
            preflight_s = 1_200 if gpu == "A100-80GB" else 1_500
            preflight(
                gpu,
                preflight_s,
                phase="7b_precheck",
                job_id=f"phase7b-precheck-{cid}",
                hard_cap_usd=spent_modal_usd(root) + cap,
                override_job_cap_usd=cap,
                cpu_cores=4.0,
                memory_gib=32.0 if gpu == "A100-80GB" else 16.0,
                root=root,
            )
            gen_fn = {
                "L4": generate_l4,
                "L40S": generate_l40s,
                "A100-80GB": generate_a100,
            }[gpu]
            gen = gen_fn.remote(
                cid,
                run_tag="precheck_7b",
                forced_rounds=2,
                permissive_rounds=0,
                forced_chains=[0],
                permissive_chains=[],
                conditions=["SELF_REFLECT"],
                protocols=["FORCED"],
                stage_cap_usd=cap,
                git_sha_value=sha,
                parse_tripwire=False,
            )
            verify = verify_precheck.remote(cid, run_tag="precheck_7b")
            results[cid] = {"generate": gen, "gpu": gpu, "verify": verify}
            if not verify.get("ok"):
                print(json.dumps(results, indent=2, sort_keys=True, default=str))
                raise SystemExit(f"precheck FAILED for {cid}: {verify}")
            budget_left -= float((gen or {}).get("usd_so_far") or 0)
        print(json.dumps(results, indent=2, sort_keys=True, default=str))
        return

    gpu = gpu_for_config(config_id, root=root)
    preflight_s = 14_000 if gpu == "A100-80GB" else 20_000
    preflight(
        gpu,
        preflight_s,
        phase="7b",
        job_id=f"phase7b-{config_id}",
        hard_cap_usd=spent_modal_usd(root) + stage_cap_usd,
        override_job_cap_usd=stage_cap_usd,
        cpu_cores=4.0,
        memory_gib=16.0 if gpu != "A100-80GB" else 32.0,
        root=root,
    )
    if detach:
        call = orchestrate_config.spawn(
            config_id,
            gpu,
            stage_cap_usd,
            git_sha_value=sha,
            code_only=code_only,
        )
        print(
            f"ORCHESTRATE config={config_id} gpu={gpu} code_only={code_only} "
            f"object_id={call.object_id}"
        )
    else:
        result = orchestrate_config.remote(
            config_id,
            gpu,
            stage_cap_usd,
            git_sha_value=sha,
            code_only=code_only,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
