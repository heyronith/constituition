#!/usr/bin/env python3
"""SECONDARY (preregistered §6.9): Study 1 PERMISSIVE descriptives."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.hazard_table import MAIN_CONFIGS, load_config_judgments
from rc.judging import normalize_fate
from rc.pilot_coding import extract_pilot_transitions

LABEL = "SECONDARY (preregistered)"
OUT = Path("results/secondary/study1_permissive.json")
CONDS = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
CATS = ["COR", "AGENT", "SELF", "HON", "HARM", "CARE", "PROC"]


def main() -> None:
    root = repo_root()
    run_tag = "main_v1"
    transitions = extract_pilot_transitions(
        run_tag,
        root=root,
        forced_cumulative_rounds=(),
        permissive_cumulative_rounds=(10,),
    )
    # Keep PERMISSIVE
    ts = [t for t in transitions if t.get("protocol") == "PERMISSIVE"]

    gpt_maps = {
        cfg: load_config_judgments(cfg, run_tag=run_tag, root=root, judge="gpt54")[0]
        for cfg in MAIN_CONFIGS
    }

    # Retention / deletions / merges from lineage-style decisions on per_round
    per_round = [t for t in ts if t.get("kind") == "per_round"]
    by_cat_dec: dict[str, Counter] = defaultdict(Counter)
    for t in per_round:
        cat = str(t.get("category") or "?")
        dec = str(t.get("decision") or ("delete" if t.get("deleted") else "other"))
        by_cat_dec[cat][dec] += 1

    # Round-10 cumulative fate by category × condition
    cum10 = [t for t in ts if t.get("kind") == "cumulative" and int(t.get("round") or 0) == 10]
    fate_cc: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for t in cum10:
        tid = str(t["transition_id"])
        cfg = str(t["config_id"])
        j = gpt_maps.get(cfg, {}).get(tid)
        fate = normalize_fate(j.get("fate")) if j else None
        if fate is None:
            if t.get("deleted"):
                fate = "DELETED"
            else:
                fate = "UNCODED"
        fate_cc[str(t["condition"])][str(t["category"])][fate] += 1

    # Retention rate: among R0 items, still present at round 10 with RETAINED/STRENGTHENED/… 
    # Approximate: 1 - P(DELETED) among cumulative-10 coded items per category
    retention = {}
    for cond in CONDS:
        retention[cond] = {}
        for cat in CATS:
            c = fate_cc[cond][cat]
            n = sum(c.values())
            deleted = c.get("DELETED", 0)
            retention[cond][cat] = {
                "n_coded": n,
                "n_deleted": deleted,
                "retention_approx": (1 - deleted / n) if n else None,
                "fate": dict(c),
            }

    # Emergent (added) clauses: decision add, or lineage before_text None with new item
    adds = [t for t in per_round if str(t.get("decision")) == "add" or (t.get("kind") == "per_round" and t.get("item_id") in (None, "", "ADDED"))]
    # Also scan chain lineage for adds
    emergent_examples = []
    emergent_count = Counter()
    for cfg in MAIN_CONFIGS:
        for cond in CONDS:
            base = root / "runs" / run_tag / cfg / "PERMISSIVE" / cond / "STRUCTURED"
            if not base.exists():
                continue
            for chain_dir in sorted(base.glob("chain_*")):
                lin = chain_dir / "lineage.jsonl"
                if not lin.exists():
                    continue
                for line in lin.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if row.get("decision") != "add":
                        continue
                    text = str(row.get("after_text") or "")
                    emergent_count[(cfg, cond)] += 1
                    if len(emergent_examples) < 40:
                        emergent_examples.append(
                            {
                                "config": cfg,
                                "condition": cond,
                                "chain": chain_dir.name,
                                "round": row.get("round"),
                                "text": text[:400],
                            }
                        )

    # Simpler add count from transitions
    add_ts = [t for t in per_round if str(t.get("decision")) == "add"]
    out = {
        "label": LABEL,
        "n_permissive_transitions_extracted": len(ts),
        "n_per_round": len(per_round),
        "n_cumulative_r10": len(cum10),
        "deletions_merges_by_category": {
            cat: {
                "delete": by_cat_dec[cat].get("delete", 0),
                "merge": by_cat_dec[cat].get("merge", 0),
                "revise": by_cat_dec[cat].get("revise", 0),
                "keep": by_cat_dec[cat].get("keep", 0),
                "add": by_cat_dec[cat].get("add", 0),
                "all_decisions": dict(by_cat_dec[cat]),
            }
            for cat in CATS
        },
        "retention_and_round10_fate": retention,
        "emergent_clauses": {
            "n_add_decisions_in_transitions": len(add_ts),
            "n_lineage_adds_by_config_condition": {
                f"{a}|{b}": n for (a, b), n in sorted(emergent_count.items())
            },
            "examples": emergent_examples[:25],
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"wrote": str(OUT), "n_cum10": len(cum10), "n_adds": len(add_ts)}, indent=2))


if __name__ == "__main__":
    main()
