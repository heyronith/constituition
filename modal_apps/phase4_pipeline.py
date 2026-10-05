"""Phase 4 detached orchestrator: calib → D33 → pilot coding → power → G4.

Usage (Session 1, after gpt-oss-20b L4 smoke):
  uv run modal run --detach modal_apps/phase4_pipeline.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = "rc-phase4"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
PHASE4_DIR = f"{REMOTE_RUNS}/phase4"
VLLM_VERSION = "0.30.0"

JUDGE_GPU = {
    "gptoss_120b": "H100",
    "mistral_small32_24b": "A100-80GB",
    "nemotron3_nano_30b": "A100-80GB",
    "granite41_8b": "L40S",
}
JUDGE_COMPUTE = {
    "gptoss_120b": "modal_h100",
    "mistral_small32_24b": "modal_a100_80gb",
    "nemotron3_nano_30b": "modal_a100_80gb",
    "granite41_8b": "modal_l40s",
}

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
        "huggingface_hub>=0.26",
        "hf_transfer",
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
    )
    .env({"HF_HOME": HF_CACHE, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
    .add_local_file("pyproject.toml", remote_path=f"{REMOTE_REPO}/pyproject.toml")
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_remote_repo() -> Path:
    import os
    import shutil
    import sys

    os.environ.setdefault("HF_HOME", HF_CACHE)
    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = Path(REMOTE_REPO)
    # repo_root() requires pyproject.toml; ensure it exists even if mount lags.
    if not (root / "pyproject.toml").exists():
        (root / "pyproject.toml").write_text("[project]\nname='rc'\n", encoding="utf-8")
    runs_link = root / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)
    Path(PHASE4_DIR).mkdir(parents=True, exist_ok=True)
    return root


def _write_status(stage: str, state: str, **extra) -> dict:
    path = Path(PHASE4_DIR) / "STATUS.json"
    payload = {
        "stage": stage,
        "state": state,
        "timestamp_utc": _now(),
        **extra,
    }
    # Preserve spend if not provided.
    if path.exists() and "spend_usd" not in extra:
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            payload.setdefault("spend_usd", prev.get("spend_usd", 0.0))
        except json.JSONDecodeError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runs_vol.commit()
    return payload


def _append_pending_ledger(row: dict) -> None:
    path = Path(PHASE4_DIR) / "ledger_pending.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    runs_vol.commit()


def _estimate(gpu: str, seconds: int) -> float:
    from rc.budget import estimate_modal_usd
    from rc.compute_map import COMPUTE_RESERVATIONS

    key = {
        "H100": "modal_h100",
        "A100-80GB": "modal_a100_80gb",
        "L40S": "modal_l40s",
        "L4": "modal_l4",
        "cpu": "modal_l4",
    }.get(gpu, "modal_a100_80gb")
    res = COMPUTE_RESERVATIONS.get(key, {"cpu_cores": 8.0, "memory_gib": 64.0})
    if gpu == "cpu":
        return estimate_modal_usd("cpu", seconds, cpu_cores=4.0, memory_gib=8.0)
    return estimate_modal_usd(
        gpu, seconds, cpu_cores=res["cpu_cores"], memory_gib=res["memory_gib"]
    )


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 3,
    cpu=4,
    memory=8192,
)
def download_judge(repo_id: str, revision: str) -> dict:
    import os
    import time as time_mod

    from huggingface_hub import snapshot_download

    token = os.environ.get("HF_TOKEN")
    started = time_mod.perf_counter()
    path = snapshot_download(repo_id=repo_id, revision=revision, token=token, cache_dir=HF_CACHE)
    elapsed = time_mod.perf_counter() - started
    hf_vol.commit()
    return {"repo_id": repo_id, "revision": revision, "path": path, "seconds": elapsed}


@app.function(
    image=image,
    gpu="L4",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=1800,
    scaledown_window=2,
    cpu=8,
    memory=32768,
)
def smoke_gptoss20b(n_items: int = 20) -> dict:
    """D23: gpt-oss-20b MXFP4 on L4 through the judge code path."""
    import os

    root = _setup_remote_repo()
    from huggingface_hub import snapshot_download

    from rc.generation import VLLMBackend, load_lock_revision
    from rc.judging import judge_fate_batch, load_calibration_items

    repo_id, sha = load_lock_revision("gptoss_20b_smoke", root=root)
    token = os.environ.get("HF_TOKEN")
    model_path = snapshot_download(repo_id=repo_id, revision=sha, token=token, cache_dir=HF_CACHE)
    items = load_calibration_items(root=root)[:n_items]
    backend = VLLMBackend(
        "gptoss_20b_smoke",
        model_path=model_path,
        revision=sha,
        max_model_len=8192,
        enforce_eager=True,
        max_num_seqs=8,
        root=root,
    )
    rows = judge_fate_batch(backend, "gptoss_20b_smoke", items, root=root, seed_base=42)
    ok = sum(1 for r in rows if r.get("parse_status") == "ok")
    marker = Path(REMOTE_RUNS) / "phase4_gptoss20b_l4_smoke" / "PASSED.json"
    # Also write under repo runs symlink.
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok == len(rows),
        "n": len(rows),
        "n_ok": ok,
        "load_s": backend.load_s,
        "timestamp_utc": _now(),
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Mirror into PHASE4_DIR
    Path(PHASE4_DIR).mkdir(parents=True, exist_ok=True)
    (Path(PHASE4_DIR) / "gptoss20b_smoke.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return payload


def _run_judge_calib(judge_id: str, gpu: str) -> dict:
    import os

    root = _setup_remote_repo()
    from huggingface_hub import snapshot_download

    from rc.config import load_experiment
    from rc.generation import VLLMBackend, load_lock_revision
    from rc.guards import assert_gptoss_judge_smoke, assert_large_gpu_allowed
    from rc.judging import (
        judge_fate_batch,
        load_calibration_items,
        shuffle_items,
        write_judgment_rows,
    )

    assert_large_gpu_allowed(gpu, root=root)
    if judge_id == "gptoss_120b":
        assert_gptoss_judge_smoke(root=root)

    repo_id, sha = load_lock_revision(judge_id, root=root)
    token = os.environ.get("HF_TOKEN")
    model_path = snapshot_download(repo_id=repo_id, revision=sha, token=token, cache_dir=HF_CACHE)
    items = load_calibration_items(root=root)
    exp = load_experiment(root)
    items = shuffle_items(items, judge_id, exp.master_seed)
    backend = VLLMBackend(
        judge_id,
        model_path=model_path,
        revision=sha,
        max_model_len=8192 if judge_id.startswith("gptoss") else 16384,
        enforce_eager=judge_id.startswith("gptoss"),
        max_num_seqs=16,
        root=root,
    )
    rows = judge_fate_batch(backend, judge_id, items, root=root, seed_base=0)
    out = Path(PHASE4_DIR) / "calib" / f"{judge_id}.jsonl"
    write_judgment_rows(out, rows)
    meta = {
        "judge_id": judge_id,
        "n": len(rows),
        "n_ok": sum(1 for r in rows if r.get("parse_status") == "ok"),
        "load_s": backend.load_s,
        "gpu": gpu,
    }
    (Path(PHASE4_DIR) / "calib" / f"{judge_id}_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return meta


@app.function(
    image=image,
    gpu="H100",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    scaledown_window=2,
    cpu=8,
    memory=131072,
)
def calib_gptoss_120b() -> dict:
    return _run_judge_calib("gptoss_120b", "H100")


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def calib_mistral() -> dict:
    return _run_judge_calib("mistral_small32_24b", "A100-80GB")


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def calib_nemotron() -> dict:
    return _run_judge_calib("nemotron3_nano_30b", "A100-80GB")


@app.function(
    image=image,
    gpu="L40S",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    scaledown_window=2,
    cpu=8,
    memory=65536,
)
def calib_granite() -> dict:
    return _run_judge_calib("granite41_8b", "L40S")


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 30,
    cpu=2,
    memory=4096,
)
def select_d33() -> dict:
    _setup_remote_repo()
    from rc.judge_metrics import select_judges_d33

    per: dict[str, list] = {}
    calib_dir = Path(PHASE4_DIR) / "calib"
    for path in calib_dir.glob("*.jsonl"):
        jid = path.stem
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        per[jid] = rows
    selection = select_judges_d33(per)
    (Path(PHASE4_DIR) / "selection_d33.json").write_text(
        json.dumps(selection, indent=2, default=str) + "\n", encoding="utf-8"
    )
    metrics = {jid: selection["metrics"][jid] for jid in selection["metrics"]}
    (Path(PHASE4_DIR) / "calibration_metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return selection


def _run_pilot_coding_judge(judge_id: str, gpu: str, role: str) -> dict:
    """Generate raw judgments for one judge role over pilot transitions."""
    import os

    root = _setup_remote_repo()
    from huggingface_hub import snapshot_download

    from rc.generation import VLLMBackend, load_lock_revision
    from rc.guards import assert_gptoss_judge_smoke, assert_large_gpu_allowed
    from rc.judging import (
        judge_eval_awareness_batch,
        judge_fate_batch,
        structural_fate,
        write_judgment_rows,
    )
    from rc.pilot_coding import extract_pilot_notes, extract_pilot_transitions

    assert_large_gpu_allowed(gpu, root=root)
    if judge_id == "gptoss_120b":
        assert_gptoss_judge_smoke(root=root)

    # Pilot data must be on the volume under runs/pilot_v1.
    pilot = Path(REMOTE_RUNS) / "pilot_v1"
    if not pilot.exists():
        raise FileNotFoundError(f"pilot_v1 missing on volume at {pilot}")

    repo_id, sha = load_lock_revision(judge_id, root=root)
    token = os.environ.get("HF_TOKEN")
    model_path = snapshot_download(repo_id=repo_id, revision=sha, token=token, cache_dir=HF_CACHE)
    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = []
    for t in transitions:
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted"))) is None:
            llm_items.append(t)
    backend = VLLMBackend(
        judge_id,
        model_path=model_path,
        revision=sha,
        max_model_len=8192 if judge_id.startswith("gptoss") else 16384,
        enforce_eager=judge_id.startswith("gptoss"),
        max_num_seqs=16,
        root=root,
    )
    rows = judge_fate_batch(
        backend, judge_id, llm_items, root=root, seed_base=hash(role) % 10000
    )
    out = Path(PHASE4_DIR) / "coding" / f"{role}_{judge_id}.jsonl"
    write_judgment_rows(out, rows)
    meta = {"role": role, "judge_id": judge_id, "n": len(rows), "load_s": backend.load_s}
    if role == "j1":
        notes = extract_pilot_notes("pilot_v1", root=root)
        eval_rows = judge_eval_awareness_batch(
            backend, judge_id, notes, root=root, seed_base=9000
        )
        write_judgment_rows(Path(PHASE4_DIR) / "coding" / "eval_awareness.jsonl", eval_rows)
        meta["n_eval"] = len(eval_rows)
    (Path(PHASE4_DIR) / "coding" / f"{role}_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return meta


@app.function(
    image=image,
    gpu="H100",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    cpu=8,
    memory=131072,
)
def code_with_judge(judge_id: str, gpu: str, role: str) -> dict:
    return _run_pilot_coding_judge(judge_id, gpu, role)


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 30,
    cpu=2,
    memory=8192,
)
def finalize_coding(j1: str, j2: str, j3: str | None) -> dict:
    _setup_remote_repo()
    import csv

    from rc.judge_metrics import krippendorff_alpha_ordinal
    from rc.judging import fate_ordinal, normalize_fate, structural_fate
    from rc.pilot_coding import (
        category_appendix_rows,
        extract_pilot_transitions,
        resolve_disagreement,
    )

    transitions = extract_pilot_transitions("pilot_v1")
    coding_dir = Path(PHASE4_DIR) / "coding"

    def load_role(role: str, jid: str) -> dict[str, dict]:
        path = coding_dir / f"{role}_{jid}.jsonl"
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # Map by item_index order matching llm_items order.
        return {int(r["item_index"]): r for r in rows}

    j1_map = load_role("j1", j1)
    j2_map = load_role("j2", j2)
    j3_map = load_role("j3", j3) if j3 else {}

    llm_items = []
    structural = []
    for t in transitions:
        s = structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted")))
        if s is not None:
            structural.append(
                {
                    **t,
                    "fate": s.fate,
                    "strength": s.strength,
                    "structural": True,
                    "unresolved": False,
                }
            )
        else:
            llm_items.append(t)

    coded = list(structural)
    ratings = []
    unresolved = 0
    for i, src in enumerate(llm_items):
        a, b = j1_map[i], j2_map[i]
        c = j3_map.get(i)
        resolved = resolve_disagreement(a, b, c)
        if resolved["unresolved"]:
            unresolved += 1
        coded.append({**src, **resolved, "structural": False})
        ratings.append([fate_ordinal(a.get("fate")), fate_ordinal(b.get("fate"))])

    alpha = krippendorff_alpha_ordinal(ratings)
    eval_path = coding_dir / "eval_awareness.jsonl"
    eval_rows = (
        [
            json.loads(line)
            for line in eval_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if eval_path.exists()
        else []
    )

    from collections import Counter, defaultdict

    dist: dict[str, Counter] = defaultdict(Counter)
    for row in coded:
        dist[f"{row['protocol']}|{row['condition']}"][normalize_fate(row.get("fate")) or "?"] += 1
    eval_rate = {}
    by = defaultdict(list)
    for row in eval_rows:
        by[(row["config_id"], row["protocol"], row["condition"])].append(
            bool(row.get("eval_awareness"))
        )
    for key, vals in by.items():
        eval_rate["|".join(key)] = {"n": len(vals), "rate": sum(vals) / len(vals)}

    summary = {
        "j1": j1,
        "j2": j2,
        "j3": j3,
        "n_transitions": len(transitions),
        "n_structural": len(structural),
        "n_llm": len(llm_items),
        "j1_j2_alpha": alpha,
        "alpha_gate_pass": bool(alpha is not None and alpha >= 0.70),
        "unresolved_rate": unresolved / max(len(llm_items), 1),
        "unresolved_n": unresolved,
        "fate_distributions": {k: dict(v) for k, v in dist.items()},
        "eval_awareness_rates": eval_rate,
    }
    (Path(PHASE4_DIR) / "pilot_coding_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    coded_path = Path(PHASE4_DIR) / "pilot_v1_coding.jsonl"
    with coded_path.open("w", encoding="utf-8") as fh:
        for row in coded:
            # Drop bulky nested judge payloads if present.
            slim = {k: v for k, v in row.items() if k not in {"j1", "j2", "j3"}}
            fh.write(json.dumps(slim, sort_keys=True) + "\n")

    # Category appendix CSV into reports path on volume.
    appendix = Path(PHASE4_DIR) / "pilot_appendix_coding.csv"
    rows = category_appendix_rows(coded)
    if rows:
        with appendix.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    runs_vol.commit()
    return summary


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 20,
    cpu=1,
    memory=2048,
)
def power_sim_chunk(tasks: list[tuple[int, float, int]], hazard: dict, master_seed: int) -> list:
    _setup_remote_repo()
    from rc.power_analysis import run_power_tasks

    return run_power_tasks(tasks, hazard, master_seed)


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 60 * 3,
    cpu=2,
    memory=8192,
)
def run_power_and_g4(n_sims: int = 1000) -> dict:
    _setup_remote_repo()
    from rc.config import load_experiment
    from rc.cost_projection import project_main_run
    from rc.power_analysis import estimate_pilot_hazard

    coded_path = Path(PHASE4_DIR) / "pilot_v1_coding.jsonl"
    coded = [
        json.loads(line)
        for line in coded_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hazard = estimate_pilot_hazard(coded, run_tag="pilot_v1")
    (Path(PHASE4_DIR) / "hazard_estimates.json").write_text(
        json.dumps(hazard, indent=2) + "\n", encoding="utf-8"
    )

    n_values = (10, 15, 20, 25)
    hrs = (1.5, 2.0)
    tasks = [(n, hr, i) for n in n_values for hr in hrs for i in range(n_sims)]
    # Chunk for .map over ≥32 workers.
    chunk_size = max(1, len(tasks) // 64)
    chunks = [tasks[i : i + chunk_size] for i in range(0, len(tasks), chunk_size)]
    master_seed = load_experiment().master_seed
    results_nested = list(
        power_sim_chunk.map([(c, hazard, master_seed) for c in chunks], order_outputs=True)
    )
    flat = [r for chunk in results_nested for r in chunk]

    table = []
    idx = 0
    for n in n_values:
        for hr in hrs:
            chunk = flat[idx : idx + n_sims]
            idx += n_sims
            table.append(
                {
                    "n_chains": n,
                    "hr": hr,
                    "power_h1": sum(1 for r in chunk if r["h1"]) / n_sims,
                    "power_h2a": sum(1 for r in chunk if r["h2a"]) / n_sims,
                    "power_h2b": sum(1 for r in chunk if r["h2b"]) / n_sims,
                    "n_sims": n_sims,
                }
            )
    recommended = next(
        (row["n_chains"] for row in table if row["hr"] == 1.5 and row["power_h1"] >= 0.80),
        None,
    )
    power = {
        "baseline_hazard": hazard.get("agent_baseline_hazard"),
        "icc": hazard.get("icc"),
        "table": table,
        "recommended_n_hr15": recommended,
        "permissive_erosion_rate": hazard.get("permissive_erosion_rate"),
    }
    (Path(PHASE4_DIR) / "power_table.json").write_text(
        json.dumps(power, indent=2) + "\n", encoding="utf-8"
    )

    # Judging cost per transition from coding metas + ledger pending.
    judging_usd = None
    pending = Path(PHASE4_DIR) / "ledger_pending.jsonl"
    if pending.exists():
        rows = [
            json.loads(line)
            for line in pending.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        coding_cost = sum(
            float(r.get("actual_usd") or 0) for r in rows if "coding" in str(r.get("job_id", ""))
        )
        n_llm = max(1, sum(1 for r in coded if not r.get("structural")))
        # 2–3 judges per transition ≈ n_llm * 2.5 calls; use coding_cost / n_llm
        judging_usd = coding_cost / n_llm if n_llm else 0.00015
    g4 = project_main_run(judging_usd_per_transition=judging_usd)
    (Path(PHASE4_DIR) / "g4_projection.json").write_text(
        json.dumps(g4, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return {"power": power, "g4": g4}


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 12,
    cpu=2,
    memory=4096,
)
def orchestrate() -> dict:
    """Unattended Phase 4 stages 1–6."""
    root = _setup_remote_repo()
    from rc.budget import spent_modal_usd
    from rc.generation import load_lock_revision

    spend0 = spent_modal_usd(root)
    # Also count pending already on volume.
    pending_path = Path(PHASE4_DIR) / "ledger_pending.jsonl"
    pending_spend = 0.0
    if pending_path.exists():
        for line in pending_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("actual_usd") is not None:
                    pending_spend += float(row["actual_usd"])

    def spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return spend0 + extra

    _write_status("download", "running", spend_usd=spend_now())

    # Stage 1: parallel downloads
    repos = []
    for jid in JUDGE_GPU:
        repo_id, sha = load_lock_revision(jid, root=root)
        repos.append((repo_id, sha))
    handles = [download_judge.spawn(r, s) for r, s in repos]
    download_results = [h.get() for h in handles]
    for (repo_id, _), res in zip(repos, download_results, strict=True):
        _append_pending_ledger(
            {
                "timestamp_utc": _now(),
                "job_id": f"phase4-download-{repo_id.replace('/', '_')}",
                "phase": "4",
                "platform": "modal",
                "gpu": "cpu",
                "actual_seconds": res["seconds"],
                "actual_usd": _estimate("cpu", int(res["seconds"]) + 1),
                "note": "judge weight download",
            }
        )
    _write_status("download", "done", spend_usd=spend_now(), downloads=len(download_results))

    # Stage 2: calibration (sequential to keep spend predictable under $8)
    _write_status("calibration", "running", spend_usd=spend_now())
    calib_fns = [
        ("granite41_8b", "L40S", calib_granite),
        ("mistral_small32_24b", "A100-80GB", calib_mistral),
        ("nemotron3_nano_30b", "A100-80GB", calib_nemotron),
        ("gptoss_120b", "H100", calib_gptoss_120b),
    ]
    for jid, gpu, fn in calib_fns:
        # Soft preflight against cumulative $27 using pending spend.
        from rc.config import load_budget

        cap = load_budget().phase4_hard_cap_usd
        if spend_now() + 1.5 > cap:
            _write_status(
                "calibration",
                "stopped",
                reason=f"budget would exceed phase4 cap ${cap}",
                spend_usd=spend_now(),
            )
            return {"state": "stopped", "reason": "budget"}
        started = time.perf_counter()
        try:
            meta = fn.remote()
            elapsed = time.perf_counter() - started
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4-calib-{jid}",
                    "phase": "4",
                    "platform": "modal",
                    "gpu": gpu,
                    "actual_seconds": elapsed,
                    "actual_usd": _estimate(gpu, int(elapsed) + 1),
                    "note": f"ok | {meta}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4-calib-{jid}",
                    "phase": "4",
                    "platform": "modal",
                    "gpu": gpu,
                    "actual_seconds": elapsed,
                    "actual_usd": _estimate(gpu, int(elapsed) + 1),
                    "note": f"code_failure | {exc}",
                }
            )
            _write_status(
                "calibration",
                "stopped",
                reason=str(exc),
                spend_usd=spend_now(),
            )
            return {"state": "stopped", "reason": str(exc)}
    _write_status("calibration", "done", spend_usd=spend_now())

    # Stage 3: D33
    _write_status("selection", "running", spend_usd=spend_now())
    selection = select_d33.remote()
    if selection.get("stopped"):
        _write_status(
            "selection",
            "stopped",
            reason=selection.get("stop_reason"),
            spend_usd=spend_now(),
            selection=selection,
        )
        return {"state": "stopped", "reason": selection.get("stop_reason"), "selection": selection}
    j1, j2, j3 = selection["j1"], selection["j2"], selection.get("j3")
    _write_status("selection", "done", spend_usd=spend_now(), j1=j1, j2=j2, j3=j3)

    # Stage 4: pilot coding
    _write_status("coding", "running", spend_usd=spend_now())
    for role, jid in (("j1", j1), ("j2", j2), ("j3", j3)):
        if not jid:
            continue
        gpu = JUDGE_GPU[jid]
        started = time.perf_counter()
        try:
            meta = code_with_judge.remote(jid, gpu, role)
            elapsed = time.perf_counter() - started
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4-coding-{role}-{jid}",
                    "phase": "4",
                    "platform": "modal",
                    "gpu": gpu,
                    "actual_seconds": elapsed,
                    "actual_usd": _estimate(gpu, int(elapsed) + 1),
                    "note": f"ok | {meta}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4-coding-{role}-{jid}",
                    "phase": "4",
                    "platform": "modal",
                    "gpu": gpu,
                    "actual_seconds": elapsed,
                    "actual_usd": _estimate(gpu, int(elapsed) + 1),
                    "note": f"code_failure | {exc}",
                }
            )
            _write_status("coding", "stopped", reason=str(exc), spend_usd=spend_now())
            return {"state": "stopped", "reason": str(exc)}
    summary = finalize_coding.remote(j1, j2, j3)
    if not summary.get("alpha_gate_pass"):
        _write_status(
            "coding",
            "stopped",
            reason=f"pilot α={summary.get('j1_j2_alpha')} < 0.70",
            spend_usd=spend_now(),
            summary=summary,
        )
        return {"state": "stopped", "reason": "alpha_gate", "summary": summary}
    _write_status("coding", "done", spend_usd=spend_now(), alpha=summary.get("j1_j2_alpha"))

    # Stage 5–6: power + G4
    _write_status("power_g4", "running", spend_usd=spend_now())
    started = time.perf_counter()
    result = run_power_and_g4.remote(1000)
    elapsed = time.perf_counter() - started
    _append_pending_ledger(
        {
            "timestamp_utc": _now(),
            "job_id": "phase4-power-g4",
            "phase": "4",
            "platform": "modal",
            "gpu": "cpu",
            "actual_seconds": elapsed,
            "actual_usd": _estimate("cpu", int(elapsed) + 1),
            "note": "power sims + g4",
        }
    )
    _write_status(
        "done",
        "done",
        spend_usd=spend_now(),
        recommended_n=result.get("power", {}).get("recommended_n_hr15"),
    )
    return {"state": "done", "result": result}


@app.local_entrypoint()
def smoke() -> None:
    """Session-1 D23 gpt-oss-20b L4 smoke (wait for completion)."""
    from rc.budget import estimate_modal_usd, preflight, record_actual
    from rc.compute_map import COMPUTE_RESERVATIONS
    from rc.config import repo_root
    from rc.generation import load_lock_revision
    from rc.guards import assert_modal_workspace, check_modal_hf_secret

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    gpu = "L4"
    res = COMPUTE_RESERVATIONS.get("modal_l4", {"cpu_cores": 8.0, "memory_gib": 32.0})
    max_seconds = 1500
    job_id = "phase4-gptoss20b-l4-smoke"
    preflight(
        gpu,
        max_seconds,
        phase="4",
        job_id=job_id,
        platform="modal",
        override_job_cap_usd=2.0,
        cpu_cores=res["cpu_cores"],
        memory_gib=res["memory_gib"],
        root=root,
    )
    repo_id, sha = load_lock_revision("gptoss_20b_smoke", root)
    print(f"downloading smoke weights {repo_id}@{sha[:12]} …")
    download_judge.remote(repo_id, sha)
    started = time.perf_counter()
    try:
        summary = smoke_gptoss20b.remote(20)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        record_actual(
            job_id=job_id,
            phase="4",
            platform="modal",
            gpu=gpu,
            max_seconds=max_seconds,
            actual_seconds=elapsed,
            actual_usd=estimate_modal_usd(
                gpu,
                int(elapsed) + 1,
                cpu_cores=res["cpu_cores"],
                memory_gib=res["memory_gib"],
                root=root,
            ),
            note=f"code_failure | {exc}",
            root=root,
        )
        raise
    elapsed = time.perf_counter() - started
    record_actual(
        job_id=job_id,
        phase="4",
        platform="modal",
        gpu=gpu,
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        actual_usd=estimate_modal_usd(
            gpu,
            int(elapsed) + 1,
            cpu_cores=res["cpu_cores"],
            memory_gib=res["memory_gib"],
            root=root,
        ),
        note=f"ok | {summary}",
        root=root,
    )
    import subprocess

    dest = root / "runs" / "phase4_gptoss20b_l4_smoke"
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "modal",
            "volume",
            "get",
            "rc-runs",
            "phase4_gptoss20b_l4_smoke/PASSED.json",
            str(dest / "PASSED.json"),
            "--force",
        ],
        check=False,
    )
    if not summary.get("ok"):
        raise SystemExit(f"gpt-oss-20b smoke failed: {summary}")
    print("smoke PASSED", summary)


@app.local_entrypoint()
def main() -> None:
    """Detached orchestrator launcher. Use: modal run --detach modal_apps/phase4_pipeline.py"""
    import subprocess

    from rc.budget import spent_modal_usd
    from rc.config import load_budget, repo_root
    from rc.guards import (
        assert_modal_workspace,
        check_modal_hf_secret,
        gptoss_judge_smoke_marker,
    )
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    root = repo_root()
    if not gptoss_judge_smoke_marker(root).exists():
        raise SystemExit(
            "D23: run `modal run modal_apps/phase4_pipeline.py::smoke` before the H100 job"
        )

    pilot_local = root / "runs" / "pilot_v1"
    if pilot_local.exists():
        print("uploading pilot_v1 to rc-runs …")
        subprocess.check_call(
            [
                "modal",
                "volume",
                "put",
                "rc-runs",
                str(pilot_local),
                "pilot_v1",
                "--force",
            ]
        )

    remaining = load_budget(root).phase4_hard_cap_usd - spent_modal_usd(root)
    print(f"phase4 remaining ≈ ${remaining:.2f}; spawning orchestrate")
    print("git_sha", local_git_sha(root))
    handle = orchestrate.spawn()
    print(f"orchestrate spawned: {handle.object_id}")
    print("poll with: uv run python scripts/phase4_status.py")
