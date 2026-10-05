"""Run on Colab via `colab exec -f`. Clones repo and installs deps."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_URL = os.environ.get("RC_REPO_URL", "https://github.com/heyronith/constituition.git")
GIT_SHA = os.environ.get("RC_GIT_SHA", "main")
VLLM_VERSION = os.environ.get("RC_VLLM_VERSION", "0.30.0")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN missing in Colab env")
    os.chdir("/content")
    run(["rm", "-rf", "constituition"])
    run(["git", "clone", REPO_URL, "constituition"])
    os.chdir("/content/constituition")
    run(["git", "checkout", GIT_SHA])
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "-q",
            "install",
            f"vllm=={VLLM_VERSION}",
            "pydantic",
            "pyyaml",
            "python-dotenv",
            "textstat",
            "huggingface_hub",
        ]
    )
    # Editable install is flaky on Colab; put src on PYTHONPATH instead.
    run(["mkdir", "-p", "/content/rc-runs"])
    Path("/content/rc-runs/.hf_token").write_text(token, encoding="utf-8")
    Path("/content/rc-runs/pythonpath").write_text("/content/constituition/src\n", encoding="utf-8")
    print("SETUP_OK", flush=True)


def start_job() -> None:
    """Start the dry-run in the same kernel session (avoids a second exec)."""
    configs = os.environ.get("RC_CONFIGS", "olmo3_7b_sft olmo3_7b_dpo olmo3_7b_final").split()
    token = Path("/content/rc-runs/.hf_token").read_text(encoding="utf-8").strip()
    env = os.environ.copy()
    env["HF_TOKEN"] = token
    env["PYTHONPATH"] = "/content/constituition/src" + (
        (":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""
    )
    out = Path("/content/rc-runs")
    log = out / "job.log"
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                sys.executable,
                "scripts/colab_run.py",
                "--configs",
                *configs,
                "--phase",
                "2",
                "--out-root",
                "/content/rc-runs",
                "--repo-root",
                "/content/constituition",
            ],
            cwd="/content/constituition",
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (out / "job.pid").write_text(str(proc.pid) + "\n", encoding="utf-8")
    print(f"STARTED pid={proc.pid}", flush=True)


if __name__ == "__main__":
    main()
    start_job()
