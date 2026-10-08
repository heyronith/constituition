#!/usr/bin/env python3
"""Launch one detached Modal app per remaining Phase 7B config (D62/D63)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.budget import preflight, spent_modal_usd  # noqa: E402
from rc.canary_checks import assert_canary_inputs, load_g4_n25  # noqa: E402
from rc.config import repo_root  # noqa: E402
from rc.guards import assert_modal_workspace, check_modal_hf_secret  # noqa: E402
from rc.io_utils import git_sha  # noqa: E402
from rc.phase7b import (  # noqa: E402
    REMAINING_CONFIGS,
    gpu_for_config,
    snapshot_canary_tree,
)


def main() -> None:
    root = repo_root()
    assert_modal_workspace(expected="heyronith")
    check_modal_hf_secret("hf-token")
    assert_canary_inputs(root=root)

    # D63 canary snapshot before any 7B write.
    snap = snapshot_canary_tree(root=root)
    snap_path = root / "results" / "canary_olmo3_7b_final_snapshot.json"
    snap_path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"canary_snapshot n_files={len(snap)} -> {snap_path}")

    g4 = load_g4_n25(root)["g4"]
    g4_per = float(g4["totals"]["modal_generation_usd"]) / 7.0
    cons_per = g4_per  # max(G4, canary-scaled) with canary < G4
    stage_cap = 1.5 * cons_per
    print(f"conservative_per_config={cons_per:.4f} stage_cap_1.5x={stage_cap:.4f}")

    sha = git_sha(root) or ""
    launches = []
    for config_id in REMAINING_CONFIGS:
        gpu = gpu_for_config(config_id, root=root)
        # Preflight wall-clock sized so estimate ≤ 1.5× conservative per-config cap.
        preflight_s = 14_000 if gpu == "A100-80GB" else 20_000
        preflight(
            gpu,
            preflight_s,
            phase="7b",
            job_id=f"phase7b-launch-{config_id}",
            hard_cap_usd=spent_modal_usd(root) + stage_cap,
            override_job_cap_usd=stage_cap,
            cpu_cores=4.0,
            memory_gib=16.0 if gpu != "A100-80GB" else 32.0,
            root=root,
        )
        cmd = [
            "uv",
            "run",
            "modal",
            "run",
            "--detach",
            "modal_apps/phase7b_main.py",
            "--mode",
            "config",
            "--config-id",
            config_id,
            "--stage-cap-usd",
            f"{stage_cap:.4f}",
        ]
        # Use spawn via python -m style: modal run entrypoint needs kwargs.
        # Prefer calling modal with env RC_GIT_SHA.
        env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "RC_GIT_SHA": sha}
        print("LAUNCH", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        print(out[-2000:])
        app_id = None
        object_id = None
        for line in out.splitlines():
            if "ap-" in line and "modal.com/apps" in line:
                app_id = line.rstrip("/").split("/")[-1].strip()
            if "object_id=" in line:
                object_id = line.split("object_id=")[-1].split()[0]
        launches.append(
            {
                "config_id": config_id,
                "gpu": gpu,
                "stage_cap_usd": stage_cap,
                "app_id": app_id,
                "object_id": object_id,
                "launch_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "returncode": proc.returncode,
            }
        )
        if proc.returncode != 0:
            print(f"WARN launch failed for {config_id}")
        time.sleep(2)

    out_path = root / "results" / "phase7b_launches.json"
    out_path.write_text(json.dumps(launches, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
