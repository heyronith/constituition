"""Run on Colab via `colab exec -f`. Assert L4 and print GPU name."""

from __future__ import annotations

import subprocess

out = subprocess.check_output(
    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
).strip()
print(out)
if "L4" not in out:
    raise SystemExit(f"expected L4 GPU, got: {out}")
