#!/usr/bin/env python3
"""Assert every fig:/tab: float label is cited outside its own float (MLJ / Springer)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLJ = ROOT / "paper_mlj"
SUB = ROOT / "submission_mlj"

LABEL_RE = re.compile(r"\\label\{((?:fig|tab):[^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|autoref|cref|Cref|pageref)\{((?:fig|tab):[^}]+)\}")
FLOAT_RE = re.compile(
    r"\\begin\{((?:figure|table)\*?|sidewaysfigure|sidewaystable)\}"
    r".*?"
    r"\\end\{\1\}",
    flags=re.S,
)


def expand_inputs(tex: str, root: Path, seen: set[Path] | None = None) -> str:
    seen = seen or set()

    def repl(m: re.Match) -> str:
        rel = m.group(1)
        path = root / rel
        if not path.suffix:
            path = path.with_suffix(".tex")
        path = path.resolve()
        if path in seen:
            return ""
        if not path.exists():
            raise FileNotFoundError(path)
        seen.add(path)
        return expand_inputs(path.read_text(), root, seen)

    return re.sub(r"\\input\{([^}]+)\}", repl, tex)


def load_flat_tex(*, prefer_submission: bool) -> tuple[str, str]:
    """Return (flat_tex, source_description)."""
    sub_ms = SUB / "manuscript.tex"
    if prefer_submission:
        if not sub_ms.exists():
            raise SystemExit(f"missing {sub_ms}")
        return sub_ms.read_text(), str(sub_ms)
    main = MLJ / "main.tex"
    flat = expand_inputs(main.read_text(), MLJ)
    return flat, f"{main} (inputs expanded)"


def float_spans(tex: str) -> list[tuple[int, int, str]]:
    """List of (start, end, kind) for each float environment."""
    spans = []
    for m in FLOAT_RE.finditer(tex):
        spans.append((m.start(), m.end(), m.group(1)))
    return spans


def label_in_float(pos: int, spans: list[tuple[int, int, str]]) -> tuple[int, int] | None:
    for a, b, _ in spans:
        if a <= pos < b:
            return (a, b)
    return None


def first_citation_line(tex: str, label: str, float_span: tuple[int, int] | None) -> int | None:
    for m in REF_RE.finditer(tex):
        if m.group(1) != label:
            continue
        if float_span and float_span[0] <= m.start() < float_span[1]:
            continue
        # 1-based line number
        return tex.count("\n", 0, m.start()) + 1
    return None


def caption_numbers_from_aux(aux_path: Path) -> dict[str, str]:
    """Map label -> printed number from .aux (\\newlabel{fig:x}{{1}{...}})."""
    out: dict[str, str] = {}
    if not aux_path.exists():
        return out
    # \newlabel{fig:paradigm}{{1}{7}{...}{figure.1}{}}
    for m in re.finditer(
        r"\\newlabel\{((?:fig|tab):[^}]+)\}\{\{([^}]*)\}",
        aux_path.read_text(errors="ignore"),
    ):
        out[m.group(1)] = m.group(2)
    return out


def pdf_mentions_number(pdf_text: str, kind: str, num: str) -> bool:
    """kind is 'figure' or 'table'; num is caption number string."""
    if kind == "figure":
        pats = [
            rf"\bFigure\s+{re.escape(num)}\b",
            rf"\bFig\.\s*{re.escape(num)}\b",
        ]
    else:
        pats = [rf"\bTable\s+{re.escape(num)}\b"]
    return any(re.search(p, pdf_text) for p in pats)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument(
        "--submission",
        action="store_true",
        help="Check flattened submission_mlj/manuscript.tex (after make mlj-submission)",
    )
    args = ap.parse_args()

    flat, src = load_flat_tex(prefer_submission=args.submission)
    spans = float_spans(flat)
    labels = [(m.group(1), m.start()) for m in LABEL_RE.finditer(flat)]
    if not labels:
        print("FAIL: no fig:/tab: labels found", file=sys.stderr)
        return 1

    aux_nums = caption_numbers_from_aux(MLJ / "main.aux")
    pdf_path = MLJ / "main.pdf"
    if not pdf_path.exists() and (SUB / "manuscript.pdf").exists():
        pdf_path = SUB / "manuscript.pdf"
    pdf_text = ""
    if pdf_path.exists():
        pdf_text = subprocess.check_output(
            ["pdftotext", str(pdf_path), "-"], text=True, errors="replace"
        )

    mapping = []
    errors = []

    for label, pos in labels:
        fspan = label_in_float(pos, spans)
        cite_line = first_citation_line(flat, label, fspan)
        num = aux_nums.get(label, "?")
        kind = "figure" if label.startswith("fig:") else "table"
        entry = {
            "label": label,
            "caption_number": num,
            "first_citation_line": cite_line,
            "source": src,
        }
        mapping.append(entry)

        if cite_line is None:
            errors.append(f"{label}: no \\ref/\\autoref/\\cref outside its float")
            continue

        if num != "?" and pdf_text:
            if not pdf_mentions_number(pdf_text, kind, num):
                errors.append(
                    f"{label}: caption number {num} not mentioned in PDF body "
                    f"(expected 'Figure {num}'/'Fig. {num}' or 'Table {num}')"
                )

    print(f"Float citation check ({src})")
    print(f"{'label':28} {'num':6} {'first cite line'}")
    for e in mapping:
        print(
            f"{e['label']:28} {e['caption_number']:6} {e['first_citation_line']}"
        )

    if args.json_out:
        args.json_out.write_text(json.dumps(mapping, indent=2) + "\n")

    if errors:
        print("\nFAIL:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("FLOAT CITATION CHECK PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
