#!/usr/bin/env python3
"""Apply D59 archive: move stale suffixes; verify retained prefixes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.chain_runner import (  # noqa: E402
    archive_stale_suffix,
    find_t_stale,
    verify_chain_consistency,
)
from rc.config import repo_root  # noqa: E402


def main() -> None:
    root = repo_root()
    report = json.loads((root / "results" / "d59_forensics.json").read_text(encoding="utf-8"))
    run_tag = report["run_tag"]
    config_id = report["config_id"]
    base = root / "runs" / run_tag / config_id
    archive_root = root / "runs" / run_tag / "_invalid_d59" / "stale_suffixes"
    archived = []
    for row in report["chains"]:
        t = row["t_stale"]
        if t is None:
            continue
        chain_dir = base / row["chain_path"]
        counts = archive_stale_suffix(
            chain_dir, int(t), archive_root, rel_path=row["chain_path"], root=root
        )
        # Retained prefix must be clean
        assert find_t_stale(chain_dir, root=root) is None, row["chain_path"]
        v = verify_chain_consistency(chain_dir, root=root)
        # input_constitution_sha256 may be absent on old rounds — ignore those errors
        bad = [
            e
            for e in v["errors"]
            if "prompt_sha256" in e or "duplicate" in e or "gaps" in e or "ParseError" in e
        ]
        if bad:
            raise SystemExit(f"prefix verify failed {row['chain_path']}: {bad}")
        archived.append({"chain": row["chain_path"], "t_stale": t, "counts": counts})

    out = {
        "n_archived": len(archived),
        "archive_root": str(archive_root.relative_to(root)),
        "archived": archived,
    }
    out_path = root / "results" / "d59_archive.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"n_archived": len(archived)}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
