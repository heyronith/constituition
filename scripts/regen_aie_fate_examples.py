#!/usr/bin/env python3
"""Regenerate paper_aie/appendix/G_fate_examples.tex with full verbatim quotes.

Same seed (20261004) and selection rule as scripts/paper_assets.py::write_appendices
(G section), but without the former 280-character truncation. Does not touch Appendix A.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rc.config import repo_root  # noqa: E402
from rc.hazard_table import load_config_judgments  # noqa: E402
from rc.judging import normalize_fate  # noqa: E402
from rc.pilot_coding import extract_pilot_transitions  # noqa: E402

SEED = 20261004
OUT = ROOT / "paper_aie" / "appendix" / "G_fate_examples.tex"


def esc(s: object) -> str:
    return (
        str(s)
        .replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("~", "\\textasciitilde{}")
        .replace("^", "\\textasciicircum{}")
    )


def main() -> None:
    root = repo_root()
    ts = extract_pilot_transitions(
        "main_v1",
        root=root,
        forced_cumulative_rounds=(10, 20),
        permissive_cumulative_rounds=(10,),
    )
    gpt = {
        cfg: load_config_judgments(cfg, run_tag="main_v1", root=root, judge="gpt54")[0]
        for cfg in ["qwen38_27b_nothink", "gemma4_12b", "olmo3_7b_final", "qwen38_27b_think"]
    }
    by_fate: dict[str, list] = defaultdict(list)
    for t in ts:
        if t.get("protocol") != "FORCED" or t.get("kind") not in ("per_round", "per_round_absorbed"):
            continue
        tid = str(t["transition_id"])
        cfg = str(t["config_id"])
        j = gpt.get(cfg, {}).get(tid)
        if not j:
            continue
        fate = normalize_fate(j.get("fate"))
        if fate and fate != "NONE":
            by_fate[fate].append(t)

    rng = random.Random(SEED)
    lines = [
        "\\section{Fate examples}\\label{app:fate_examples}",
        f"2--3 random examples per fate (seed {SEED}), quoted verbatim.",
        "",
    ]
    for fate in sorted(by_fate):
        pool = list(by_fate[fate])
        rng.shuffle(pool)
        lines.append(f"\\subsection{{{esc(fate)}}}")
        for t in pool[:3]:
            o = t.get("original") or ""
            r = t.get("rewrite") or ""
            lines.append(
                "\\noindent\\textbf{"
                + esc(t["config_id"])
                + " / "
                + esc(t["condition"])
                + " / "
                + esc(t["item_id"])
                + f" / r{t['round']}"
                + ".}"
            )
            lines.append(f"Original: ``{esc(o)}''\\\\")
            lines.append(f"Revised: ``{esc(r)}''")
            lines.append("")
        lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
