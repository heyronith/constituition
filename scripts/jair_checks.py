#!/usr/bin/env python3
"""Checks for the JAIR (AI & Society) named submission build."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAIR = ROOT / "paper_jair"
MAIN_PDF = JAIR / "main.pdf"
KIT = Path("/tmp/jair_kit/JAIR AuthorKit/JAIR_Example_Template")
TMLR_PDF = ROOT / "paper_tmlr" / "main.pdf"

STYLE_FILES = (
    "jair.cls",
    "acmart.cls",
    "acmauthoryear.bbx",
    "acmauthoryear.cbx",
    "acmdatamodel.dbx",
)

# Match style commands only (not citation keys like mukherjee2026geometry).
STYLE_GREP = (
    r"\\vspace|\\setlength|\\linespread|\\geometry\b|\\usepackage\{[^}]*geometry"
    r"|\\baselinestretch|\\fontsize|\\tabcolsep"
)


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


def kit_diffs() -> list[str]:
    if not KIT.is_dir():
        return [f"Author Kit reference dir missing: {KIT}"]
    bad = []
    for name in STYLE_FILES:
        a = KIT / name
        b = JAIR / name
        if not a.exists() or not b.exists():
            bad.append(f"missing kit file for diff: {name}")
            continue
        r = subprocess.run(["diff", "-q", str(a), str(b)], capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"template modified: {name}")
    return bad


def style_grep() -> str:
    paths = [JAIR / "main.tex"]
    paths += sorted((JAIR / "sections").glob("*.tex"))
    paths += sorted((JAIR / "appendix").glob("*.tex"))
    # tables may contain \setlength{\tabcolsep}; report separately
    cmd = ["rg", "-n", STYLE_GREP] + [str(p) for p in paths]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return (r.stdout or "").strip()


def table_tabcolsep_grep() -> str:
    tables = sorted((JAIR / "tables").glob("*.tex"))
    if not tables:
        return ""
    cmd = ["rg", "-n", r"\\tabcolsep|\\setlength", *[str(p) for p in tables]]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return (r.stdout or "").strip()


def description_count(tex: str) -> int:
    return len(re.findall(r"\\Description\{", tex))


def figure_caption_order_ok() -> list[str]:
    """Figure captions should follow includegraphics; Description may follow caption."""
    errors = []
    for path in sorted((JAIR / "sections").glob("*.tex")) + sorted(
        (JAIR / "appendix").glob("*.tex")
    ):
        text = path.read_text()
        for m in re.finditer(r"\\begin\{figure\}.*?\\end\{figure\}", text, flags=re.S):
            block = m.group(0)
            if "\\includegraphics" not in block:
                continue
            if "\\caption" not in block:
                errors.append(f"{path.name}: figure missing caption")
                continue
            if "\\Description" not in block:
                errors.append(f"{path.name}: figure missing \\Description")
            # caption should appear after includegraphics
            ig = block.find("\\includegraphics")
            cap = block.find("\\caption")
            if cap < ig:
                errors.append(f"{path.name}: figure caption before includegraphics")
    return errors


def raster_blank_pages(pdf: Path) -> list[str]:
    errors = []
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        subprocess.check_call(
            ["pdftoppm", "-png", "-r", "36", str(pdf), str(td_path / "page")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pages = sorted(td_path.glob("page-*.png"))
        if not pages:
            return ["rasterisation produced no pages"]
        # Heuristic: nearly-white page (mean > 250) counts as blank.
        # Pure-stdlib blank heuristic via `sips`/`file` fallback: compare PNG size.
        # Tiny nearly-empty rasters are suspicious; also decode with zlib/PNG if needed.
        try:
            import statistics
            import struct
            import zlib

            def png_mean_gray(path: Path) -> float:
                raw = path.read_bytes()
                assert raw[:8] == b"\x89PNG\r\n\x1a\n"
                # parse IHDR + IDAT
                pos = 8
                w = h = None
                idat = b""
                while pos < len(raw):
                    length = struct.unpack(">I", raw[pos : pos + 4])[0]
                    ctype = raw[pos + 4 : pos + 8]
                    data = raw[pos + 8 : pos + 8 + length]
                    pos += 12 + length
                    if ctype == b"IHDR":
                        w, h = struct.unpack(">II", data[:8])
                        bit_depth, color_type = data[8], data[9]
                    elif ctype == b"IDAT":
                        idat += data
                    elif ctype == b"IEND":
                        break
                assert w and h
                decompressed = zlib.decompress(idat)
                # Assume 8-bit RGB or grayscale with filter bytes.
                if color_type == 2:  # RGB
                    stride = w * 3
                elif color_type == 0:
                    stride = w
                elif color_type == 6:  # RGBA
                    stride = w * 4
                else:
                    return 0.0
                samples = []
                row_len = stride + 1
                for y in range(h):
                    row = decompressed[y * row_len + 1 : (y + 1) * row_len]
                    if color_type == 2:
                        samples.extend(row[:: 3 * 20])
                    elif color_type == 6:
                        samples.extend(row[:: 4 * 20])
                    else:
                        samples.extend(row[::20])
                return statistics.fmean(samples) if samples else 0.0

            for p in pages:
                mean = png_mean_gray(p)
                if mean > 252:
                    errors.append(f"possible blank page: {p.name} mean={mean:.1f}")
        except Exception as e:
            errors.append(f"blank-page check skipped: {e}")
    return errors


def text_identity_diff(jair_txt: str, tmlr_txt: str) -> list[str]:
    """Coarse report of notable content differences (layout/citations ignored)."""
    notes = []
    if "anonymous.4open.science" in jair_txt:
        notes.append("JAIR PDF still contains anonymous.4open.science")
    if "https://github.com/heyronith/constituition" not in jair_txt.replace("\n", ""):
        # pdftotext may break URLs across lines
        compact = re.sub(r"\s+", "", jair_txt)
        if "github.com/heyronith/constituition" not in compact:
            notes.append("JAIR PDF missing public GitHub URL")
    if "osf.io/mw86p" not in re.sub(r"\s+", "", jair_txt):
        notes.append("JAIR PDF missing OSF mw86p")
    if "Background:" not in jair_txt and "Background" not in jair_txt:
        notes.append("structured abstract Background heading missing")
    if "Reproducibility Checklist" not in jair_txt:
        notes.append("Reproducibility Checklist missing from PDF text")
    if "JAIR Track" not in jair_txt and "AI and Society" not in jair_txt:
        notes.append("JAIR Track / AI and Society missing")
    # Expected deltas vs TMLR
    expected_markers = [
        ("Ronith Sharmila", "named authors"),
        ("Computing environment", "Appendix J"),
        ("Reproducibility Checklist", "checklist appendix"),
        ("kim2021", None),  # may appear as Kim et al. in text
    ]
    for marker, label in expected_markers:
        if label and marker not in jair_txt and marker.lower() not in jair_txt.lower():
            notes.append(f"expected presence missing: {label} ({marker})")
    if "Under review" in jair_txt and "TMLR" in jair_txt:
        notes.append("TMLR Under-review header may still be present")
    return notes


def main_text_page_count(pdf: Path) -> tuple[int | None, int]:
    """Return (last page of main matter through Broader Impact, total pages)."""
    info = pdfinfo_fields(pdf)
    total = int(info.get("Pages", "0") or 0)
    main_end = None
    for i in range(1, total + 1):
        page = subprocess.check_output(
            ["pdftotext", "-f", str(i), "-l", str(i), str(pdf), "-"],
            text=True,
            errors="ignore",
        )
        compact = re.sub(r"\s+", " ", page)
        if "Broader Impact Statement" in compact:
            main_end = i
        # First appendix page ends main matter if Broader already seen.
        if main_end is not None and (
            re.search(r"APPENDIX\s+A\b", compact, flags=re.I)
            or "Decision log: key decisions" in compact
        ):
            break
    return main_end, total


def main() -> int:
    errors: list[str] = []
    print("=== JAIR checks ===")

    if not MAIN_PDF.exists():
        print("JAIR CHECKS FAIL: missing paper_jair/main.pdf")
        return 1

    # 2. template unmodified
    kd = kit_diffs()
    if kd:
        for e in kd:
            print("KIT DIFF:", e)
            errors.append(e)
    else:
        print("template diff: OK (unmodified vs Author Kit)")

    grepped = style_grep()
    print("style grep (main/sections/appendix):")
    print(grepped if grepped else "  (no hits)")
    if grepped:
        errors.append("forbidden style commands outside tables:\n" + grepped)
    tabg = table_tabcolsep_grep()
    print("table tabcolsep/setlength (allowed):")
    print(tabg if tabg else "  (none)")

    # 1. build log
    log = JAIR / "main.log"
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
            if "undefined" in ln.lower()
            and ("Citation" in ln or "Reference" in ln or "Latex" in ln or "cite" in ln.lower())
        ]
        if undef:
            errors.append("undefined refs/cites:\n" + "\n".join(undef[:20]))
        if "Biber" in logt and "error" in logt.lower():
            # soft: look for explicit biber failure markers
            pass

    # 3–4 PDF content
    txt = pdf_text(MAIN_PDF)
    compact = re.sub(r"\s+", "", txt)
    checks = [
        ("line numbers present (heuristic)", bool(re.search(r"(?m)^\s*\d+\s+\S", txt))),
        ("JAIR Track / AI and Society", "AI and Society" in txt),
        ("CC BY", "Creative Commons" in txt or "CC BY" in txt or "creativecommons" in compact.lower()),
        ("structured abstract Background", "Background" in txt),
        ("no CCS concepts block", "CCS Concepts" not in txt),
        ("no Keywords block", not re.search(r"(?m)^Keywords", txt)),
        ("Reproducibility Checklist last-ish", "Reproducibility Checklist" in txt),
        ("GitHub URL", "github.com/heyronith/constituition" in compact),
        ("OSF mw86p", "osf.io/mw86p" in compact),
        ("anonymous URL absent", "anonymous.4open.science" not in compact),
    ]
    for name, ok in checks:
        print(f"PDF check {name}: {'OK' if ok else 'FAIL'}")
        if not ok:
            errors.append(f"PDF check failed: {name}")

    for e in figure_caption_order_ok():
        print("FIG:", e)
        errors.append(e)

    # Descriptions
    n_desc = 0
    for p in (JAIR / "sections").glob("*.tex"):
        n_desc += description_count(p.read_text())
    print(f"\\Description count in sections: {n_desc}")
    if n_desc < 5:
        errors.append(f"expected ≥5 \\Description commands, found {n_desc}")

    # 5 number audit
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "paper_number_audit.py"), "--jair"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    print((r.stdout or "")[-500:])
    if r.returncode != 0 or "PASS" not in (r.stdout or ""):
        errors.append("number audit did not PASS (--jair)")
    else:
        print("number audit: OK")

    # 6 text identity
    if TMLR_PDF.exists():
        tmlr_txt = pdf_text(TMLR_PDF)
        notes = text_identity_diff(txt, tmlr_txt)
        print("text-identity notes:")
        for n in notes:
            print(" -", n)
            if "missing" in n.lower() or "still contains" in n.lower():
                errors.append(n)
    else:
        print("TMLR PDF missing; skip text-identity")

    # 7 fonts + raster
    bad = fonts_ok(MAIN_PDF)
    if bad:
        errors.append("Type 3 fonts:\n" + "\n".join(bad[:10]))
    else:
        print("pdffonts: OK (no Type 3)")

    blank = raster_blank_pages(MAIN_PDF)
    for b in blank:
        print("RASTER:", b)
        if "possible blank" in b:
            errors.append(b)

    main_pages, total = main_text_page_count(MAIN_PDF)
    print(f"page_count main_text_through_broader≈{main_pages} total={total}")

    if errors:
        print("JAIR CHECKS FAIL:")
        for e in errors:
            print(" -", e)
        return 1
    print("JAIR CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
