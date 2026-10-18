#!/usr/bin/env python3
"""Build Word (.docx) versions of the MLJ cover letter and Contribution Information Sheet.

Source of truth: paper_mlj/*.tex. Text is never retyped by hand — it is read from the
.tex files (with \\today replaced by the date string from cover_letter.pdf).

Method: python-docx built directly from the .tex sources (pandoc is used only to seed
paper_mlj/word/reference.docx styles if missing). Layout requirements (sender block,
run-in bold labels, bullets) are more reliable this way than pandoc+postprocess.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parents[1]
MLJ = ROOT / "paper_mlj"
WORD = MLJ / "word"
SUB = ROOT / "submission_mlj"
REF = WORD / "reference.docx"

FONT = "Times New Roman"
SIZE = Pt(11)


# ---------------------------------------------------------------------------
# TeX helpers (parse formatting; never invent wording)
# ---------------------------------------------------------------------------

def _date_from_cover_pdf() -> str:
    pdf = SUB / "cover_letter.pdf"
    if not pdf.exists():
        pdf = MLJ / "cover_letter.pdf"
    text = subprocess.check_output(["pdftotext", str(pdf), "-"], text=True)
    m = re.search(
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})",
        text,
    )
    if not m:
        raise SystemExit("Could not read date string from cover_letter.pdf")
    return m.group(1)


def _read_tex_body(path: Path, today: str) -> str:
    raw = path.read_text(encoding="utf-8")
    raw = raw.replace(r"\today", today)
    # Drop preamble through \begin{document}
    body = re.split(r"\\begin\{document\}", raw, maxsplit=1)[1]
    body = re.split(r"\\end\{document\}", body, maxsplit=1)[0]
    return body


def _tex_to_plain_segments(s: str) -> list[tuple[str, dict]]:
    """Convert a TeX fragment to (text, {bold, italic, url}) runs. Source-faithful."""
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Structural / spacing commands we drop (content already extracted)
    s = s.replace(r"\maketitle", "")
    s = s.replace(r"\noindent", "")
    # Quotes, dashes, percent
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = s.replace("---", "\u2014")
    s = s.replace("--", "\u2013")
    s = s.replace(r"\%", "%")
    s = s.replace(r"\&", "&")
    # Math fragments appearing in the CIS
    s = s.replace(r"$\times$", "\u00d7")
    s = s.replace(r"$\alpha$", "\u03b1")
    s = s.replace(r"$-$", "\u2212")
    s = re.sub(r"\$([^$]*)\$", lambda m: m.group(1), s)  # leftover simple math
    s = s.replace(r"\times", "\u00d7")
    s = s.replace(r"\alpha", "\u03b1")
    # vs.\ → vs.
    s = s.replace(r"vs.\ ", "vs. ")
    s = s.replace(r"et.\ ", "et. ")  # shouldn't appear
    # Soft command: \  (control space)
    s = s.replace(r"\ ", " ")

    runs: list[tuple[str, dict]] = []

    # Tokenize bold / italic / url / textbf-italic nesting (simple)
    pattern = re.compile(
        r"\\url\{([^}]*)\}"
        r"|\\textbf\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
        r"|\\textit\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
        r"|\\textbf\{([^}]*)\}"
        r"|\\textit\{([^}]*)\}"
    )

    # Simpler iterative parser
    i = 0
    while i < len(s):
        if s.startswith(r"\url{", i):
            j = s.index("}", i + 5)
            url = s[i + 5 : j]
            runs.append((url, {"url": url}))
            i = j + 1
            continue
        if s.startswith(r"\textbf{", i):
            depth, j = 1, i + 8
            while j < len(s) and depth:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            inner = s[i + 8 : j - 1]
            # Recurse for nested \textit etc. (rare); flatten with bold
            inner_plain = _strip_tex_commands(inner)
            runs.append((inner_plain, {"bold": True}))
            i = j
            continue
        if s.startswith(r"\textit{", i):
            depth, j = 1, i + 8
            while j < len(s) and depth:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            inner = s[i + 8 : j - 1]
            inner_plain = _strip_tex_commands(inner)
            runs.append((inner_plain, {"italic": True}))
            i = j
            continue
        # Skip leftover backslash commands like \title{...}
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1].isalpha():
            m = re.match(r"\\[A-Za-z]+(\[[^\]]*\])?(\{([^{}]*)\})?", s[i:])
            if m:
                # Keep braced argument text if present (e.g. title)
                if m.group(3) is not None and m.group(0).startswith(r"\title"):
                    runs.append((_strip_tex_commands(m.group(3)), {"bold": True}))
                i += len(m.group(0))
                continue
        # Plain character
        # Find next special
        nxt = len(s)
        for marker in (r"\url{", r"\textbf{", r"\textit{", "\\"):
            k = s.find(marker, i + 1) if marker == "\\" else s.find(marker, i)
            if marker == "\\" and k == i:
                continue
            if k != -1:
                nxt = min(nxt, k)
        chunk = s[i:nxt]
        if chunk:
            runs.append((_strip_tex_commands(chunk), {}))
        if nxt == i:
            i += 1
        else:
            i = nxt
    # Merge adjacent same-style runs
    merged: list[tuple[str, dict]] = []
    for text, sty in runs:
        if not text:
            continue
        if merged and merged[-1][1] == sty:
            merged[-1] = (merged[-1][0] + text, sty)
        else:
            merged.append((text, sty))
    return merged


def _strip_tex_commands(s: str) -> str:
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = s.replace(r"\%", "%").replace(r"\&", "&").replace(r"\ ", " ")
    s = s.replace(r"$\times$", "\u00d7").replace(r"$\alpha$", "\u03b1").replace(r"$-$", "\u2212")
    s = re.sub(r"\$([^$]*)\$", lambda m: m.group(1), s)
    s = s.replace(r"\times", "\u00d7").replace(r"\alpha", "\u03b1")
    s = s.replace(r"vs.\ ", "vs. ")
    # Remove remaining simple commands keeping args: \foo{bar} -> bar
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\\[A-Za-z]+\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = s.replace("{", "").replace("}", "")
    return s


# ---------------------------------------------------------------------------
# Document styling
# ---------------------------------------------------------------------------

def _set_run_font(run, *, bold=False, italic=False):
    run.font.name = FONT
    run.font.size = SIZE
    run.bold = bold
    run.italic = italic
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), FONT)
    rFonts.set(qn("w:hAnsi"), FONT)
    rFonts.set(qn("w:eastAsia"), FONT)


def _style_paragraph(p: Paragraph, *, space_after_pt: float = 6.0, center: bool = False):
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(space_after_pt)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.first_line_indent = Pt(0)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:
        _set_run_font(run, bold=bool(run.bold), italic=bool(run.italic))


def _add_runs(p: Paragraph, segments: list[tuple[str, dict]]):
    for text, sty in segments:
        if sty.get("url"):
            _add_hyperlink(p, sty["url"], text)
            continue
        run = p.add_run(text)
        _set_run_font(run, bold=sty.get("bold", False), italic=sty.get("italic", False))


def _add_hyperlink(paragraph: Paragraph, url: str, text: str):
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    # Times New Roman 11, blue underline
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), FONT)
    rFonts.set(qn("w:hAnsi"), FONT)
    rPr.append(rFonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "22")  # half-points
    rPr.append(sz)
    szCs = OxmlElement("w:szCs")
    szCs.set(qn("w:val"), "22")
    rPr.append(szCs)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def _set_page(doc: Document):
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        # No header
        section.header.is_linked_to_previous = False
        for p in section.header.paragraphs:
            p.clear()
        # Page number centred in footer (allowed)
        footer = section.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fp.clear()
        run = fp.add_run()
        _set_run_font(run)
        fld_char_begin = OxmlElement("w:fldChar")
        fld_char_begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = " PAGE "
        fld_char_end = OxmlElement("w:fldChar")
        fld_char_end.set(qn("w:fldCharType"), "end")
        run._r.append(fld_char_begin)
        run._r.append(instr)
        run._r.append(fld_char_end)


def _ensure_reference_docx():
    WORD.mkdir(parents=True, exist_ok=True)
    doc = Document()
    _set_page(doc)
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = SIZE
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    style.paragraph_format.first_line_indent = Pt(0)
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), FONT)
    rFonts.set(qn("w:hAnsi"), FONT)
    p = doc.add_paragraph("Reference style document for MLJ Word exports.")
    _style_paragraph(p)
    doc.save(REF)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_cover_letter(today: str, out: Path) -> None:
    body = _read_tex_body(MLJ / "cover_letter.tex", today)
    # Split flushleft block
    m = re.search(
        r"\\begin\{flushleft\}(.*?)\\end\{flushleft\}",
        body,
        flags=re.S,
    )
    if not m:
        raise SystemExit("cover_letter.tex: missing flushleft block")
    sender_raw = m.group(1)
    rest = body[m.end() :]
    sender_lines = [ln.strip() for ln in re.split(r"\\\\", sender_raw) if ln.strip()]
    # After flushleft: Editor\\ \textit{...}\\ Springer then paragraphs
    rest = rest.strip()
    # Split on blank lines (paragraphs) after converting \\ to newlines for recipient
    # First extract recipient lines before "Dear Editor"
    dear_idx = rest.find("Dear Editor")
    if dear_idx < 0:
        raise SystemExit("cover_letter.tex: missing Dear Editor")
    recipient_part = rest[:dear_idx]
    letter_part = rest[dear_idx:]
    recip_lines = [
        _strip_tex_commands(ln.strip())
        for ln in re.split(r"\\\\", recipient_part)
        if ln.strip() and not ln.strip().startswith("%")
    ]
    # Also handle \textit in recipient — keep via segments
    recip_segs = []
    for ln in re.split(r"\\\\", recipient_part):
        ln = ln.strip()
        if not ln:
            continue
        recip_segs.append(_tex_to_plain_segments(ln))

    # Letter paragraphs: split on blank lines
    paras = re.split(r"\n\s*\n", letter_part.strip())
    # Expand Sincerely block: Sincerely,\\[1em] lines
    doc = Document()
    _set_page(doc)
    if not doc.paragraphs:
        doc.add_paragraph()

    # Sender
    for i, line in enumerate(sender_lines):
        text = _strip_tex_commands(line)
        if i == 0:
            p = doc.paragraphs[0]
            p.clear()
            p.add_run(text)
            _set_run_font(p.runs[0])
        else:
            p = doc.add_paragraph()
            p.add_run(text)
            _set_run_font(p.runs[0])
        after = 0 if i < len(sender_lines) - 1 else 6
        _style_paragraph(p, space_after_pt=after)

    # Recipient
    for segs in recip_segs:
        p = doc.add_paragraph()
        _add_runs(p, segs)
        _style_paragraph(p, space_after_pt=0)
    # space after Springer
    if doc.paragraphs:
        doc.paragraphs[-1].paragraph_format.space_after = Pt(12)

    # Body paragraphs
    for para in paras:
        para = para.strip()
        if not para:
            continue
        # Signature block starts at Sincerely
        if para.startswith("Sincerely"):
            lines = re.split(r"\\\\(?:\[[^\]]*\])?", para)
            for j, ln in enumerate(lines):
                ln = ln.strip()
                if not ln:
                    continue
                p = doc.add_paragraph()
                _add_runs(p, _tex_to_plain_segments(ln))
                # Extra space after Sincerely,
                after = 12 if ln.startswith("Sincerely") else (0 if j < len(lines) - 1 else 0)
                _style_paragraph(p, space_after_pt=after)
            continue
        p = doc.add_paragraph()
        _add_runs(p, _tex_to_plain_segments(para))
        _style_paragraph(p, space_after_pt=6)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    print(f"Wrote {out}")


def build_contribution_sheet(today: str, out: Path) -> None:
    body = _read_tex_body(MLJ / "contribution_information_sheet.tex", today)
    # Title from \title{...}
    tm = re.search(r"\\title\{([^}]*)\}", (MLJ / "contribution_information_sheet.tex").read_text())
    if not tm:
        raise SystemExit("missing \\title")
    title = _strip_tex_commands(tm.group(1).replace("---", "\u2014"))

    doc = Document()
    _set_page(doc)
    # Title
    p = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    p.clear()
    run = p.add_run(title)
    _set_run_font(run, bold=True)
    _style_paragraph(p, space_after_pt=12, center=True)

    # Remove \maketitle / author / date noise from body
    body = re.sub(r"\\maketitle", "", body)
    body = re.sub(r"\\author\{\}", "", body)
    body = re.sub(r"\\date\{\}", "", body)

    # Split into chunks by blank lines, but keep itemize as a unit
    # Process sequentially
    pos = 0
    while pos < len(body):
        # Skip whitespace
        mws = re.match(r"\s+", body[pos:])
        if mws:
            pos += mws.end()
            continue
        # itemize block
        if body[pos:].lstrip().startswith(r"\begin{itemize}"):
            im = re.search(
                r"\\begin\{itemize\}.*?\\end\{itemize\}",
                body[pos:],
                flags=re.S,
            )
            if not im:
                raise SystemExit("unclosed itemize")
            block = im.group(0)
            pos += im.end()
            items = re.findall(r"\\item\s+(.*?)(?=\\item|\\end\{itemize\})", block, flags=re.S)
            for item in items:
                item = item.strip()
                p = doc.add_paragraph(style="List Bullet")
                _add_runs(p, _tex_to_plain_segments(item))
                _style_paragraph(p, space_after_pt=6)
                # Ensure Times on bullet para
                for run in p.runs:
                    _set_run_font(run, bold=bool(run.bold), italic=bool(run.italic))
            continue
        # Next paragraph until blank line or itemize
        nxt_itemize = body.find(r"\begin{itemize}", pos)
        nxt_blank = re.search(r"\n\s*\n", body[pos:])
        end = len(body)
        if nxt_itemize != -1:
            end = min(end, nxt_itemize)
        if nxt_blank:
            end = min(end, pos + nxt_blank.start())
        para = body[pos:end].strip()
        pos = end if not nxt_blank or (pos + nxt_blank.start() != end) else pos + nxt_blank.end()
        if not para:
            # advanced via blank
            if nxt_blank and end == pos + nxt_blank.start():
                pos = pos  # already
            continue
        if not para:
            continue
        p = doc.add_paragraph()
        _add_runs(p, _tex_to_plain_segments(para))
        _style_paragraph(p, space_after_pt=6)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    print(f"Wrote {out}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _docx_plain(path: Path) -> str:
    doc = Document(path)
    parts = []
    for p in doc.paragraphs:
        parts.append(p.text)
    return "\n".join(parts)


def _pdf_plain(path: Path) -> str:
    return subprocess.check_output(["pdftotext", str(path), "-"], text=True)


def normalize_for_identity(s: str) -> str:
    """Normalise for text-identity check (instruction §3.1)."""
    s = s.lower()
    # Join hyphenation line-breaks: keep a real hyphen, drop only the newline
    s = re.sub(r"([a-z0-9])-\n([a-z])", r"\1-\2", s)
    # Soft hyphen
    s = s.replace("\u00ad", "")
    # Typographic quotes/apostrophes from PDF engines → ASCII (same source wording)
    for a, b in (
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2212", "-"),  # minus → hyphen for compare only
        ("\u2013", "-"),  # en dash
        ("\u2014", "-"),  # em dash
        ("\u00d7", "x"),  # ×
        ("\u03b1", "alpha"),
    ):
        s = s.replace(a, b)
    # Drop page-number-only lines
    lines = []
    for ln in s.splitlines():
        if re.fullmatch(r"\s*\d+\s*", ln):
            continue
        lines.append(ln)
    s = "\n".join(lines)
    # Strip list markers / numbering at line starts (not decimals like 0.671)
    s = re.sub(r"^[\s]*[•\-\*\u2022\u00b7]\s*", "", s, flags=re.M)
    s = re.sub(r"^[\s]*\d+[\.\)]\s+", "", s, flags=re.M)
    # Remove all whitespace
    s = re.sub(r"\s+", "", s)
    # Drop any leftover form-feed
    s = s.replace("\x0c", "")
    # PDF engines drop hyphens at line wraps (self-refinement → selfrefinement);
    # strip intra-word hyphens so both sides compare equal without changing source text.
    s = re.sub(r"([a-z0-9])-([a-z0-9])", r"\1\2", s)
    return s


def assert_text_identity(docx_path: Path, pdf_path: Path) -> None:
    d = normalize_for_identity(_docx_plain(docx_path))
    p = normalize_for_identity(_pdf_plain(pdf_path))
    if d != p:
        diff = "\n".join(
            difflib.unified_diff(
                list(p),
                list(d),
                fromfile=str(pdf_path),
                tofile=str(docx_path),
                n=40,
            )
        )
        # Also show longer context chunks
        print("TEXT IDENTITY FAIL", docx_path.name)
        print("PDF norm length", len(p), "DOCX norm length", len(d))
        # Find first mismatch
        for i, (a, b) in enumerate(zip(p, d)):
            if a != b:
                print(f"first mismatch at {i}: pdf={a!r} docx={b!r}")
                print("pdf context:", p[max(0, i - 40) : i + 40])
                print("docx context:", d[max(0, i - 40) : i + 40])
                break
        else:
            if len(p) != len(d):
                print("prefix match; length differs")
                print("pdf tail:", p[-80:])
                print("docx tail:", d[-80:])
        raise SystemExit(1)
    print(f"text identity OK: {docx_path.name} ↔ {pdf_path.name}")


def _try_libreoffice_pages(docx_path: Path) -> int | None:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    soffice = next((c for c in candidates if c and Path(c).exists()), None)
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        subprocess.check_call(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(td_path), str(docx_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pdf = td_path / (docx_path.stem + ".pdf")
        if not pdf.exists():
            return None
        info = subprocess.check_output(["pdfinfo", str(pdf)], text=True)
        m = re.search(r"Pages:\s+(\d+)", info)
        # Also copy for PNG inspection
        dest = WORD / f"_lo_{docx_path.stem}.pdf"
        shutil.copy(pdf, dest)
        return int(m.group(1)) if m else None


def main() -> None:
    today = _date_from_cover_pdf()
    print(f"Date from PDF: {today}")
    _ensure_reference_docx()

    cover_docx = WORD / "cover_letter.docx"
    sheet_docx = WORD / "contribution_information_sheet.docx"
    build_cover_letter(today, cover_docx)
    build_contribution_sheet(today, sheet_docx)

    # TODO grep
    for path in (cover_docx, sheet_docx):
        plain = _docx_plain(path)
        if "TODO" in plain:
            raise SystemExit(f"TODO found in {path}")
        if re.search(r"[\\{}~]", plain):
            # Allow nothing that looks like leftover LaTeX
            bad = re.findall(r"[\\{}~]", plain)
            raise SystemExit(f"stray LaTeX chars in {path}: {bad[:10]}")

    cover_pdf = SUB / "cover_letter.pdf"
    sheet_pdf = SUB / "contribution_information_sheet.pdf"
    if not cover_pdf.exists():
        cover_pdf = MLJ / "cover_letter.pdf"
    if not sheet_pdf.exists():
        sheet_pdf = MLJ / "contribution_information_sheet.pdf"

    assert_text_identity(cover_docx, cover_pdf)
    assert_text_identity(sheet_docx, sheet_pdf)

    pages = {}
    for label, path in (("cover", cover_docx), ("sheet", sheet_docx)):
        n = _try_libreoffice_pages(path)
        pages[label] = n
        if n is not None:
            print(f"LibreOffice pages ({label}): {n}")
            if label == "cover" and n != 1:
                raise SystemExit(f"cover letter must be 1 page, got {n}")
            if label == "sheet" and n > 2:
                raise SystemExit(f"sheet must be ≤2 pages, got {n}")
        else:
            print(f"LibreOffice unavailable; page-count check skipped for {label}")

    # Copy into submission_mlj (not into zip)
    SUB.mkdir(parents=True, exist_ok=True)
    for src in (cover_docx, sheet_docx):
        shutil.copy(src, SUB / src.name)
        print(f"Copied {src.name} → submission_mlj/")

    # Write a small status sidecar for the report
    status = WORD / "_build_status.txt"
    status.write_text(
        f"date={today}\n"
        f"method=python-docx-from-tex\n"
        f"reference={REF}\n"
        f"libreoffice_cover_pages={pages.get('cover')}\n"
        f"libreoffice_sheet_pages={pages.get('sheet')}\n"
        f"text_identity=PASS\n"
    )
    print("All Word checks passed.")


if __name__ == "__main__":
    main()
