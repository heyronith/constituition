#!/usr/bin/env python3
"""One-shot Phase 7 STATUS.json reader (no loop). D55."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-tag",
        default="main_v1",
        help="Volume path prefix under rc-runs/ (default main_v1; canary uses main_v1 too)",
    )
    parser.add_argument(
        "--local",
        type=Path,
        default=None,
        help="If set, read STATUS.json from this local path instead of Modal volume",
    )
    args = parser.parse_args()

    if args.local is not None:
        status_path = args.local
        if not status_path.exists():
            raise SystemExit(f"missing {status_path}")
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "STATUS.json"
            remote = f"{args.run_tag}/STATUS.json"
            proc = subprocess.run(
                ["modal", "volume", "get", "rc-runs", remote, str(dest), "--force"],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0 or not dest.exists():
                print(f"STATUS.json not found on volume rc-runs:/{remote}")
                print(proc.stderr or proc.stdout)
                raise SystemExit(1)
            payload = json.loads(dest.read_text(encoding="utf-8"))

    print(json.dumps(payload, indent=2, sort_keys=True))
    from rc.phase7_status import summarize_status

    print("\n" + summarize_status(payload))


if __name__ == "__main__":
    main()
