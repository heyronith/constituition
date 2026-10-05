"""Run on Colab via `colab exec -f`. Tar rc-runs for download."""

from __future__ import annotations

import subprocess

subprocess.check_call(["tar", "-czf", "/content/rc-runs-phase2b.tgz", "-C", "/content", "rc-runs"])
print("TAR_OK")
