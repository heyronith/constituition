"""Run verify_h3_swaps against Modal Volume main_v1 (authoritative)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import modal

app = modal.App("rc-verify-h3-swaps")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("pydantic>=2", "pyyaml", "python-dotenv")
    .add_local_dir("src", remote_path="/rc/src")
    .add_local_dir("configs", remote_path="/rc/configs")
    .add_local_dir("materials", remote_path="/rc/materials")
    .add_local_file("scripts/verify_h3_swaps.py", remote_path="/rc/scripts/verify_h3_swaps.py")
    .add_local_file("pyproject.toml", remote_path="/rc/pyproject.toml")
)
vol = modal.Volume.from_name("rc-runs")


@app.function(image=image, volumes={"/vol": vol}, timeout=1800, memory=8192)
def run() -> dict:
    import os
    import sys

    runs = Path("/rc/runs")
    if runs.is_symlink() or runs.is_file():
        runs.unlink()
    elif runs.exists():
        shutil.rmtree(runs)
    runs.symlink_to("/vol")
    os.chdir("/rc")
    Path("/rc/results").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, "/rc/src")
    sys.path.insert(0, "/rc/scripts")
    import verify_h3_swaps as v

    code = v.main()
    out = Path("/rc/results/phase7d_swap_verify.json")
    payload = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    payload["exit_code"] = code
    return payload


@app.local_entrypoint()
def main() -> None:
    payload = run.remote()
    Path("results/phase7d_swap_verify.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"n={payload.get('n')} n_fail={payload.get('n_fail')} "
        f"all_pass={payload.get('all_pass')}"
    )
    if not payload.get("all_pass"):
        for r in payload.get("results") or []:
            if r.get("status") == "FAIL":
                print("FAIL", r.get("constitution_id") or r.get("reason"))
        raise SystemExit(1)
