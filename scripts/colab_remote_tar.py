"""Run on Colab via `colab exec -f`. Tar rc-runs for download."""

from __future__ import annotations

import os
import subprocess

TAR_NAME = os.environ.get("RC_TAR_NAME", "rc-runs-out.tgz")
subprocess.check_call(["tar", "-czf", f"/content/{TAR_NAME}", "-C", "/content", "rc-runs"])
print(f"TAR_OK {TAR_NAME}")
