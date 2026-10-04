"""Local entrypoint for the D23 L4 tiny-model smoke.

The remote function lives in `generate.py` so the Modal worker does not need
the `modal_apps` package (which is not installed in the container).

Usage:
  PYTHONPATH=src modal run modal_apps/generate.py::smoke
  # or:
  PYTHONPATH=src python -m modal_apps.smoke_l4
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        "-m",
        "modal",
        "run",
        str(root / "modal_apps" / "generate.py") + "::smoke",
    ]
    env = {**dict(**__import__("os").environ), "PYTHONPATH": str(root / "src")}
    return subprocess.call(cmd, cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
