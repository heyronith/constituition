"""Build materials/main_run/h3_constitutions.json from Volume main_v1 chains."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import modal

app = modal.App("rc-build-h3-manifest")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("pydantic>=2", "pyyaml", "python-dotenv")
    .add_local_dir("src", remote_path="/rc/src")
    .add_local_dir("configs", remote_path="/rc/configs")
    .add_local_dir("materials", remote_path="/rc/materials")
    .add_local_file("pyproject.toml", remote_path="/rc/pyproject.toml")
)
vol = modal.Volume.from_name("rc-runs")


@app.function(image=image, volumes={"/vol": vol}, timeout=1800, memory=8192)
def build() -> dict:
    import os
    import sys

    runs = Path("/rc/runs")
    if runs.exists() or runs.is_symlink():
        if runs.is_symlink() or runs.is_file():
            runs.unlink()
        else:
            shutil.rmtree(runs)
    runs.symlink_to("/vol")
    os.chdir("/rc")
    sys.path.insert(0, "/rc/src")
    from rc.h3_constitutions import CONFIGS_7, build_manifest

    payload = build_manifest("main_v1", root=Path("/rc"), config_ids=CONFIGS_7)
    out = Path("/vol/main_v1/h3_constitutions.json")
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # summary without clause texts (blinding-safe operational)
    summary = {"n": payload["n_constitutions"], "by_config": {}}
    for cid in CONFIGS_7:
        rows = [c for c in payload["constitutions"] if c["config_id"] == cid]
        types = Counter(c["type"] for c in rows)
        n_early = sum(
            1
            for c in rows
            if c.get("r_final") is not None and int(c["r_final"]) < 20 and c["type"] != "R0"
        )
        swaps = [
            {
                "constitution_id": c["constitution_id"],
                "type": c["type"],
                "n_changed_vs_r0": c.get("n_changed_vs_r0"),
                "r_final": c.get("r_final"),
            }
            for c in rows
            if c["type"] in {"COR_SWAP", "AGENT_SWAP"}
        ]
        summary["by_config"][cid] = {
            "n": len(rows),
            "types": dict(types),
            "n_r_final_lt_20": n_early,
            "swaps": swaps,
        }
    Path("/vol/main_v1/h3_constitutions_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    vol.commit()
    return summary


@app.local_entrypoint()
def main() -> None:
    summary = build.remote()
    Path("results/phase7d_h3_manifest_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    # pull full manifest into materials/
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "h3_constitutions.json"
        subprocess.run(
            [
                "modal",
                "volume",
                "get",
                "rc-runs",
                "main_v1/h3_constitutions.json",
                str(dest),
                "--force",
            ],
            check=True,
        )
        target = Path("materials/main_run/h3_constitutions.json")
        target.write_bytes(dest.read_bytes())
    print(json.dumps(summary, indent=2)[:4000])
    print("wrote", "materials/main_run/h3_constitutions.json")
