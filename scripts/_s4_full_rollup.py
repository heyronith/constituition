"""Session 4 finish: consistency + checks + MiMo/Batch rollup for all 7 configs."""

from __future__ import annotations

import json
from pathlib import Path

import modal

app = modal.App("rc-s4-full-rollup")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
        "huggingface_hub",
        "textstat>=0.7.13",
        "openai",
        "httpx",
    )
    .add_local_dir("src", remote_path="/rc/src")
    .add_local_dir("materials", remote_path="/rc/materials")
    .add_local_dir("configs", remote_path="/rc/configs")
    .add_local_file("pyproject.toml", remote_path="/rc/pyproject.toml")
    .add_local_file(
        "results/canary_olmo3_7b_final_snapshot.json",
        remote_path="/rc/results/canary_olmo3_7b_final_snapshot.json",
    )
)
vol = modal.Volume.from_name("rc-runs")

CONFIGS = (
    "olmo3_7b_final",
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
)


@app.function(image=image, volumes={"/vol": vol}, timeout=1800)
def rollup() -> dict:
    import os
    import shutil

    runs = Path("/rc/runs")
    if runs.exists() or runs.is_symlink():
        if runs.is_symlink() or runs.is_file():
            runs.unlink()
        else:
            shutil.rmtree(runs)
    runs.symlink_to("/vol")
    budget = Path("/rc/budget")
    vol_budget = Path("/vol/main_v1/budget")
    vol_budget.mkdir(parents=True, exist_ok=True)
    if budget.is_symlink() or budget.is_file():
        budget.unlink()
    elif budget.exists():
        shutil.rmtree(budget)
    budget.symlink_to(vol_budget)
    (budget / "ledger.jsonl").touch()
    os.chdir("/rc")
    import sys

    sys.path.insert(0, "/rc/src")
    from rc.chain_runner import verify_run_consistency
    from rc.main_run_coding import load_mimo_slot_ids, mimo_slot_post_censor
    from rc.phase7b import verify_canary_snapshot

    root = Path("/rc")
    selected_all = load_mimo_slot_ids(root)
    out: dict = {"configs": {}, "n_chains_total": 0, "consistency_all_ok": True}

    for cid in CONFIGS:
        gate = verify_run_consistency("main_v1", cid, root=root)
        ck_path = root / "runs/main_v1" / cid / "config_checks.json"
        st_path = root / "runs/main_v1" / f"STATUS_{cid}.json"
        if cid == "olmo3_7b_final" and not st_path.exists():
            st_path = root / "runs/main_v1" / "STATUS.json"
        coding = root / "runs/main_v1/coding" / cid
        if cid == "olmo3_7b_final" and not (coding / "gpt54_meta.json").exists():
            coding = root / "runs/main_v1/coding"
        ck = json.loads(ck_path.read_text()) if ck_path.exists() else None
        st = json.loads(st_path.read_text()) if st_path.exists() else None
        gpt = (
            json.loads((coding / "gpt54_meta.json").read_text())
            if (coding / "gpt54_meta.json").exists()
            else {}
        )
        mimo = (
            json.loads((coding / "mimo_meta.json").read_text())
            if (coding / "mimo_meta.json").exists()
            else {}
        )
        # Count chains
        base = root / "runs/main_v1" / cid
        n_chains = sum(1 for p in base.rglob("chain_*") if p.is_dir()) if base.exists() else 0
        out["n_chains_total"] += n_chains
        if not gate.get("ok"):
            out["consistency_all_ok"] = False

        selected = {s for s in selected_all if s.startswith(f"{cid}|")}
        present = int(mimo.get("n_slots_selected_present") or mimo.get("n") or 0)
        missing = int(mimo.get("n_slots_selected_missing") or 0)
        post_censor = int(mimo.get("n_slots_missing_post_censor") or 0)
        if post_censor == 0 and selected:
            # recompute post-censor absences if meta lacks field
            post_censor = sum(
                1
                for sid in selected
                if mimo_slot_post_censor(sid, run_tag="main_v1", root=root)
            )

        c1 = (ck or {}).get("C1") or (ck or {}).get("C1_subject_parsing")
        c3 = (ck or {}).get("C3") or (ck or {}).get("C3_judge_integrity")
        c5 = (ck or {}).get("C5") or (ck or {}).get("C5_storage")
        # normalize pass flags
        def _pass(block):
            if block is None:
                return None
            if isinstance(block, dict) and "pass" in block:
                return block.get("pass")
            return None

        out["configs"][cid] = {
            "status": {
                k: (st or {}).get(k)
                for k in (
                    "state",
                    "stage",
                    "checks_pass",
                    "batch_ids",
                    "last_update_utc",
                )
            },
            "n_chains": n_chains,
            "consistency_ok": bool(gate.get("ok")),
            "consistency_n_failed": gate.get("n_failed"),
            "C1": c1,
            "C3": c3,
            "C5": c5,
            "C1_pass": _pass(c1),
            "C3_pass": _pass(c3),
            "C5_pass": _pass(c5),
            "all_pass": (ck or {}).get("all_pass"),
            "gpt54": {
                "api_usd": gpt.get("api_usd"),
                "n": gpt.get("n"),
                "n_batch": gpt.get("n_batch"),
                "n_sync": gpt.get("n_sync"),
                "batch_id": gpt.get("batch_id"),
                "resumed_from_jsonl": gpt.get("resumed_from_jsonl"),
            },
            "mimo": {
                "api_usd": mimo.get("api_usd"),
                "n": mimo.get("n"),
                "n_selected": len(selected),
                "n_present": present,
                "n_missing": missing,
                "n_post_censor_absent": post_censor,
                "n_resumed": mimo.get("n_resumed"),
                "n_api_new": mimo.get("n_api_new"),
            },
        }

    snap = json.loads(
        (root / "results/canary_olmo3_7b_final_snapshot.json").read_text(encoding="utf-8")
    )
    out["canary_snapshot"] = verify_canary_snapshot(snap, root=root)
    return out


@app.local_entrypoint()
def main() -> None:
    result = rollup.remote()
    Path("results/phase7b_session4_full_rollup.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, default=str)[:12000])
