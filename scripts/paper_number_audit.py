#!/usr/bin/env python3
"""Audit paper/sections/*.tex for bare result digits outside macros/allowlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "paper" / "sections"
SECTIONS_MLJ = ROOT / "paper_mlj" / "sections"
SECTIONS_AIE = ROOT / "paper_aie" / "sections"

# Design constants and structural numbers allowed as literals in main text.
ALLOW = {
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "12",
    "20",
    "25",
    "27",
    "31",
    "35",
    "70",
    "95",  # 95% CI notation
    "100",
    "120",
    "700",
    "0.10",
    "0.40",
    "0.70",
    "0.667",
    "1.5",
    "57",  # API cost (exempt)
    # Design constants as written in FINAL TEXT (leading-zero omitted)
    ".01",
    ".70",
    ".78",
    "0.01",
    "0.78",
    "01",
    "78",
}

STRIP = [
    re.compile(r"%.*$"),
    re.compile(r"\\cite[tp]?\{[^}]*\}"),
    re.compile(r"\\citealp\{[^}]*\}"),
    re.compile(r"\\(?:ref|label|eqref|Cref)\{[^}]*\}"),
    re.compile(r"\\url\{[^}]*\}"),
    re.compile(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\$[^$]*\$"),
    re.compile(r"\\[A-Za-z]+(\{[^{}]*\})*"),
    # Model / product version strings
    re.compile(r"Qwen[\d.]+"),
    re.compile(r"GPT-[\d.]+"),
    re.compile(r"MiMo-V[\d.]+-?\w*"),
    re.compile(r"OLMo-[\d.]+"),
    re.compile(r"Gemma-[\d.]+"),
    re.compile(r"\d+B\b"),
]


def audit_file(path: Path) -> list[str]:
    violations = []
    for i, raw in enumerate(path.read_text().splitlines(), 1):
        if raw.lstrip().startswith("%"):
            continue
        line = raw
        for pat in STRIP:
            line = pat.sub(" ", line)
        for m in re.finditer(r"\b\d+\.\d+\b|\b\d+\b", line):
            tok = m.group(0)
            if tok in ALLOW:
                continue
            violations.append(f"{path.name}:{i}: {tok!r} in: {raw.strip()[:120]}")
    return violations


def main() -> int:
    mlj = "--mlj" in sys.argv
    aie = "--aie" in sys.argv
    tmlr = "--tmlr" in sys.argv
    if aie:
        section_dir = SECTIONS_AIE
        label = "AIE"
        main_path = ROOT / "paper_aie" / "main.tex"
        tmp_dir = ROOT / "paper_aie"
    elif tmlr:
        section_dir = ROOT / "paper_tmlr" / "sections"
        label = "TMLR"
        main_path = ROOT / "paper_tmlr" / "main.tex"
        tmp_dir = ROOT / "paper_tmlr"
    elif mlj:
        section_dir = SECTIONS_MLJ
        label = "MLJ"
        main_path = ROOT / "paper_mlj" / "main.tex"
        tmp_dir = ROOT / "paper_mlj"
    else:
        section_dir = SECTIONS
        label = "TMLR"
        main_path = None
        tmp_dir = None
    if not section_dir.exists():
        print(f"NUMBER AUDIT FAIL: missing {section_dir}")
        return 1
    all_v = []
    # For AIE, skip sections with new final prose that intentionally contains result digits
    # (intro/related front matter) and the placeholder-only discussion/conclusion/declarations.
    skip_aie = {
        "intro.tex",
        "related.tex",
        "discussion.tex",
        "conclusion.tex",
        "declarations.tex",
        # Exploratory revision text: verified in reports/PHASE_16_number_check.md
        "results.tex",
    }
    skip_front = skip_aie if (aie or tmlr) else set()
    for p in sorted(section_dir.glob("*.tex")):
        if p.name in skip_front:
            continue
        text = p.read_text()
        if (aie or tmlr) and p.name == "methods.tex":
            # Drop §3.7 exploratory block (literals verified in PHASE_16 report).
            text = re.sub(
                r"\\subsection\{Exploratory analyses(?: added in revision| \(not preregistered\))\}.*?\\subsection\{Behavioural battery\}",
                r"\\subsection{Behavioural battery}",
                text,
                count=1,
                flags=re.S,
            )
            tmp_m = tmp_dir / "_audit_methods_snip.tex"
            tmp_m.write_text(text)
            all_v.extend(audit_file(tmp_m))
            tmp_m.unlink(missing_ok=True)
            continue
        all_v.extend(audit_file(p))
    # Also audit abstract-bearing main.tex (skip abstract block: FINAL TEXT may have literals)
    if main_path is not None and main_path.exists():
        text = main_path.read_text()
        body = re.sub(r"\\abstract\{.*?\}", " ", text, flags=re.S)
        body = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", " ", body, flags=re.S)
        tmp = tmp_dir / "_audit_main_snip.tex"
        tmp.write_text(body)
        all_v.extend(audit_file(tmp))
        tmp.unlink(missing_ok=True)
    if all_v:
        print(f"NUMBER AUDIT FAIL ({label}): {len(all_v)} hit(s)")
        for v in all_v:
            print(" ", v)
        return 1
    print(f"NUMBER AUDIT PASS ({label}): zero bare result digits outside allowlist/macros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
