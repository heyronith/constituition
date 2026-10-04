#!/usr/bin/env python3
"""Resolve Hugging Face repo SHAs without downloading weight shards."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env", override=False)

from rc.hf_registry import collect_lockfile  # noqa: E402


def main() -> int:
    token = os.environ.get("HF_TOKEN")
    if not token:
        print(
            "HF_TOKEN missing; cannot resolve gated repos. Refusing to guess IDs.",
            file=sys.stderr,
        )
        return 1
    data = collect_lockfile(token=token)
    out = ROOT / "configs" / "model_revisions.lock.yaml"
    out.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"wrote {out.relative_to(ROOT)}")
    n_unresolved = 0
    for role in ("subjects", "judges"):
        for row in data[role]:
            ident = row.get("config_id") or row.get("judge_id")
            status = row["status"]
            sha = (row.get("sha") or "")[:12]
            fit = row.get("fit") or {}
            flag = fit.get("flag")
            extra = f" fit_flag={flag}" if flag else ""
            print(f"  {role[:-1]:7} {ident:24} {status:12} {row.get('exact_repo_id')} {sha}{extra}")
            if status != "OK":
                n_unresolved += 1
                if row.get("candidates"):
                    print(f"           candidates: {row['candidates']}")
    return 1 if n_unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
