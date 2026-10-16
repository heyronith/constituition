#!/usr/bin/env python3
"""Section-12 checks for the MLJ build (non-number-audit)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLJ = ROOT / "paper_mlj"
SUB = ROOT / "submission_mlj"


def pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)


def count_abstract_words(tex: str) -> int:
    m = re.search(r"\\abstract\{(.*?)\}", tex, flags=re.S)
    if not m:
        return -1
    body = m.group(1)
    body = re.sub(r"\\[A-Za-z]+(\{[^}]*\})*", " ", body)
    body = re.sub(r"[{}$\\]", " ", body)
    # Match `wc -w`: keep digit grouping commas inside numbers (2,342 = one token).
    body = re.sub(r"(?<=\d),(?=\d)", "", body)
    words = body.split()
    return len(words)


def heading_depth(tex: str) -> int:
    deepest = 0
    for cmd, depth in (("section", 1), ("subsection", 2), ("subsubsection", 3), ("paragraph", 4)):
        if re.search(rf"\\{cmd}\*?\{{", tex):
            deepest = max(deepest, depth)
    return deepest


def grep_forbidden(flat: str) -> list[str]:
    bad = []
    for needle in ("TMLR", "Anonymous", "withheld", "double-blind", r"\ifanon", r"\input{", r"\include{", "git, 2026"):
        if needle.startswith("\\"):
            if needle in flat:
                # allow TODO(author) paths only
                bad.append(needle)
        elif needle == "git, 2026":
            if re.search(r"git,\s*2026", flat):
                bad.append(needle)
        else:
            if needle in flat and "TODO(author)" not in flat[max(0, flat.find(needle) - 40) : flat.find(needle) + 40]:
                # TMLR may appear in appendix D-log historically — flag if in flattened main body before appendices
                bad.append(needle)
    return bad


def fonts_embedded(pdf: Path) -> list[str]:
    out = subprocess.check_output(["pdffonts", str(pdf)], text=True)
    lines = [ln for ln in out.splitlines()[2:] if ln.strip()]
    bad = []
    for ln in lines:
        # columns: name type emb sub uni object
        if re.search(r"\bno\b", ln):
            # emb column: look for pattern after type
            parts = ln.split()
            # Heuristic: 'yes' should appear for emb
            if "yes" not in parts:
                bad.append(ln)
    return bad


def main() -> int:
    errors: list[str] = []
    main_tex = (MLJ / "main.tex").read_text()
    # collect all section tex for heading depth
    all_tex = main_tex
    for p in (MLJ / "sections").glob("*.tex"):
        all_tex += "\n" + p.read_text()

    n_abs = count_abstract_words(main_tex)
    if not (150 <= n_abs <= 250):
        errors.append(f"abstract words={n_abs} (need 150-250)")
    if re.search(r"\\cite", re.search(r"\\abstract\{(.*?)\}", main_tex, flags=re.S).group(1)):
        errors.append("abstract contains citation")

    kws = re.search(r"\\keywords\{(.*?)\}", main_tex, flags=re.S)
    n_kw = len([k.strip() for k in kws.group(1).split(",") if k.strip()]) if kws else 0
    if not (4 <= n_kw <= 6):
        errors.append(f"keywords={n_kw} (need 4-6)")

    depth = heading_depth(all_tex)
    if depth > 3:
        errors.append(f"heading depth={depth} > 3")

    pdf = MLJ / "main.pdf"
    if pdf.exists():
        badf = fonts_embedded(pdf)
        if badf:
            errors.append(f"manuscript fonts not embedded: {badf[:3]}")
    else:
        errors.append("main.pdf missing")

    for n in range(1, 5):
        fig = MLJ / "figs" / f"Fig{n}.pdf"
        if not fig.exists():
            errors.append(f"missing {fig.name}")
            continue
        badf = fonts_embedded(fig)
        if badf:
            errors.append(f"{fig.name} fonts: {badf[:2]}")
        font_used = (MLJ / "figs" / "FONT_USED.txt").read_text().strip() if (MLJ / "figs" / "FONT_USED.txt").exists() else ""
        if font_used and font_used not in ("Arial", "Helvetica", "TeX Gyre Heros", "Nimbus Sans", "Liberation Sans"):
            # allow fuzzy Arial/Helvetica family
            if not any(x in font_used for x in ("Arial", "Helvetica", "Heros", "Nimbus", "Liberation")):
                errors.append(f"figure font unexpected: {font_used}")

    flat = SUB / "manuscript.tex"
    if flat.exists():
        ft = flat.read_text()
        for needle in ("\\input{", "\\include{", "\\ifanon", "git, 2026", "Anonymous", "double-blind", "withheld"):
            if needle in ft:
                errors.append(f"flattened tex contains {needle}")
        # Historical D-log entries may mention TMLR; flag only if outside appendix A.
        before_app = ft.split("\\begin{appendices}")[0]
        if "TMLR" in before_app:
            errors.append("flattened main-text contains TMLR")

    if errors:
        print("MLJ CHECKS FAIL:")
        for e in errors:
            print(" ", e)
        return 1
    print(
        f"MLJ CHECKS PASS: abstract={n_abs} words; keywords={n_kw}; heading_depth={depth}; fonts OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
