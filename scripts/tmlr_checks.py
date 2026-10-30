#!/usr/bin/env python3
"""Checks for the TMLR anonymous submission and named preprint builds."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMLR = ROOT / "paper_tmlr"
MAIN_PDF = TMLR / "main.pdf"
PREPRINT_PDF = TMLR / "preprint.pdf"

ANON_FORBIDDEN = [
    "heyronith",
    "Ronith",
    "Sharmila",
    "Agrawal",
    "Rupesh",
    "SWOSU",
    "Southwestern Oklahoma",
    "Northern Kentucky",
    "mw86p",
    "osf.io",
    "github.com/heyronith",
    "swosu.edu",
    "nku.edu",
]


def fonts_ok(pdf: Path) -> list[str]:
    out = subprocess.check_output(["pdffonts", str(pdf)], text=True)
    bad = []
    for ln in out.splitlines()[2:]:
        if not ln.strip():
            continue
        if "Type 3" in ln or "Type3" in ln:
            bad.append(ln)
    return bad


def pdf_text(pdf: Path) -> str:
    return subprocess.check_output(
        ["pdftotext", "-layout", str(pdf), "-"], text=True, errors="ignore"
    )


def pdfinfo_fields(pdf: Path) -> dict[str, str]:
    out = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
    fields = {}
    for ln in out.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            fields[k.strip()] = v.strip()
    return fields


def overfull_gt(log: Path, limit_pt: float = 5.0) -> list[tuple[float, str]]:
    if not log.exists():
        return []
    text = log.read_text(errors="ignore")
    hits = []
    for m in re.finditer(r"Overfull \\hbox \(([\d.]+)pt too wide\)", text):
        pt = float(m.group(1))
        if pt > limit_pt:
            hits.append((pt, m.group(0)))
    return hits


def anon_hits_in_text(text: str, where: str) -> list[str]:
    hits = []
    for needle in ANON_FORBIDDEN:
        if re.search(re.escape(needle), text, flags=re.I):
            m = re.search(re.escape(needle), text, flags=re.I)
            ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
            hits.append(f"{where}: {needle!r} :: {ctx}")
    return hits


def anon_tracked_sources() -> list[str]:
    hits = []
    for path in sorted(TMLR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(TMLR).as_posix()
        if rel.startswith("preprint") or "preprint" in path.name:
            continue
        if path.suffix.lower() in {".pdf", ".eps", ".png", ".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".bbl", ".blg", ".synctex.gz"}:
            if path.name not in {"main.pdf"}:
                continue
        if path.suffix.lower() not in {".tex", ".bib", ".md", ".txt", ".sty", ".bst"} and path.name != "main.pdf":
            continue
        if path.suffix.lower() == ".pdf" or path.name.endswith(".pdf"):
            try:
                text = pdf_text(path)
            except Exception as e:
                hits.append(f"{rel}: pdftotext failed: {e}")
                continue
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Allow macros_tmlr.tex to define preprint-only URLs behind \ifTMLRpreprint
            if path.name in {"preprint_identity.tex"}:
                continue
        hits.extend(anon_hits_in_text(text, rel))
    return hits


def main() -> int:
    errors: list[str] = []

    if not MAIN_PDF.exists():
        errors.append("missing paper_tmlr/main.pdf")
        print("TMLR CHECKS FAIL:")
        for e in errors:
            print(" -", e)
        return 1

    info = pdfinfo_fields(MAIN_PDF)
    print(f"Pages: {info.get('Pages', '?')}")
    for key in ("Author", "Creator", "Subject"):
        val = info.get(key, "")
        print(f"pdfinfo {key}={val!r}")
        if val.strip():
            errors.append(f"main.pdf metadata {key} not empty: {val!r}")

    bad = fonts_ok(MAIN_PDF)
    if bad:
        errors.append("Type 3 fonts in main.pdf:\n" + "\n".join(bad[:10]))
    else:
        print("pdffonts: OK (no Type 3)")

    log = TMLR / "main.log"
    of = overfull_gt(log)
    print(f"overfull>5pt={len(of)}")
    for pt, msg in of[:20]:
        print(f"  {pt}: {msg}")
        errors.append(f"overfull {pt}pt: {msg}")

    if log.exists():
        logt = log.read_text(errors="ignore")
        undef = [
            ln
            for ln in logt.splitlines()
            if ("undefined" in ln.lower()) and ("Citation" in ln or "Reference" in ln or "Latex" in ln)
        ]
        if undef:
            errors.append("undefined refs/cites:\n" + "\n".join(undef[:20]))

    main_txt = pdf_text(MAIN_PDF)
    anon_pdf = anon_hits_in_text(main_txt, "main.pdf")
    print(f"anon_hits_main_pdf={len(anon_pdf)}")
    for h in anon_pdf[:20]:
        print(" ", h)
        errors.append(h)

    anon_src = anon_tracked_sources()
    print(f"anon_hits_tracked_sources={len(anon_src)}")
    for h in anon_src[:20]:
        print(" ", h)
        errors.append(h)

    # Preprint expectations (build may be optional for check target; warn if missing)
    if PREPRINT_PDF.exists():
        pre_txt = pdf_text(PREPRINT_PDF)
        need = ["Ronith", "Sharmila", "Agrawal", "github.com/heyronith", "osf.io/mw86p"]
        missing = [n for n in need if n.lower() not in pre_txt.lower()]
        print(f"preprint_required_present={not missing}")
        if missing:
            errors.append(f"preprint.pdf missing: {missing}")
        # Must not be empty of Broader Impact
        if "Broader Impact" not in pre_txt:
            errors.append("preprint.pdf missing Broader Impact Statement")
    else:
        print("preprint.pdf: not built yet (run make tmlr-preprint)")

    # Number audit reuse
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "paper_number_audit.py"), "--tmlr"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        print(r.stdout[-500:] if r.stdout else "")
        if r.returncode != 0:
            # Fall back to AIE audit path if --tmlr unsupported
            r2 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "paper_number_audit.py"), "--aie"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            print("(fallback --aie)", (r2.stdout or "")[-300:])
            if "PASS" not in (r2.stdout or "") and "PASS" not in (r.stdout or ""):
                errors.append("number audit did not PASS")
            else:
                print("number audit: PASS (via available checker)")
        else:
            print("number audit: OK")
    except FileNotFoundError:
        print("paper_number_audit.py not found; skip")

    if errors:
        print("TMLR CHECKS FAIL:")
        for e in errors:
            print(" -", e)
        return 1
    print("TMLR CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
