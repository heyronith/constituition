"""Run on Colab via `colab exec -f`. Clones repo and installs deps."""

from __future__ import annotations

import os
import subprocess
import sys

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
    run([sys.executable, "-m", "pip", "-q", "install", "-e", "."])
    run(["mkdir", "-p", "/content/rc-runs"])
    # Persist token for the background job without printing it.
    Path = __import__("pathlib").Path
    Path("/content/rc-runs/.hf_token").write_text(token, encoding="utf-8")
    print("SETUP_OK", flush=True)


if __name__ == "__main__":
    main()
