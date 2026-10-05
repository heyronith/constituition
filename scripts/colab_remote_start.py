"""Run on Colab via `colab exec -f`. Starts generation in the background."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

CONFIGS = os.environ.get("RC_CONFIGS", "olmo3_7b_sft olmo3_7b_dpo olmo3_7b_final").split()
MODE = os.environ.get("RC_MODE", "dryrun")
PHASE = os.environ.get("RC_PHASE", "3" if MODE != "dryrun" else "2")
RUN_TAG = os.environ.get("RC_RUN_TAG", "")


def main() -> None:
    token_path = Path("/content/rc-runs/.hf_token")
    if not token_path.exists():
        raise SystemExit("missing /content/rc-runs/.hf_token; run setup first")
    env = os.environ.copy()
    env["HF_TOKEN"] = token_path.read_text(encoding="utf-8").strip()
    pp = Path("/content/rc-runs/pythonpath")
    src = pp.read_text(encoding="utf-8").strip() if pp.exists() else "/content/constituition/src"
    env["PYTHONPATH"] = src + ((":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    out = Path("/content/rc-runs")
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python",
        "scripts/colab_run.py",
        "--configs",
        *CONFIGS,
        "--phase",
        PHASE,
        "--mode",
        MODE,
        "--out-root",
        "/content/rc-runs",
        "--repo-root",
        "/content/constituition",
    ]
    if RUN_TAG:
        cmd.extend(["--run-tag", RUN_TAG])
    if MODE == "olmo_check":
        cmd.extend(["--skip-endorsement", "--skip-realism"])
    log = out / "job.log"
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            cmd,
            cwd="/content/constituition",
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (out / "job.pid").write_text(str(proc.pid) + "\n", encoding="utf-8")
    print(f"STARTED pid={proc.pid} mode={MODE}", flush=True)


if __name__ == "__main__":
    main()
