"""Run on Colab via `colab exec -f`. Prints status.json (or {})."""

from __future__ import annotations

from pathlib import Path

path = Path("/content/rc-runs/status.json")
if path.exists():
    print(path.read_text(encoding="utf-8"), end="")
else:
    print("{}")
