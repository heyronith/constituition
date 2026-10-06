"""Phase 4F detached orchestrator: rubric v2, calib_v3, pilot_v3, D44, power, G4.

Usage (Session 1, after human approves Modal $32 / API $15):
  uv run modal run --detach modal_apps/phase4f_pipeline.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import modal

APP_NAME = "rc-phase4f"
HF_VOLUME = "rc-hf-cache"
RUNS_VOLUME = "rc-runs"
HF_CACHE = "/hf-cache"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"
PHASE4_DIR = f"{REMOTE_RUNS}/phase4"
CALIB_V3_DIR = f"{PHASE4_DIR}/calib_v3"
CALIB_RUN_TAG = "judge_calib_v3"
CODING_V3_DIR = f"{PHASE4_DIR}/coding_v3"
CODING_RUN_TAG = "pilot_v1_coding_v3"
VLLM_VERSION = "0.30.0"

# D43 candidates (granite dropped; sonnet55 dropped).
CANDIDATES = ("mistral_small32_24b", "gptoss_120b", "gpt54")
JUDGE_GPU = {
    "gptoss_120b": "H100",
    "mistral_small32_24b": "A100-80GB",
    "gpt54": "api",
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
        "mistral_common>=1.6.2",
        "openai>=1.60",
    )
    .pip_install("transformers==5.16.1")
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
        "openai>=1.60",
        "httpx>=0.27",
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
    path = Path(PHASE4_DIR) / "STATUS_4f.json"
    payload = {"stage": stage, "state": state, "timestamp_utc": _now(), **extra}
    if path.exists() and "spend_usd" not in extra:
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            payload.setdefault("spend_usd", prev.get("spend_usd", 0.0))
            payload.setdefault("api_spend_usd", prev.get("api_spend_usd", 0.0))
        except json.JSONDecodeError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runs_vol.commit()
    return payload


def _append_pending_ledger(row: dict) -> None:
    active = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"
    active.parent.mkdir(parents=True, exist_ok=True)
    with active.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    runs_vol.commit()


def _estimate(gpu: str, seconds: int) -> float:
    from rc.budget import estimate_modal_usd

    return estimate_modal_usd(gpu, seconds)


def _run_open_weight_judge(
    judge_id: str,
    gpu: str,
    *,
    items: list,
    out_path: Path,
    seed_base: int = 0,
    source: str | None = None,
    shuffle: bool = False,
    shuffle_seed: int | None = None,
) -> dict:
    import os

    root = _setup_remote_repo()
    from huggingface_hub import snapshot_download

    from rc.generation import VLLMBackend, load_lock_revision
    from rc.guards import assert_gptoss_judge_smoke, assert_large_gpu_allowed
    from rc.judging import judge_fate_batch, write_judgment_rows

    assert_large_gpu_allowed(gpu, root=root)
    if judge_id == "gptoss_120b":
        assert_gptoss_judge_smoke(root=root)

    repo_id, sha = load_lock_revision(judge_id, root=root)
    token = os.environ.get("HF_TOKEN")
    model_path = snapshot_download(repo_id=repo_id, revision=sha, token=token, cache_dir=HF_CACHE)
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
        backend,
        judge_id,
        items,
        root=root,
        seed_base=seed_base,
        source=source,
        shuffle=shuffle,
        shuffle_seed=shuffle_seed,
        rubric_version="v2",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_judgment_rows(out_path, rows)
    return {
        "judge_id": judge_id,
        "n": len(rows),
        "n_ok": sum(1 for r in rows if r.get("parse_status") == "ok"),
        "load_s": backend.load_s,
        "gpu": gpu,
    }


def _run_gpt54_judge(
    *,
    items: list,
    out_path: Path,
    job_id: str,
    seed_base: int = 0,
    source: str | None = None,
    shuffle: bool = False,
    shuffle_seed: int | None = None,
) -> dict:
    root = _setup_remote_repo()
    from rc.judging import judge_fate_batch, write_judgment_rows
    from rc.openai_batch import OpenAIBatchBackend

    work = Path(PHASE4_DIR) / "openai_batches" / job_id
    backend = OpenAIBatchBackend(
        "gpt54",
        work_dir=work,
        root=root,
        poll_seconds=60.0,
        job_id=job_id,
    )
    rows = judge_fate_batch(
        backend,
        "gpt54",
        items,
        root=root,
        seed_base=seed_base,
        source=source,
        shuffle=shuffle,
        shuffle_seed=shuffle_seed,
        rubric_version="v2",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_judgment_rows(out_path, rows)
    cost = backend.last_cost
    return {
        "judge_id": "gpt54",
        "n": len(rows),
        "n_ok": sum(1 for r in rows if r.get("parse_status") == "ok"),
        "batch_id": cost.batch_id,
        "api_usd": cost.usd,
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "cached_input_tokens": cost.cached_input_tokens,
    }


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
def calib_mistral_v3() -> dict:
    root = _setup_remote_repo()
    from rc.config import load_experiment
    from rc.judging import load_calibration_items, shuffle_items

    items = shuffle_items(load_calibration_items(root=root), "mistral_small32_24b", load_experiment(root).master_seed)
    return _run_open_weight_judge(
        "mistral_small32_24b",
        "A100-80GB",
        items=items,
        out_path=Path(CALIB_V3_DIR) / "mistral_small32_24b.jsonl",
    )


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
def calib_gptoss_v3() -> dict:
    root = _setup_remote_repo()
    from rc.config import load_experiment
    from rc.judging import load_calibration_items, shuffle_items

    items = shuffle_items(load_calibration_items(root=root), "gptoss_120b", load_experiment(root).master_seed)
    return _run_open_weight_judge(
        "gptoss_120b",
        "H100",
        items=items,
        out_path=Path(CALIB_V3_DIR) / "gptoss_120b.jsonl",
    )


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openai-key")],
    timeout=60 * 60 * 12,
    cpu=2,
    memory=8192,
)
def calib_gpt54_v3() -> dict:
    root = _setup_remote_repo()
    from rc.config import load_experiment
    from rc.judging import load_calibration_items, shuffle_items

    items = shuffle_items(load_calibration_items(root=root), "gpt54", load_experiment(root).master_seed)
    return _run_gpt54_judge(
        items=items,
        out_path=Path(CALIB_V3_DIR) / "gpt54.jsonl",
        job_id="calib_v3_gpt54",
    )


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 30,
    cpu=2,
    memory=4096,
)
def select_d38_v3() -> dict:
    """D38 eligibility on judge_calib_v3 (rubric v2)."""
    _setup_remote_repo()
    from rc.judge_metrics import select_judges_d33, select_judges_d38

    per: dict[str, list] = {}
    technical_failures: dict[str, str] = {}
    calib_dir = Path(CALIB_V3_DIR)
    for path in calib_dir.glob("*_technical_failure.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        jid = payload.get("judge_id") or path.name.replace("_technical_failure.json", "")
        technical_failures[jid] = str(payload.get("error") or "technical_failure")
    for path in calib_dir.glob("*.jsonl"):
        jid = path.stem
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if rows:
            per[jid] = rows
            technical_failures.pop(jid, None)
    d38 = select_judges_d38(per)
    d33 = select_judges_d33(per)
    d38["technical_failures"] = technical_failures
    d38["d33_reference"] = d33
    d38["run_tag"] = CALIB_RUN_TAG
    d38["candidates"] = list(CANDIDATES)
    out_dir = Path(PHASE4_DIR)
    (out_dir / "selection_d38_v3.json").write_text(
        json.dumps(d38, indent=2, default=str) + "\n", encoding="utf-8"
    )
    # Also write metrics for local pull.
    metrics = {
        jid: d38["metrics"][jid]
        for jid in d38.get("metrics", {})
    }
    (out_dir / "calibration_metrics_v3.json").write_text(
        json.dumps(
            {
                "run_tag": CALIB_RUN_TAG,
                "d38": d38,
                "metrics": metrics,
                "eligibility": d38.get("eligibility"),
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    runs_vol.commit()
    return d38


@app.function(
    image=image,
    gpu="A100-80GB",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    cpu=8,
    memory=65536,
)
def code_mistral_v3() -> dict:
    return _code_open_weight("mistral_small32_24b", "A100-80GB")


@app.function(
    image=image,
    gpu="H100",
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("hf-token")],
    timeout=60 * 60 * 2,
    cpu=8,
    memory=131072,
)
def code_gptoss_v3() -> dict:
    return _code_open_weight("gptoss_120b", "H100")


def _code_open_weight(judge_id: str, gpu: str) -> dict:
    import os

    root = _setup_remote_repo()
    from huggingface_hub import snapshot_download

    from rc.config import load_experiment
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

    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = []
    for t in transitions:
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted"))) is None:
            row = dict(t)
            row["source"] = "pilot"
            llm_items.append(row)

    repo_id, sha = load_lock_revision(judge_id, root=root)
    model_path = snapshot_download(
        repo_id=repo_id, revision=sha, token=os.environ.get("HF_TOKEN"), cache_dir=HF_CACHE
    )
    backend = VLLMBackend(
        judge_id,
        model_path=model_path,
        revision=sha,
        max_model_len=8192 if judge_id.startswith("gptoss") else 16384,
        enforce_eager=judge_id.startswith("gptoss"),
        max_num_seqs=16,
        root=root,
    )
    exp = load_experiment(root)
    rows = judge_fate_batch(
        backend,
        judge_id,
        llm_items,
        root=root,
        seed_base=hash(judge_id) % 10000,
        source="pilot",
        shuffle=True,
        shuffle_seed=int(exp.master_seed) + (hash(judge_id) % 1000),
        rubric_version="v2",
    )
    out_dir = Path(CODING_V3_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_judgment_rows(out_dir / f"{judge_id}.jsonl", rows)
    meta = {
        "judge_id": judge_id,
        "run_tag": CODING_RUN_TAG,
        "n": len(rows),
        "n_ok": sum(1 for r in rows if r.get("parse_status") == "ok"),
        "load_s": backend.load_s,
        "gpu": gpu,
    }
    # Eval-awareness once: first open-weight coder that reaches this point.
    eval_path = out_dir / "eval_awareness.jsonl"
    if not eval_path.exists():
        notes = extract_pilot_notes("pilot_v1", root=root)
        eval_rows = judge_eval_awareness_batch(backend, judge_id, notes, root=root, seed_base=9000)
        write_judgment_rows(eval_path, eval_rows)
        meta["n_eval"] = len(eval_rows)
    (out_dir / f"{judge_id}_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return meta


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openai-key")],
    timeout=60 * 60 * 18,
    cpu=2,
    memory=8192,
)
def code_gpt54_v3() -> dict:
    root = _setup_remote_repo()
    from rc.config import load_experiment
    from rc.judging import structural_fate
    from rc.pilot_coding import extract_pilot_transitions

    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = []
    for t in transitions:
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted"))) is None:
            row = dict(t)
            row["source"] = "pilot"
            llm_items.append(row)
    exp = load_experiment(root)
    meta = _run_gpt54_judge(
        items=llm_items,
        out_path=Path(CODING_V3_DIR) / "gpt54.jsonl",
        job_id="pilot_v3_gpt54",
        seed_base=hash("gpt54") % 10000,
        source="pilot",
        shuffle=True,
        shuffle_seed=int(exp.master_seed) + (hash("gpt54") % 1000),
    )
    meta["run_tag"] = CODING_RUN_TAG
    (Path(CODING_V3_DIR) / "gpt54_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return meta


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 30,
    cpu=2,
    memory=8192,
)
def finalize_d44_and_coding(eligible: list[str]) -> dict:
    """Integrity gates → D44 pair selection → join coded pilot → α gate."""
    _setup_remote_repo()
    import csv

    from rc.judge_integrity import assert_one_to_one_join, run_integrity_gates
    from rc.judge_metrics import (
        BINARY_ERODED,
        binary_erosion_label,
        krippendorff_alpha_ordinal,
        select_judges_d44,
    )
    from rc.judging import fate_ordinal, normalize_fate, structural_fate
    from rc.pilot_coding import (
        category_appendix_rows,
        extract_pilot_transitions,
        resolve_disagreement,
    )

    coding_dir = Path(CODING_V3_DIR)
    per: dict[str, list] = {}
    for jid in eligible:
        path = coding_dir / f"{jid}.jsonl"
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        per[jid] = rows

    # Integrity on all eligible outputs (binding = prompt-hash).
    all_rows = [r for rows in per.values() for r in rows]
    gates = run_integrity_gates(all_rows)
    (coding_dir / "integrity_gates.json").write_text(
        json.dumps(gates, indent=2) + "\n", encoding="utf-8"
    )
    if not gates["ok"]:
        summary = {
            "run_tag": CODING_RUN_TAG,
            "integrity_gates": gates,
            "stopped": True,
            "stop_reason": "integrity_gate_failed",
            "alpha_gate_pass": False,
        }
        (Path(PHASE4_DIR) / "pilot_coding_summary_v3.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
        )
        runs_vol.commit()
        return summary

    d44 = select_judges_d44(per, eligible_ids=eligible)
    (Path(PHASE4_DIR) / "selection_d44.json").write_text(
        json.dumps(d44, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if d44.get("stopped"):
        summary = {
            "run_tag": CODING_RUN_TAG,
            "d44": d44,
            "integrity_gates": gates,
            "stopped": True,
            "stop_reason": d44.get("stop_reason"),
            "alpha_gate_pass": False,
            "pair_alphas": d44.get("pair_alphas"),
            "eroded_rates": d44.get("eroded_rates"),
        }
        (Path(PHASE4_DIR) / "pilot_coding_summary_v3.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
        )
        runs_vol.commit()
        return summary

    j1, j2, j3 = d44["j1"], d44["j2"], d44.get("j3")
    transitions = extract_pilot_transitions("pilot_v1")

    def by_key(rows: list) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in rows:
            key = r.get("judgment_key") or r.get("transition_id")
            out[str(key)] = r
        return out

    j1_map = by_key(per[j1])
    j2_map = by_key(per[j2])
    j3_map = by_key(per[j3]) if j3 else {}

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

    assert_one_to_one_join(llm_items, [j1_map[t["transition_id"]] for t in llm_items])
    assert_one_to_one_join(llm_items, [j2_map[t["transition_id"]] for t in llm_items])
    if j3:
        assert_one_to_one_join(llm_items, [j3_map[t["transition_id"]] for t in llm_items])

    coded = list(structural)
    ratings_binary = []
    ratings_ordinal = []
    unresolved = 0
    for src in llm_items:
        tid = src["transition_id"]
        a, b = j1_map[tid], j2_map[tid]
        c = j3_map.get(tid)
        resolved = resolve_disagreement(a, b, c)
        if resolved["unresolved"]:
            unresolved += 1
        coded.append({**src, **resolved, "structural": False, "judgment_key": tid})
        ratings_ordinal.append([fate_ordinal(a.get("fate")), fate_ordinal(b.get("fate"))])
        la = binary_erosion_label(a.get("fate"))
        lb = binary_erosion_label(b.get("fate"))
        ratings_binary.append(
            [
                None if la is None else (1.0 if la == BINARY_ERODED else 0.0),
                None if lb is None else (1.0 if lb == BINARY_ERODED else 0.0),
            ]
        )

    alpha = krippendorff_alpha_ordinal(ratings_binary)
    alpha_ordinal = krippendorff_alpha_ordinal(ratings_ordinal)
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

    strength_le2 = sum(
        1
        for r in coded
        if not r.get("structural") and isinstance(r.get("strength"), int) and r["strength"] <= 2
    )

    summary = {
        "j1": j1,
        "j2": j2,
        "j3": j3,
        "run_tag": CODING_RUN_TAG,
        "rubric_version": "v2",
        "d44": d44,
        "n_transitions": len(transitions),
        "n_structural": len(structural),
        "n_llm": len(llm_items),
        "j1_j2_alpha": alpha,
        "j1_j2_alpha_binary": alpha,
        "j1_j2_alpha_ordinal": alpha_ordinal,
        "alpha_gate": "binary_d44",
        "alpha_gate_pass": bool(alpha is not None and alpha >= 0.70),
        "unresolved_rate": unresolved / max(len(llm_items), 1),
        "unresolved_n": unresolved,
        "strength_le2_n": strength_le2,
        "strength_le2_rate": strength_le2 / max(len(llm_items), 1),
        "fate_distributions": {k: dict(v) for k, v in dist.items()},
        "eval_awareness_rates": eval_rate,
        "integrity_gates": gates,
        "pair_alphas": d44.get("pair_alphas"),
        "eroded_rates": d44.get("eroded_rates"),
        "stopped": False,
    }
    (Path(PHASE4_DIR) / "pilot_coding_summary_v3.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    coded_path = Path(PHASE4_DIR) / "pilot_v1_coding_v3.jsonl"
    with coded_path.open("w", encoding="utf-8") as fh:
        for row in coded:
            slim = {k: v for k, v in row.items() if k not in {"j1", "j2", "j3"}}
            fh.write(json.dumps(slim, sort_keys=True) + "\n")
    appendix = Path(PHASE4_DIR) / "pilot_appendix_coding_v3.csv"
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
def power_sim_chunk(payload: dict) -> list:
    """One map unit: payload has tasks, hazard, master_seed (explicit; D48 fix)."""
    _setup_remote_repo()
    from rc.power_analysis import run_power_tasks

    return run_power_tasks(payload["tasks"], payload["hazard"], int(payload["master_seed"]))


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 60 * 3,
    cpu=2,
    memory=8192,
)
def run_power_and_g4_v3(n_sims: int = 1000) -> dict:
    _setup_remote_repo()
    from rc.config import load_experiment
    from rc.cost_projection import project_main_run
    from rc.power_analysis import estimate_pilot_hazard

    coded_path = Path(PHASE4_DIR) / "pilot_v1_coding_v3.jsonl"
    coded = [
        json.loads(line)
        for line in coded_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hazard = estimate_pilot_hazard(coded, run_tag="pilot_v1")
    (Path(PHASE4_DIR) / "hazard_estimates_v3.json").write_text(
        json.dumps(hazard, indent=2) + "\n", encoding="utf-8"
    )

    n_values = (10, 15, 20, 25)
    hrs = (1.5, 2.0)
    tasks = [(n, hr, i) for n in n_values for hr in hrs for i in range(n_sims)]
    chunk_size = max(1, len(tasks) // 64)
    chunks = [tasks[i : i + chunk_size] for i in range(0, len(tasks), chunk_size)]
    master_seed = load_experiment().master_seed
    results_nested = list(
        power_sim_chunk.map(
            [
                {"tasks": c, "hazard": hazard, "master_seed": master_seed}
                for c in chunks
            ],
            order_outputs=True,
        )
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
    (Path(PHASE4_DIR) / "power_table_v3.json").write_text(
        json.dumps(power, indent=2) + "\n", encoding="utf-8"
    )

    # Judging cost: Modal coding + API coding for selected panel.
    pending = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"
    coding_modal = 0.0
    coding_api = 0.0
    if pending.exists():
        for line in pending.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            jid = str(r.get("job_id", ""))
            if "coding" not in jid and "pilot" not in jid:
                continue
            usd = float(r.get("actual_usd") or 0)
            if r.get("platform") == "openai":
                coding_api += usd
            else:
                coding_modal += usd
    n_llm = max(1, sum(1 for r in coded if not r.get("structural")))
    judging_usd = (coding_modal + coding_api) / n_llm
    g4 = project_main_run(judging_usd_per_transition=judging_usd)
    g4["judging_modal_usd_pilot"] = coding_modal
    g4["judging_api_usd_pilot"] = coding_api
    (Path(PHASE4_DIR) / "g4_projection_v3.json").write_text(
        json.dumps(g4, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return {"power": power, "g4": g4}


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 10,
    cpu=1,
    memory=2048,
)
def run_eval_awareness_a2() -> dict:
    """A2 levels + keyword audit (CPU; uses pilot_v1 probe files)."""
    root = _setup_remote_repo()
    from collections import defaultdict
    from pathlib import Path as P

    # Pilot probes store judgment + probability_evaluation (not numeric level).
    levels: dict[str, dict] = {}
    for path in (P(REMOTE_RUNS) / "pilot_v1").glob("*/eval_awareness/calls.jsonl"):
        config_id = path.parts[-3]
        probs = []
        n_eval = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("probability_evaluation") is not None:
                probs.append(float(row["probability_evaluation"]))
            if str(row.get("judgment") or "").lower() == "evaluation":
                n_eval += 1
        if probs:
            levels[config_id] = {
                "n": len(probs),
                "mean_probability_evaluation": sum(probs) / len(probs),
                "judgment_evaluation_rate": n_eval / len(probs),
                "gte_0_5_rate": sum(1 for p in probs if p >= 0.5) / len(probs),
                "gte_0_8_rate": sum(1 for p in probs if p >= 0.8) / len(probs),
            }
    # Keyword audit on a few notes if present.
    keywords = ("evaluat", "benchmark", "test suite", "grader", "rubric")
    hits = []
    notes_n = 0
    for path in (P(REMOTE_RUNS) / "pilot_v1").rglob("rounds.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            note = str(row.get("note") or "")
            if not note:
                continue
            notes_n += 1
            low = note.lower()
            for kw in keywords:
                if kw in low:
                    hits.append({"config_id": path.parts[-3], "keyword": kw, "note": note[:120]})
                    break
            if len(hits) >= 10:
                break
        if len(hits) >= 10:
            break
    payload = {
        "levels": levels,
        "keyword_audit": {"n_notes_scanned": notes_n, "n_hits": len(hits), "examples": hits[:10]},
    }
    (Path(PHASE4_DIR) / "eval_awareness_a2_v3.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return payload


CODE_FN = {
    "mistral_small32_24b": code_mistral_v3,
    "gptoss_120b": code_gptoss_v3,
    "gpt54": code_gpt54_v3,
}
CALIB_FN = {
    "mistral_small32_24b": calib_mistral_v3,
    "gptoss_120b": calib_gptoss_v3,
    "gpt54": calib_gpt54_v3,
}


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("hf-token"),
        modal.Secret.from_name("openai-key"),
    ],
    timeout=60 * 60 * 24,
    cpu=2,
    memory=4096,
)
def orchestrate_phase4f(spent_at_launch: float = 0.0, api_spent_at_launch: float = 0.0) -> dict:
    """Unattended 4F: calib_v3 → D38 → pilot_v3 (eligible) → D44 → power → G4."""
    _setup_remote_repo()
    pending_path = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"
    if not pending_path.exists():
        pending_path.write_text("", encoding="utf-8")
        runs_vol.commit()

    def spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") == "modal" and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(spent_at_launch) + extra

    def api_spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") == "openai" and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(api_spent_at_launch) + extra

    from rc.config import load_budget

    cap = load_budget().phase4_hard_cap_usd
    api_cap = load_budget().api_hard_cap_usd

    # --- Stage 1: calibration v3 ---
    _write_status(
        "calib_v3",
        "running",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        run_tag=CALIB_RUN_TAG,
    )
    Path(CALIB_V3_DIR).mkdir(parents=True, exist_ok=True)
    for jid in CANDIDATES:
        out = Path(CALIB_V3_DIR) / f"{jid}.jsonl"
        if out.exists() and out.stat().st_size > 0:
            continue
        if jid != "gpt54" and spend_now() + 1.5 > cap:
            _write_status("calib_v3", "stopped", reason="modal budget", spend_usd=spend_now())
            return {"state": "stopped", "reason": "modal_budget"}
        started = time.perf_counter()
        try:
            meta = CALIB_FN[jid].remote()
            elapsed = time.perf_counter() - started
            if jid == "gpt54":
                _append_pending_ledger(
                    {
                        "timestamp_utc": _now(),
                        "job_id": f"phase4f-calib-{jid}",
                        "phase": "4f",
                        "platform": "openai",
                        "gpu": "api",
                        "actual_seconds": elapsed,
                        "actual_usd": float(meta.get("api_usd") or 0),
                        "est_usd": float(meta.get("api_usd") or 0),
                        "note": f"ok | {CALIB_RUN_TAG} | {meta}",
                    }
                )
            else:
                gpu = JUDGE_GPU[jid]
                _append_pending_ledger(
                    {
                        "timestamp_utc": _now(),
                        "job_id": f"phase4f-calib-{jid}",
                        "phase": "4f",
                        "platform": "modal",
                        "gpu": gpu,
                        "actual_seconds": elapsed,
                        "actual_usd": _estimate(gpu, int(elapsed) + 1),
                        "note": f"ok | {CALIB_RUN_TAG} | {meta}",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            fail_path = Path(CALIB_V3_DIR) / f"{jid}_technical_failure.json"
            fail_path.write_text(
                json.dumps({"judge_id": jid, "error": str(exc), "timestamp_utc": _now()}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            runs_vol.commit()
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4f-calib-{jid}",
                    "phase": "4f",
                    "platform": "openai" if jid == "gpt54" else "modal",
                    "gpu": JUDGE_GPU[jid],
                    "actual_seconds": elapsed,
                    "actual_usd": 0.0 if jid == "gpt54" else _estimate(JUDGE_GPU[jid], int(elapsed) + 1),
                    "note": f"code_failure | {exc}",
                }
            )

    if api_spend_now() > api_cap:
        _write_status(
            "calib_v3",
            "stopped",
            reason=f"API cap ${api_cap}",
            spend_usd=spend_now(),
            api_spend_usd=api_spend_now(),
        )
        return {"state": "stopped", "reason": "api_budget"}

    d38 = select_d38_v3.remote()
    eligible = [
        jid
        for jid, info in (d38.get("eligibility") or {}).items()
        if info.get("eligible")
    ]
    _write_status(
        "calib_v3",
        "done",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        eligible=eligible,
        d38_stopped=d38.get("stopped"),
    )
    if len(eligible) < 2:
        _write_status(
            "d38",
            "stopped",
            reason=d38.get("stop_reason") or "fewer than 2 eligible",
            spend_usd=spend_now(),
            api_spend_usd=api_spend_now(),
            d38=d38,
        )
        return {"state": "stopped", "reason": "d38", "d38": d38}

    # --- Stage 2: pilot coding v3 for every eligible candidate ---
    _write_status(
        "coding_v3",
        "running",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        eligible=eligible,
        run_tag=CODING_RUN_TAG,
    )
    Path(CODING_V3_DIR).mkdir(parents=True, exist_ok=True)
    for jid in eligible:
        out = Path(CODING_V3_DIR) / f"{jid}.jsonl"
        if out.exists() and out.stat().st_size > 0:
            continue
        if jid != "gpt54" and spend_now() + 1.5 > cap:
            _write_status("coding_v3", "stopped", reason="modal budget", spend_usd=spend_now())
            return {"state": "stopped", "reason": "modal_budget"}
        started = time.perf_counter()
        try:
            meta = CODE_FN[jid].remote()
            elapsed = time.perf_counter() - started
            if jid == "gpt54":
                _append_pending_ledger(
                    {
                        "timestamp_utc": _now(),
                        "job_id": f"phase4f-coding-{jid}",
                        "phase": "4f",
                        "platform": "openai",
                        "gpu": "api",
                        "actual_seconds": elapsed,
                        "actual_usd": float(meta.get("api_usd") or 0),
                        "est_usd": float(meta.get("api_usd") or 0),
                        "note": f"ok | {CODING_RUN_TAG} | {meta}",
                    }
                )
            else:
                gpu = JUDGE_GPU[jid]
                _append_pending_ledger(
                    {
                        "timestamp_utc": _now(),
                        "job_id": f"phase4f-coding-{jid}",
                        "phase": "4f",
                        "platform": "modal",
                        "gpu": gpu,
                        "actual_seconds": elapsed,
                        "actual_usd": _estimate(gpu, int(elapsed) + 1),
                        "note": f"ok | {CODING_RUN_TAG} | {meta}",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4f-coding-{jid}",
                    "phase": "4f",
                    "platform": "openai" if jid == "gpt54" else "modal",
                    "gpu": JUDGE_GPU[jid],
                    "actual_seconds": elapsed,
                    "actual_usd": 0.0 if jid == "gpt54" else _estimate(JUDGE_GPU[jid], int(elapsed) + 1),
                    "note": f"code_failure | {exc}",
                }
            )
            _write_status("coding_v3", "stopped", reason=str(exc), spend_usd=spend_now())
            return {"state": "stopped", "reason": str(exc)}

    if api_spend_now() > api_cap:
        _write_status(
            "coding_v3",
            "stopped",
            reason=f"API cap ${api_cap}",
            spend_usd=spend_now(),
            api_spend_usd=api_spend_now(),
        )
        return {"state": "stopped", "reason": "api_budget"}

    summary = finalize_d44_and_coding.remote(eligible)
    if summary.get("stopped"):
        _write_status(
            "coding_v3",
            "stopped",
            reason=summary.get("stop_reason"),
            spend_usd=spend_now(),
            api_spend_usd=api_spend_now(),
            summary=summary,
        )
        return {"state": "stopped", "reason": summary.get("stop_reason"), "summary": summary}

    _write_status(
        "coding_v3",
        "done",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        alpha=summary.get("j1_j2_alpha"),
        j1=summary.get("j1"),
        j2=summary.get("j2"),
        j3=summary.get("j3"),
    )

    # --- Stage 3: eval-awareness A2 + power + G4 ---
    eval_a2 = run_eval_awareness_a2.remote()
    _write_status("power_g4", "running", spend_usd=spend_now(), api_spend_usd=api_spend_now())
    started = time.perf_counter()
    result = run_power_and_g4_v3.remote(1000)
    elapsed = time.perf_counter() - started
    _append_pending_ledger(
        {
            "timestamp_utc": _now(),
            "job_id": "phase4f-power-g4",
            "phase": "4f",
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
        api_spend_usd=api_spend_now(),
        recommended_n=result.get("power", {}).get("recommended_n_hr15"),
        eval_awareness=eval_a2,
    )
    return {
        "state": "done",
        "d38": d38,
        "summary": summary,
        "result": result,
        "eval_awareness": eval_a2,
        "spend_usd": spend_now(),
        "api_spend_usd": api_spend_now(),
    }


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    timeout=60 * 60 * 6,
    cpu=2,
    memory=4096,
)
def orchestrate_phase4f_resume(spent_at_launch: float = 0.0, api_spent_at_launch: float = 0.0) -> dict:
    """D45 resume: reuse coding_v3 (no re-judge) → D44 → α → power → G4 → eval A2."""
    _setup_remote_repo()
    pending_path = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"

    def spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") == "modal" and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(spent_at_launch) + extra

    def api_spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") == "openai" and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(api_spent_at_launch) + extra

    eligible = ["gpt54", "mistral_small32_24b"]
    for jid in eligible:
        path = Path(CODING_V3_DIR) / f"{jid}.jsonl"
        if not path.exists() or path.stat().st_size == 0:
            _write_status(
                "resume",
                "stopped",
                reason=f"missing coding_v3 for {jid}",
                spend_usd=spend_now(),
                api_spend_usd=api_spend_now(),
            )
            return {"state": "stopped", "reason": f"missing {jid}"}

    _write_status(
        "resume_d44",
        "running",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        eligible=eligible,
        decision="D45",
        note="reuse pilot_v1_coding_v3; no re-judge",
    )
    summary = finalize_d44_and_coding.remote(eligible)
    # Persist quote non-hit examples for PHASE_4F.md
    quote = (summary.get("integrity_gates") or {}).get("quote_audit") or {}
    (Path(PHASE4_DIR) / "quote_audit_v3.json").write_text(
        json.dumps(quote, indent=2, default=str) + "\n", encoding="utf-8"
    )
    runs_vol.commit()

    if summary.get("stopped"):
        _write_status(
            "resume_d44",
            "stopped",
            reason=summary.get("stop_reason"),
            spend_usd=spend_now(),
            api_spend_usd=api_spend_now(),
            summary=summary,
        )
        return {"state": "stopped", "reason": summary.get("stop_reason"), "summary": summary}

    _write_status(
        "coding_v3",
        "done",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        alpha=summary.get("j1_j2_alpha"),
        j1=summary.get("j1"),
        j2=summary.get("j2"),
        j3=summary.get("j3"),
        quote_hit_rate=quote.get("hit_rate"),
    )

    eval_a2 = run_eval_awareness_a2.remote()
    _write_status("power_g4", "running", spend_usd=spend_now(), api_spend_usd=api_spend_now())
    started = time.perf_counter()
    result = run_power_and_g4_v3.remote(1000)
    elapsed = time.perf_counter() - started
    _append_pending_ledger(
        {
            "timestamp_utc": _now(),
            "job_id": "phase4f-power-g4",
            "phase": "4f",
            "platform": "modal",
            "gpu": "cpu",
            "actual_seconds": elapsed,
            "actual_usd": _estimate("cpu", int(elapsed) + 1),
            "note": "power sims + g4 (D45 resume)",
        }
    )
    _write_status(
        "done",
        "done",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        recommended_n=result.get("power", {}).get("recommended_n_hr15"),
        eval_awareness=eval_a2,
        quote_hit_rate=quote.get("hit_rate"),
        decision="D45",
    )
    return {
        "state": "done",
        "summary": summary,
        "result": result,
        "eval_awareness": eval_a2,
        "spend_usd": spend_now(),
        "api_spend_usd": api_spend_now(),
    }


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 60 * 3,
    cpu=2,
    memory=8192,
)
def run_power_and_g4_d48(n_sims: int = 1000) -> dict:
    """Power + G4 using D48 primary (gpt54) event coding."""
    _setup_remote_repo()
    from rc.config import load_experiment
    from rc.cost_projection import project_main_run
    from rc.d48_design import build_primary_coded
    from rc.power_analysis import estimate_pilot_hazard

    coding_dir = Path(PHASE4_DIR) / "coding_v3"
    coded = build_primary_coded(
        coding_dir=coding_dir,
        root=Path(REMOTE_REPO),
    )
    coded_path = Path(PHASE4_DIR) / "pilot_v1_coding_d48_primary.jsonl"
    with coded_path.open("w", encoding="utf-8") as fh:
        for row in coded:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    hazard = estimate_pilot_hazard(coded, run_tag="pilot_v1")
    (Path(PHASE4_DIR) / "hazard_estimates_d48.json").write_text(
        json.dumps(hazard, indent=2) + "\n", encoding="utf-8"
    )

    # In-process (no .map): preemptible map workers were thrashing under restart.
    # Same task packing as smoke/production (.map payload still used by smoke_d48).
    from rc.power_analysis import run_power_table

    master_seed = load_experiment().master_seed
    power = run_power_table(
        hazard,
        n_sims=n_sims,
        n_values=(10, 15, 20, 25),
        hrs=(1.5, 2.0),
        master_seed=master_seed,
        workers=2,
    )
    power = {
        "decision": "D48",
        "event_mode": "primary_gpt54",
        **power,
    }
    (Path(PHASE4_DIR) / "power_table_d48.json").write_text(
        json.dumps(power, indent=2) + "\n", encoding="utf-8"
    )

    pending = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"
    coding_modal = coding_api = 0.0
    if pending.exists():
        for line in pending.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            jid = str(r.get("job_id", ""))
            if "coding" not in jid and "calib" not in jid:
                continue
            usd = float(r.get("actual_usd") or 0)
            if r.get("platform") in {"openai", "openrouter"}:
                coding_api += usd
            elif r.get("platform") == "modal":
                coding_modal += usd
    n_llm = max(1, sum(1 for r in coded if not r.get("structural")))
    judging_usd = (coding_modal + coding_api) / n_llm
    g4 = project_main_run(judging_usd_per_transition=judging_usd)
    g4["judging_modal_usd_pilot"] = coding_modal
    g4["judging_api_usd_pilot"] = coding_api
    g4["decision"] = "D48"
    (Path(PHASE4_DIR) / "g4_projection_d48.json").write_text(
        json.dumps(g4, indent=2) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return {"power": power, "g4": g4, "hazard": hazard}


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    timeout=60 * 60 * 4,
    cpu=2,
    memory=4096,
)
def orchestrate_d48_unblock(spent_at_launch: float = 0.0, api_spent_at_launch: float = 0.0) -> dict:
    """D48 unblock: power (gpt54 primary) → G4 → eval-awareness. No new judge calls."""
    _setup_remote_repo()
    pending_path = Path(PHASE4_DIR) / "ledger_pending_4f.jsonl"

    def spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") == "modal" and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(spent_at_launch) + extra

    def api_spend_now() -> float:
        extra = 0.0
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("platform") in {"openai", "openrouter"} and row.get("actual_usd") is not None:
                        extra += float(row["actual_usd"])
        return float(api_spent_at_launch) + extra

    # Persist D48 subsample draw on the volume (seed fixed; idempotent).
    from rc.d48_design import draw_reliability_subsample

    sub = draw_reliability_subsample()
    (Path(PHASE4_DIR) / "d48_reliability_subsample.json").write_text(
        json.dumps(sub, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runs_vol.commit()

    _write_status(
        "d48_power_g4",
        "running",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        decision="D48",
        primary="gpt54",
    )
    eval_a2 = run_eval_awareness_a2.remote()
    started = time.perf_counter()
    result = run_power_and_g4_d48.remote(1000)
    elapsed = time.perf_counter() - started
    _append_pending_ledger(
        {
            "timestamp_utc": _now(),
            "job_id": "phase4f-d48-power-g4",
            "phase": "4f",
            "platform": "modal",
            "gpu": "cpu",
            "actual_seconds": elapsed,
            "actual_usd": _estimate("cpu", int(elapsed) + 1),
            "note": "D48 power sims + g4 (gpt54 primary)",
        }
    )
    _write_status(
        "done",
        "done",
        spend_usd=spend_now(),
        api_spend_usd=api_spend_now(),
        decision="D48",
        recommended_n=result.get("power", {}).get("recommended_n_hr15"),
        eval_awareness=eval_a2,
        subsample_n=sub.get("n_selected"),
    )
    return {
        "state": "done",
        "result": result,
        "eval_awareness": eval_a2,
        "subsample": {"n_selected": sub["n_selected"], "n_population": sub["n_population"]},
        "spend_usd": spend_now(),
        "api_spend_usd": api_spend_now(),
    }


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openrouter-key")],
    timeout=60 * 60 * 18,
    cpu=2,
    memory=8192,
    retries=modal.Retries(max_retries=8, backoff_coefficient=1.5, initial_delay=10.0),
)
def background_mimo_calib_and_pilot() -> dict:
    """Non-blocking D48: mimo D38 calib + reliability-subsample pilot coding.

    If mimo fails D38, try glm53 under the same rules.
    """
    print("[d48-bg] start", flush=True)
    root = _setup_remote_repo()
    print("[d48-bg] repo ready", flush=True)
    from rc.config import load_experiment
    from rc.d48_design import draw_reliability_subsample
    from rc.judging import judge_fate_batch, load_calibration_items, shuffle_items, structural_fate, write_judgment_rows
    from rc.judge_metrics import select_judges_d38
    from rc.openrouter_backend import OpenRouterBackend
    from rc.pilot_coding import extract_pilot_transitions

    out: dict[str, Any] = {"decision": "D48", "steps": []}
    exp = load_experiment(root)
    sub = draw_reliability_subsample(root=root)
    (Path(PHASE4_DIR) / "d48_reliability_subsample.json").write_text(
        json.dumps(sub, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    print(f"[d48-bg] subsample n={sub['n_selected']}", flush=True)

    def _run_judge(judge_id: str, items: list, job_id: str, out_path: Path) -> dict:
        print(f"[d48-bg] judge {judge_id} n={len(items)} job={job_id}", flush=True)
        backend = OpenRouterBackend(
            judge_id,
            work_dir=Path(PHASE4_DIR) / "openrouter" / job_id,
            root=root,
            job_id=job_id,
            est_usd_per_request=0.002,
        )
        # Chunk to keep logs alive and avoid one giant preflight estimate edge case.
        chunk = 50
        rows: list[dict] = []
        total_usd = 0.0
        total_in = total_out = 0
        model = provider = None
        for start in range(0, len(items), chunk):
            part = items[start : start + chunk]
            print(f"[d48-bg] {job_id} chunk {start}:{start+len(part)}", flush=True)
            part_rows = judge_fate_batch(
                backend,
                judge_id,
                part,
                root=root,
                seed_base=(hash(job_id) % 10000) + start,
                rubric_version="v2",
            )
            rows.extend(part_rows)
            cost = backend.last_cost
            total_usd += float(cost.usd or 0)
            total_in += int(cost.prompt_tokens or 0)
            total_out += int(cost.completion_tokens or 0)
            model = cost.model or model
            provider = cost.provider or provider
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_judgment_rows(out_path, rows)
            runs_vol.commit()
            print(
                f"[d48-bg] {job_id} wrote {len(rows)}/{len(items)} usd={total_usd:.4f}",
                flush=True,
            )
        _append_pending_ledger(
            {
                "timestamp_utc": _now(),
                "job_id": job_id,
                "phase": "4f",
                "platform": "openrouter",
                "gpu": "api",
                "actual_seconds": None,
                "actual_usd": total_usd,
                "est_usd": total_usd,
                "note": (
                    f"ok | {judge_id} | model={model} provider={provider} "
                    f"n={len(rows)} tokens_in={total_in} tokens_out={total_out}"
                ),
            }
        )
        return {
            "judge_id": judge_id,
            "n": len(rows),
            "usd": total_usd,
            "model": model,
            "provider": provider,
            "served_path": str(out_path),
        }

    # Calibration on same 1031 items.
    candidates = ["mimo_v26_pro", "glm53"]
    chosen = None
    calib_dir = Path(PHASE4_DIR) / "calib_d48"
    calib_dir.mkdir(parents=True, exist_ok=True)
    for jid in candidates:
        items = shuffle_items(load_calibration_items(root=root), jid, exp.master_seed)
        try:
            meta = _run_judge(jid, items, f"d48-calib-{jid}", calib_dir / f"{jid}.jsonl")
            out["steps"].append({"stage": "calib", **meta})
        except Exception as exc:  # noqa: BLE001
            out["steps"].append({"stage": "calib", "judge_id": jid, "error": str(exc)})
            (calib_dir / f"{jid}_technical_failure.json").write_text(
                json.dumps({"judge_id": jid, "error": str(exc)}, indent=2) + "\n",
                encoding="utf-8",
            )
            runs_vol.commit()
            continue
        # D38 vs gpt54 calib reference: evaluate mimo alone on planted labels.
        rows = [
            json.loads(line)
            for line in (calib_dir / f"{jid}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        d38 = select_judges_d38({jid: rows})
        (calib_dir / f"{jid}_d38.json").write_text(
            json.dumps(d38, indent=2, default=str) + "\n", encoding="utf-8"
        )
        eligible = bool((d38.get("eligibility") or {}).get(jid, {}).get("eligible"))
        out["steps"].append({"stage": "d38", "judge_id": jid, "eligible": eligible, "d38": d38.get("eligibility")})
        if eligible:
            chosen = jid
            break
        # If mimo fails, try glm53; if glm fails too, stop background.
    if chosen is None:
        out["state"] = "stopped"
        out["reason"] = "no D38-eligible second judge (mimo/glm)"
        (Path(PHASE4_DIR) / "d48_background_summary.json").write_text(
            json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
        )
        runs_vol.commit()
        return out

    # Pilot: code reliability subsample only (LLM items among selected IDs).
    selected = set(sub["transition_ids"])
    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = []
    for t in transitions:
        if t["transition_id"] not in selected:
            continue
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted"))) is None:
            row = dict(t)
            row["source"] = "pilot"
            llm_items.append(row)
    coding_dir = Path(PHASE4_DIR) / "coding_d48"
    try:
        meta = _run_judge(
            chosen,
            llm_items,
            f"d48-pilot-subsample-{chosen}",
            coding_dir / f"{chosen}_subsample.jsonl",
        )
        out["steps"].append({"stage": "pilot_subsample", **meta})
    except Exception as exc:  # noqa: BLE001
        out["state"] = "stopped"
        out["reason"] = str(exc)
        out["steps"].append({"stage": "pilot_subsample", "error": str(exc)})
        (Path(PHASE4_DIR) / "d48_background_summary.json").write_text(
            json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
        )
        runs_vol.commit()
        return out

    # FORCED per-round α vs gpt54 on the subsample.
    from rc.d48_design import subsample_forced_alpha

    gpt_path = Path(PHASE4_DIR) / "coding_v3" / "gpt54.jsonl"
    if not gpt_path.exists():
        # Fall back to local mount path used earlier.
        gpt_path = Path(REMOTE_RUNS) / "phase4" / "coding_v3" / "gpt54.jsonl"
    gpt_rows = [
        json.loads(line)
        for line in gpt_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    second_rows = [
        json.loads(line)
        for line in (coding_dir / f"{chosen}_subsample.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    alpha_report = subsample_forced_alpha(gpt_rows, second_rows, selected)
    out["second_judge"] = chosen
    out["subsample_alpha"] = alpha_report
    out["state"] = "done"
    (Path(PHASE4_DIR) / "d48_background_summary.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    return out


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openrouter-key")],
    timeout=60 * 15,
    cpu=2,
    memory=4096,
)
def smoke_d48() -> dict:
    """Required pre-launch checks: tiny power .map + 1 OpenRouter call per second-judge."""
    root = _setup_remote_repo()
    from rc.judging import judge_fate_batch, load_calibration_items, parse_fate_response
    from rc.openrouter_backend import OpenRouterBackend
    from rc.power_analysis import estimate_pilot_hazard
    from rc.d48_design import build_primary_coded

    out: dict[str, Any] = {"ok": True, "checks": []}

    # --- Power .map smoke (same payload signature as production) ---
    coding_dir = Path(PHASE4_DIR) / "coding_v3"
    coded = build_primary_coded(coding_dir=coding_dir, root=root)
    hazard = estimate_pilot_hazard(coded, run_tag="pilot_v1")
    n_sims = 3
    n_values = (5,)
    hrs = (1.5,)
    tasks = [(n, hr, i) for n in n_values for hr in hrs for i in range(n_sims)]
    # Two chunks so .map is exercised.
    chunks = [tasks[:2], tasks[2:]]
    master_seed = 20261004
    try:
        nested = list(
            power_sim_chunk.map(
                [
                    {"tasks": c, "hazard": hazard, "master_seed": master_seed}
                    for c in chunks
                    if c
                ],
                order_outputs=True,
            )
        )
        flat = [r for chunk in nested for r in chunk]
        assert len(flat) == n_sims, f"expected {n_sims} sims, got {len(flat)}"
        out["checks"].append(
            {
                "check": "power_sim_chunk.map",
                "ok": True,
                "n_results": len(flat),
                "sample": flat[0] if flat else None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["checks"].append({"check": "power_sim_chunk.map", "ok": False, "error": str(exc)})

    # --- OpenRouter 1-item smoke for mimo + glm ---
    items = load_calibration_items(root=root)
    one = [items[0]]
    for jid in ("mimo_v26_pro", "glm53"):
        try:
            backend = OpenRouterBackend(
                jid,
                work_dir=Path(PHASE4_DIR) / "openrouter" / f"smoke_{jid}",
                root=root,
                job_id=f"smoke-{jid}",
                est_usd_per_request=0.01,
            )
            rows = judge_fate_batch(
                backend, jid, one, root=root, seed_base=0, rubric_version="v2"
            )
            row = rows[0]
            parsed_ok = row.get("parse_status") == "ok"
            # Re-parse raw to confirm JSON
            if row.get("raw_text"):
                parsed_ok = parsed_ok and parse_fate_response(row["raw_text"]).parse_status == "ok"
            cost = backend.last_cost
            ok = bool(parsed_ok and row.get("fate") and cost.model)
            if not ok:
                out["ok"] = False
            out["checks"].append(
                {
                    "check": f"openrouter_{jid}",
                    "ok": ok,
                    "fate": row.get("fate"),
                    "parse_status": row.get("parse_status"),
                    "served_model": cost.model,
                    "served_provider": cost.provider,
                    "usd": cost.usd,
                    "provider_order": backend.provider_order,
                }
            )
            _append_pending_ledger(
                {
                    "timestamp_utc": _now(),
                    "job_id": f"phase4f-smoke-{jid}",
                    "phase": "4f",
                    "platform": "openrouter",
                    "gpu": "api",
                    "actual_usd": cost.usd,
                    "est_usd": cost.usd,
                    "note": f"ok | smoke | model={cost.model} provider={cost.provider}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            out["ok"] = False
            out["checks"].append({"check": f"openrouter_{jid}", "ok": False, "error": str(exc)})

    (Path(PHASE4_DIR) / "d48_smoke.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
    )
    runs_vol.commit()
    print(json.dumps(out, indent=2, default=str))
    return out


@app.function(
    image=cpu_image,
    volumes={HF_CACHE: hf_vol, REMOTE_RUNS: runs_vol},
    secrets=[
        modal.Secret.from_name("hf-token"),
        modal.Secret.from_name("openrouter-key"),
    ],
    timeout=60 * 60 * 20,
    cpu=2,
    memory=4096,
)
def orchestrate_d48_session(spent_at_launch: float = 0.0, api_spent_at_launch: float = 0.0) -> dict:
    """Parent keeps both D48 jobs alive under one detached container."""
    # Reset stale STATUS from prior failed run.
    _write_status(
        "d48_session",
        "running",
        spend_usd=spent_at_launch,
        api_spend_usd=api_spent_at_launch,
        decision="D48",
        note="relaunched after smoke fixes",
    )
    bg = background_mimo_calib_and_pilot.spawn()
    unblock = orchestrate_d48_unblock.remote(spent_at_launch, api_spent_at_launch)
    # Wait for background to finish so the parent covers the full phase.
    bg_result = bg.get()
    _write_status(
        "done",
        "done" if unblock.get("state") == "done" else "stopped",
        decision="D48",
        unblock_state=unblock.get("state"),
        background_state=bg_result.get("state") if isinstance(bg_result, dict) else None,
        recommended_n=(unblock.get("result") or {}).get("power", {}).get("recommended_n_hr15")
        if isinstance(unblock, dict)
        else None,
        second_judge=bg_result.get("second_judge") if isinstance(bg_result, dict) else None,
        subsample_alpha=(bg_result.get("subsample_alpha") or {}).get("alpha")
        if isinstance(bg_result, dict)
        else None,
    )
    return {"unblock": unblock, "background": bg_result}


@app.local_entrypoint()
def main() -> None:
    """Smoke checks, then detach D48 session (power/G4 + background MiMo)."""
    import subprocess

    from rc.budget import spent_api_usd, spent_modal_usd
    from rc.config import load_budget, repo_root
    from rc.d48_design import save_reliability_subsample
    from rc.guards import assert_modal_workspace, gptoss_judge_smoke_marker
    from rc.io_utils import git_sha as local_git_sha

    assert_modal_workspace(expected="heyronith")
    root = repo_root()
    if not gptoss_judge_smoke_marker(root).exists():
        raise SystemExit("D23: gpt-oss-20b L4 smoke marker missing")

    sub_path = save_reliability_subsample(root)
    print("D48 pilot reliability subsample (not main-run) written", sub_path)

    spent = spent_modal_usd(root)
    api_spent = spent_api_usd(root)
    budget = load_budget(root)
    print(f"Modal ledger ${spent:.2f} / cap ${budget.phase4_hard_cap_usd}")
    print(
        f"API ledger ${api_spent:.2f} / cap ${budget.api_hard_cap_usd} "
        f"(OpenRouter ≤ ${budget.openrouter_hard_cap_usd})"
    )
    print("git_sha", local_git_sha(root))

    for local, remote in (
        (
            root / "runs" / "phase4_coding" / "d48_reliability_subsample.json",
            "phase4/d48_reliability_subsample.json",
        ),
        (
            root / "runs" / "pilot_v1_coding_v3" / "coding_v3" / "gpt54.jsonl",
            "phase4/coding_v3/gpt54.jsonl",
        ),
    ):
        if local.exists():
            subprocess.check_call(
                ["modal", "volume", "put", "rc-runs", str(local), remote, "--force"]
            )

    print("Running D48 smoke checks (power .map + OpenRouter ×2)…")
    smoke = smoke_d48.remote()
    print("smoke result:", json.dumps(smoke, indent=2, default=str)[:2000])
    if not smoke.get("ok"):
        raise SystemExit(f"D48 smoke failed: {smoke}")

    # Clear stale STATUS locally on volume via a tiny write through spawn parent.
    handle = orchestrate_d48_session.spawn(spent, api_spent)
    print(f"orchestrate_d48_session spawned: {handle.object_id}")
    print("Monitoring until done; Session 2 will write reports/PHASE_4F.md.")

