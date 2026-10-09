#!/usr/bin/env python3
"""Blinded label-permuted dry run of frozen confirmatory R code (Phase 7E-A §4)."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import subprocess
import time
from pathlib import Path
from typing import Any

from rc.config import repo_root

MASTER_SEED = 20261004
HAZARD_PERMUTE_CATS = frozenset({"COR", "AGENT"})
BATTERY_PERMUTE_CONS = frozenset({"R0", "COR_swap", "AGENT_swap"})


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:  # type: ignore[arg-type]
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in fieldnames})


def permute_hazard(rows: list[dict[str, str]], seed: int = MASTER_SEED) -> list[dict[str, str]]:
    rng = random.Random(seed)
    # Within each chain (config, condition, chain): permute category among COR/AGENT rows
    # Keep row identity; only shuffle labels on those rows (same item across rounds shares category —
    # permute at item level within chain).
    by_chain: dict[tuple[str, str, str], list[str]] = {}
    item_cat: dict[tuple[str, str, str, str], str] = {}
    for r in rows:
        key = (r["config"], r["condition"], r["chain"])
        item = r["item_id"]
        cat = r["category"]
        if cat in HAZARD_PERMUTE_CATS:
            ik = (*key, item)
            if ik not in item_cat:
                item_cat[ik] = cat
                by_chain.setdefault(key, []).append(item)
    # Build permutation of categories for items in each chain
    mapping: dict[tuple[str, str, str, str], str] = {}
    for key, items in by_chain.items():
        cats = [item_cat[(*key, it)] for it in items]
        rng.shuffle(cats)
        for it, cat in zip(items, cats, strict=True):
            mapping[(*key, it)] = cat
    out = []
    for r in rows:
        nr = dict(r)
        ik = (r["config"], r["condition"], r["chain"], r["item_id"])
        if ik in mapping:
            nr["category"] = mapping[ik]
        out.append(nr)
    return out


def permute_battery(rows: list[dict[str, str]], seed: int = MASTER_SEED) -> list[dict[str, str]]:
    rng = random.Random(seed)
    # Within (config, chain): permute constitution among R0/COR_swap/AGENT_swap rows
    # Group by (config, chain, constitution) blocks — permute labels across those three types
    # at the row level within each (config, chain), preserving counts.
    by_cc: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(rows):
        if r.get("constitution") in BATTERY_PERMUTE_CONS:
            chain = str(r.get("chain") or "")
            by_cc.setdefault((r["config"], chain), []).append(i)
    out = [dict(r) for r in rows]
    for (_cfg, _ch), idxs in by_cc.items():
        labels = [out[i]["constitution"] for i in idxs]
        rng.shuffle(labels)
        for i, lab in zip(idxs, labels, strict=True):
            out[i]["constitution"] = lab
    return out


def extract_methods(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull estimation method / fallback only — no estimates."""
    hyp = payload.get("hypotheses") or payload
    h1 = hyp.get("H1") or hyp.get("h1") or {}
    h2 = hyp.get("H2") or hyp.get("h2") or {}
    h3 = hyp.get("H3") or hyp.get("h3") or {}
    out: dict[str, Any] = {
        "H1": {"method": h1.get("method"), "fallback_log": h1.get("fallback_log")},
        "H2a": {
            "method": (h2.get("H2a") or {}).get("method"),
            "fallback_log": (h2.get("H2a") or {}).get("fallback_log"),
        },
        "H2b": {
            "method": (h2.get("H2b") or {}).get("method"),
            "fallback_log": (h2.get("H2b") or {}).get("fallback_log"),
        },
        "H3": {"method": h3.get("method"), "fallback_log": h3.get("fallback_log")},
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hazard", type=Path, default=None)
    parser.add_argument("--battery", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    root = repo_root()
    hazard_path = args.hazard or (root / "results" / "hazard_table_main_v1.csv.gz")
    battery_path = args.battery or (root / "results" / "battery_b1_main_v1.csv.gz")
    out_json = args.out or (root / "results" / "dryrun_permuted.json")

    h_fields, h_rows = _read_csv(hazard_path)
    b_fields, b_rows = _read_csv(battery_path)
    h_perm = permute_hazard(h_rows)
    b_perm = permute_battery(b_rows)

    h_out = root / "results" / "hazard_table_main_v1_permuted.csv"
    b_out = root / "results" / "battery_b1_main_v1_permuted.csv"
    _write_csv(h_out, h_fields, h_perm)
    _write_csv(b_out, b_fields, b_perm)

    t0 = time.time()
    md_out = root / "results" / "dryrun_permuted_table.md"
    proc = subprocess.run(
        [
            "Rscript",
            "analysis/confirmatory/run_confirmatory.R",
            "--hazard",
            str(h_out),
            "--battery",
            str(b_out),
            "--out",
            str(out_json),
            "--md",
            str(md_out),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    status: dict[str, Any] = {
        "completed": proc.returncode == 0,
        "returncode": proc.returncode,
        "runtime_s": round(elapsed, 3),
        "hazard_permuted": str(h_out),
        "battery_permuted": str(b_out),
        "out": str(out_json),
        "stderr_tail": (proc.stderr or "")[-4000:],
        "stdout_tail": (proc.stdout or "")[-2000:],
    }
    if out_json.exists():
        try:
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            status["methods"] = extract_methods(payload)
            # Rewrite out_json to methods-only for blinding (keep full under .full.json)
            full = out_json.with_suffix(".full.json")
            full.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            out_json.write_text(
                json.dumps(
                    {
                        "completed": True,
                        "runtime_s": status["runtime_s"],
                        "methods": status["methods"],
                        "note": "Estimates redacted for blinding (D55/D73). Full payload in .full.json local only.",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        except json.JSONDecodeError as exc:
            status["completed"] = False
            status["json_error"] = str(exc)
    else:
        status["completed"] = False
        status["error"] = "no output json"

    status_path = root / "results" / "dryrun_permuted_status.json"
    # Strip any estimate-like keys if present in stderr parsing — keep status only
    safe = {
        "completed": status["completed"],
        "returncode": status["returncode"],
        "runtime_s": status["runtime_s"],
        "methods": status.get("methods"),
        "stderr_has_content": bool(status.get("stderr_tail")),
        "error": status.get("error") or status.get("json_error"),
    }
    # Keep stderr for debugging failures only
    if not status["completed"]:
        safe["stderr_tail"] = status.get("stderr_tail")
        safe["stdout_tail"] = status.get("stdout_tail")
    status_path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(safe, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
