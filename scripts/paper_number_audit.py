#!/usr/bin/env python3
"""Audit paper/sections/*.tex for bare result digits outside macros/allowlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ROOT / "paper" / "sections"

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
    all_v = []
    for p in sorted(SECTIONS.glob("*.tex")):
        all_v.extend(audit_file(p))
    if all_v:
        print(f"NUMBER AUDIT FAIL: {len(all_v)} hit(s)")
        for v in all_v:
            print(" ", v)
        return 1
    print("NUMBER AUDIT PASS: zero bare result digits outside allowlist/macros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
