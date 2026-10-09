#!/usr/bin/env python3
"""Phase 7D Session 2: gate, then launch 7 detached apps (think first)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.budget import estimate_modal_usd, preflight, spent_modal_usd  # noqa: E402
from rc.config import repo_root  # noqa: E402
from rc.guards import assert_modal_workspace, check_modal_hf_secret  # noqa: E402
from rc.h3_dedup import load_dedup_map  # noqa: E402
from rc.io_utils import git_sha  # noqa: E402
from rc.phase7b import MODAL_CAP_USD, gpu_for_config  # noqa: E402
from rc.phase7d import budget_gate_7d  # noqa: E402

# Longest first.
LAUNCH_ORDER = (
    "qwen38_27b_think",
    "qwen38_27b_nothink",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_final",
    "olmo3_7b_dpo",
)


def reforecast(*, modal_spent: float, root: Path) -> dict:
    pre = json.loads((root / "results" / "phase7d_precheck.json").read_text())
    dmap = load_dedup_map(root)
    forecast = {}
    modal_7d = 0.0
    for cid in LAUNCH_ORDER:
        s = pre[cid]
        gpu = gpu_for_config(cid, root=root)
        pps = float(s["prompts_per_s"])
        load_s = float(s["model_load_s"])
        n_prompts = int(dmap["configs"][cid]["n_generate_prompts"])
        gen_s = n_prompts / pps
        total_s = load_s + gen_s
        cores = 8.0 if gpu == "A100-80GB" else 4.0
        mem = 64.0 if gpu == "A100-80GB" else (32.0 if gpu == "L40S" else 16.0)
        cost = estimate_modal_usd(
            gpu, int(total_s) + 1, cpu_cores=cores, memory_gib=mem, root=root
        )
        forecast[cid] = {
            "gpu": gpu,
            "n_distinct_system": dmap["configs"][cid]["n_distinct_system"],
            "n_generate_prompts": n_prompts,
            "prompts_per_s": pps,
            "model_load_s": load_s,
            "proj_generate_s": gen_s,
            "proj_total_s": total_s,
            "proj_modal_usd": cost,
            "stage_cap_1_5x": 1.5 * cost,
        }
        modal_7d += cost
    gate = budget_gate_7d(
        modal_spent=modal_spent,
        modal_proj_7d=modal_7d,
        modal_cap_usd=MODAL_CAP_USD,
        headroom_frac=0.05,
        root=root,
    )
    out = {
        "method": "one_load_plus_generate_at_measured_pps_deduped",
        "modal_spent_metered": modal_spent,
        "modal_cap_usd": MODAL_CAP_USD,
        "n_distinct_system_total": dmap["n_distinct_system_total"],
        "n_generate_prompts_total": dmap["n_generate_prompts_total"],
        "per_config": forecast,
        "modal_7d_total": modal_7d,
        "gate": gate,
    }
    (root / "results" / "phase7d_forecast.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )
    return out


def main() -> None:
    root = repo_root()
    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")

    # Metered billing
    bill = subprocess.run(
        ["uv", "run", "modal", "billing", "summary"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    modal_spent = None
    for line in (bill.stdout or "").splitlines():
        if "Metered Cost:" in line:
            modal_spent = float(line.split(":")[-1].strip())
    if modal_spent is None:
        raise SystemExit(f"could not parse modal billing:\n{bill.stdout}\n{bill.stderr}")

    fc = reforecast(modal_spent=modal_spent, root=root)
    print(json.dumps(fc["gate"], indent=2))
    if not fc["gate"]["ok"]:
        raise SystemExit("BUDGET GATE FAIL — not launching")

    # Clear kill switch
    stop = root / "runs" / "main_v1_7d" / "STOP"
    if stop.exists():
        stop.unlink()

    sha = git_sha(root) or ""
    launches = []
    for config_id in LAUNCH_ORDER:
        stage_cap = float(fc["per_config"][config_id]["stage_cap_1_5x"])
        cmd = [
            "uv",
            "run",
            "modal",
            "run",
            "--detach",
            "modal_apps/phase7d_main.py",
            "--mode",
            "config",
            "--config-id",
            config_id,
            "--stage-cap-usd",
            f"{stage_cap:.4f}",
        ]
        print("LAUNCH", " ".join(cmd))
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        print(out[-1200:])
        app_id = None
        for line in out.splitlines():
            if "ap-" in line and "modal.com/apps" in line:
                app_id = line.rstrip("/").split("/")[-1].strip()
        launches.append(
            {
                "config_id": config_id,
                "gpu": fc["per_config"][config_id]["gpu"],
                "stage_cap_usd": stage_cap,
                "app_id": app_id,
                "launch_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "returncode": proc.returncode,
            }
        )
        time.sleep(3)

    path = root / "results" / "phase7d_launches.json"
    path.write_text(json.dumps(launches, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
