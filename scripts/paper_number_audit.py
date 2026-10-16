#!/usr/bin/env python3
"""Audit paper/sections/*.tex for bare result digits outside macros/allowlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "paper" / "sections"
SECTIONS_MLJ = ROOT / "paper_mlj" / "sections"

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
    section_dir = SECTIONS_MLJ if mlj else SECTIONS
    label = "MLJ" if mlj else "TMLR"
    if not section_dir.exists():
        print(f"NUMBER AUDIT FAIL: missing {section_dir}")
        return 1
    all_v = []
    for p in sorted(section_dir.glob("*.tex")):
        all_v.extend(audit_file(p))
    # Also audit MLJ abstract in main.tex (contains bare result digits by design in FINAL TEXT)
    if mlj:
        main_tex = ROOT / "paper_mlj" / "main.tex"
        if main_tex.exists():
            # Abstract is source-of-truth prose with literals; skip abstract block only.
            text = main_tex.read_text()
            # Audit non-abstract body of main.tex (front matter macros only)
            body = re.sub(r"\\abstract\{.*?\}", " ", text, flags=re.S)
            tmp = ROOT / "paper_mlj" / "_audit_main_snip.tex"
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
