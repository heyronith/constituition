#!/usr/bin/env python3
"""Checks for the AI and Ethics (AIE) scaffold build."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIE = ROOT / "paper_aie"

FORBIDDEN = [
    "Sharmila",
    "Agrawal",
    "heyronith",
    "github.com",
    "osf.io",
    "Southwestern Oklahoma State University",
    "Northern Kentucky University",
    "swosu",
    "nku.edu",
]


def count_abstract_words(tex: str) -> int:
    m = re.search(r"\\abstract\{(.*?)\}", tex, flags=re.S)
    if not m:
        return -1
    body = m.group(1)
    body = body.replace(r"\%", "%").replace(r"\&", "&")
    body = re.sub(r"\\[A-Za-z]+(\[[^\]]*\])?(\{[^}]*\})*", " ", body)
    body = re.sub(r"[{}]", " ", body)
    return len(body.split())


def heading_depth(tex: str) -> int:
    deepest = 0
    for cmd, depth in (("section", 1), ("subsection", 2), ("subsubsection", 3), ("paragraph", 4)):
        if re.search(rf"\\{cmd}\*?\{{", tex):
            deepest = max(deepest, depth)
    return deepest


def fonts_ok(pdf: Path) -> list[str]:
    out = subprocess.check_output(["pdffonts", str(pdf)], text=True)
    bad = []
    for ln in out.splitlines()[2:]:
        if not ln.strip():
            continue
        if "Type 3" in ln or "Type3" in ln:
            bad.append(ln)
            continue
        # Embedded column is typically near the end; require 'yes' somewhere.
        parts = ln.split()
        if "yes" not in parts:
            bad.append(ln)
    return bad


def collect_tex() -> str:
    parts = [(AIE / "main.tex").read_text(encoding="utf-8")]
    for p in sorted((AIE / "sections").glob("*.tex")):
        parts.append(p.read_text(encoding="utf-8"))
    for p in sorted((AIE / "appendix").glob("*.tex")):
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    bib = AIE / "refs.bib"
    if bib.exists():
        parts.append(bib.read_text(encoding="utf-8"))
    return "\n".join(parts)


def pending_hits() -> list[str]:
    hits = []
    for path in sorted(AIE.rglob("*.tex")):
        rel = path.relative_to(AIE).as_posix()
        if rel.startswith("template/") or path.name == "title_page.tex":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if r"\PENDING{" in line:
                hits.append(f"{rel}:{i}")
    return hits


def anon_grep() -> list[str]:
    hits = []
    # Sources (exclude title_page and template)
    for path in sorted(AIE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(AIE).as_posix()
        if rel.startswith("template/") or path.name == "title_page.tex" or path.name == "title_page.pdf":
            continue
        if path.suffix.lower() in {".pdf", ".eps", ".png", ".jpg", ".zip", ".cls", ".bst"}:
            # PDF checked via pdftotext below
            if path.suffix.lower() != ".pdf":
                continue
            if path.name not in {"main.pdf", "manuscript.pdf"}:
                continue
        if path.suffix.lower() in {".tex", ".bib", ".md", ".txt"} or path.name in {
            "main.pdf",
            "manuscript.pdf",
        }:
            if path.suffix.lower() == ".pdf" or path.name.endswith(".pdf"):
                try:
                    text = subprocess.check_output(
                        ["pdftotext", "-layout", str(path), "-"], text=True, errors="ignore"
                    )
                except Exception as e:
                    hits.append(f"{rel}: pdftotext failed: {e}")
                    continue
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
            for needle in FORBIDDEN:
                if re.search(re.escape(needle), text, flags=re.I):
                    # Find a short context
                    m = re.search(re.escape(needle), text, flags=re.I)
                    ctx = text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
                    hits.append(f"{rel}: {needle!r} :: {ctx}")
    return hits


def main() -> int:
    errors: list[str] = []
    main_tex = (AIE / "main.tex").read_text(encoding="utf-8")
    all_tex = collect_tex()

    n_abs = count_abstract_words(main_tex)
    print(f"abstract_words={n_abs}")
    if not (150 <= n_abs <= 250):
        errors.append(f"abstract word count {n_abs} not in 150–250")

    # Keywords
    km = re.search(r"\\keywords\{(.*?)\}", main_tex, flags=re.S)
    if not km:
        errors.append("missing keywords")
    else:
        kws = [k.strip() for k in km.group(1).split(",") if k.strip()]
        print(f"keywords={len(kws)}: {kws}")
        if len(kws) != 6:
            errors.append(f"expected 6 keywords, got {len(kws)}")

    depth = heading_depth(all_tex)
    print(f"heading_depth={depth}")
    if depth > 3:
        errors.append(f"heading depth {depth} > 3")

    # Numbered citation style class option
    if "sn-mathphys-num" not in main_tex:
        errors.append("main.tex missing sn-mathphys-num")

    pdf = AIE / "manuscript.pdf"
    if not pdf.exists():
        pdf = AIE / "main.pdf"
    if not pdf.exists():
        errors.append("missing manuscript PDF")
    else:
        bad_fonts = fonts_ok(pdf)
        if bad_fonts:
            errors.append("font issues:\n" + "\n".join(bad_fonts[:10]))
        else:
            print("pdffonts: OK (no Type 3; embedded)")

        # Undefined citations/refs from log
        log = (AIE / "main.log").read_text(errors="ignore") if (AIE / "main.log").exists() else ""
        if "Citation" in log and "undefined" in log.lower():
            undef = [ln for ln in log.splitlines() if "Citation" in ln and "undefined" in ln.lower()]
            if undef:
                errors.append("undefined citations:\n" + "\n".join(undef[:20]))
        if "Reference" in log and "undefined" in log.lower():
            undef = [ln for ln in log.splitlines() if "Reference" in ln and "undefined" in ln.lower()]
            if undef:
                errors.append("undefined references:\n" + "\n".join(undef[:20]))

        pages = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
        for ln in pages.splitlines():
            if ln.startswith("Pages:"):
                print(ln)

    pend = pending_hits()
    print(f"PENDING_count={len(pend)}")
    for h in pend:
        print(" ", h)
    if len(pend) != 0:
        errors.append(f"expected 0 \\PENDING, got {len(pend)}")

    anon = anon_grep()
    print(f"anon_hits={len(anon)}")
    for h in anon[:30]:
        print(" ", h)
    if anon:
        errors.append(f"anonymisation grep: {len(anon)} hit(s)")

    if errors:
        print("AIE CHECKS FAIL:")
        for e in errors:
            print(" -", e)
        return 1
    print("AIE CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
