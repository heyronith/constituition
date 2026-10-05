#!/usr/bin/env python3
"""Print Phase 4 detached-pipeline STATUS.json from the rc-runs Modal Volume."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "phase4"
        dest.mkdir()
        # Prefer volume get of the status file only.
        cmd = [
            "modal",
            "volume",
            "get",
            "rc-runs",
            "phase4/STATUS.json",
            str(dest / "STATUS.json"),
            "--force",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        status_path = dest / "STATUS.json"
        if proc.returncode != 0 or not status_path.exists():
            print("STATUS.json not found on volume rc-runs:/phase4/STATUS.json")
            print(proc.stderr or proc.stdout)
            raise SystemExit(1)
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(
            f"\nstage={payload.get('stage')} state={payload.get('state')} "
            f"spend_usd={payload.get('spend_usd')}"
        )


if __name__ == "__main__":
    main()
