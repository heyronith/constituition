#!/usr/bin/env python3
"""Tabulate parse-failure reasons by config × protocol × condition (Phase 2B)."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from rc.config import repo_root

DEFAULT_RUN_TAG = "phase2b_dryrun"
N_EXAMPLES = 3


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def collect(run_tag: str, root: Path) -> list[dict]:
    base = root / "runs" / run_tag
    rows: list[dict] = []
    if not base.exists():
        return rows
    for path in base.rglob("rounds.jsonl"):
        parts = path.relative_to(base).parts
        # config / protocol / condition / fmt / chain_N / rounds.jsonl
        if len(parts) < 5:
            continue
        config_id, protocol, condition = parts[0], parts[1], parts[2]
        for row in _load_jsonl(path):
            rows.append(
                {
                    "config_id": config_id,
                    "protocol": protocol,
                    "condition": condition,
                    "fmt": parts[3],
                    "chain": parts[4],
                    "round": row.get("round"),
                    "attempt": row.get("attempt"),
                    "parse_status": row.get("parse_status"),
                    "parse_error": row.get("parse_error"),
                    "text_final": row.get("text_final") or "",
                }
            )
    return rows


def reason_key(err: str | None) -> str:
    if not err:
        return "(none)"
    text = err.strip().splitlines()[0]
    # Collapse opaque IDs / quotes for grouping.
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch in " _-.:":
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    words = " ".join("".join(cleaned).split())
    return words[:120] if words else text[:120]


def render_table(rows: list[dict]) -> str:
    fails = [r for r in rows if r.get("parse_status") != "ok"]
    lines: list[str] = []
    lines.append(f"Total round-attempts: {len(rows)}; parse failures: {len(fails)}\n")

    by_cell: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in fails:
        by_cell[(r["config_id"], r["protocol"], r["condition"])].append(r)

    for key in sorted(by_cell):
        config_id, protocol, condition = key
        cell = by_cell[key]
        reasons = Counter(reason_key(r.get("parse_error")) for r in cell)
        n_all = sum(
            1
            for r in rows
            if r["config_id"] == config_id
            and r["protocol"] == protocol
            and r["condition"] == condition
        )
        lines.append(
            f"### {config_id} | {protocol} | {condition}  "
            f"(failures {len(cell)} / {n_all} attempts)\n"
        )
        lines.append("| reason | n |")
        lines.append("|---|---|")
        for reason, n in reasons.most_common():
            lines.append(f"| `{reason}` | {n} |")
        lines.append("")
        lines.append("Examples:")
        for ex in cell[:N_EXAMPLES]:
            snippet = (ex.get("text_final") or "").replace("\n", "\\n")[:240]
            lines.append(
                f"- chain={ex['chain']} round={ex['round']} attempt={ex['attempt']}: "
                f"`{ex.get('parse_error')}` · raw=`{snippet}`"
            )
        lines.append("")
    if not fails:
        lines.append("_No parse failures in this run tag._\n")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tag", default=DEFAULT_RUN_TAG)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or repo_root()
    rows = collect(args.run_tag, root)
    print(render_table(rows))


if __name__ == "__main__":
    main()
