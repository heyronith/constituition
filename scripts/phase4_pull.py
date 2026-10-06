#!/usr/bin/env python3
"""Pull Phase 4 outputs from Modal Volume rc-runs into local runs/ and reports/."""

from __future__ import annotations

import shutil
import subprocess

from rc.config import repo_root


def main() -> None:
    root = repo_root()
    tmp = root / "runs" / "_pull_phase4"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    cmd = ["modal", "volume", "get", "rc-runs", "phase4", str(tmp), "--force"]
    print(" ".join(cmd))
    subprocess.check_call(cmd)

    src = tmp / "phase4" if (tmp / "phase4").exists() else tmp
    dest = root / "runs" / "phase4"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    # Append pending ledger rows not already present (idempotent on re-pull).
    ledger = root / "budget" / "ledger.jsonl"
    existing = set()
    if ledger.exists():
        existing = {
            line.strip()
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    for name in ("ledger_pending.jsonl", "ledger_pending_active.jsonl"):
        pending = dest / name
        if not pending.exists() or pending.stat().st_size == 0:
            continue
        n_new = 0
        with ledger.open("a", encoding="utf-8") as out, pending.open(encoding="utf-8") as inp:
            for line in inp:
                stripped = line.strip()
                if not stripped or stripped in existing:
                    continue
                out.write(stripped + "\n")
                existing.add(stripped)
                n_new += 1
        print(f"appended {n_new} new rows from {pending} → {ledger}")

    # Copy key summaries into reports/
    for name in (
        "selection_d33.json",
        "calibration_metrics.json",
        "pilot_coding_summary.json",
        "power_table.json",
        "g4_projection.json",
        "STATUS.json",
    ):
        p = dest / name
        if p.exists():
            target = root / "reports" / f"phase4_{name}"
            shutil.copy2(p, target)
            print(f"copied {p} → {target}")
    print("done", dest)


if __name__ == "__main__":
    main()
