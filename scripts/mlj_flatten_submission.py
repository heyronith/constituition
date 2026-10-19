#!/usr/bin/env python3
"""Flatten paper_mlj into submission_mlj/ (no subfolders) and zip."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLJ = ROOT / "paper_mlj"
SUB = ROOT / "submission_mlj"


def expand_inputs(tex: str, root: Path, seen: set[Path] | None = None) -> str:
    """Inline \\input{...}. Paths resolve against the manuscript root (latexmk cwd)."""
    seen = seen or set()

    def repl(m: re.Match) -> str:
        rel = m.group(1)
        path = root / rel
        if not path.suffix:
            path = path.with_suffix(".tex")
        path = path.resolve()
        if path in seen:
            return f"% circular input {rel}\n"
        if not path.exists():
            raise FileNotFoundError(path)
        seen.add(path)
        body = path.read_text()
        return expand_inputs(body, root, seen)

    # \input{...} only (not \includegraphics)
    return re.sub(r"\\input\{([^}]+)\}", repl, tex)


def main() -> None:
    if SUB.exists():
        shutil.rmtree(SUB)
    SUB.mkdir(parents=True)

    main_tex = (MLJ / "main.tex").read_text()
    # Drop macros input; will inline after expansion of sections
    flat = expand_inputs(main_tex, MLJ)

    # Inline macros_numbers if still present
    flat = re.sub(
        r"\\input\{macros_numbers\.tex\}",
        lambda _m: (MLJ / "macros_numbers.tex").read_text(),
        flat,
    )

    # Rewrite figure paths to bare names
    flat = flat.replace("figs/Fig", "Fig")
    flat = re.sub(r"\\includegraphics(\[[^\]]*\])?\{figs/", r"\\includegraphics\1{", flat)

    # Inline .bbl if present
    bbl = MLJ / "main.bbl"
    if bbl.exists():
        bbl_text = bbl.read_text()
        flat = re.sub(
            r"\\bibliography\{[^}]+\}",
            lambda _m: bbl_text,
            flat,
            count=1,
        )

    (SUB / "manuscript.tex").write_text(flat)

    # Copy class, bst, bib, bbl, figs, extras
    shutil.copy(MLJ / "sn-jnl.cls", SUB / "sn-jnl.cls")
    shutil.copy(MLJ / "sn-apacite.bst", SUB / "sn-apacite.bst")
    shutil.copy(MLJ / "refs.bib", SUB / "refs.bib")
    if bbl.exists():
        shutil.copy(bbl, SUB / "manuscript.bbl")

    for n in range(1, 5):
        for ext in (".pdf", ".eps"):
            src = MLJ / "figs" / f"Fig{n}{ext}"
            if src.exists():
                shutil.copy(src, SUB / f"Fig{n}{ext}")

    for name in (
        "contribution_information_sheet.pdf",
        "cover_letter.pdf",
        "main.pdf",
    ):
        src = MLJ / name
        if src.exists():
            dest = SUB / ("manuscript.pdf" if name == "main.pdf" else name)
            shutil.copy(src, dest)

    # Clean compile in temp dir
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        for f in SUB.iterdir():
            if f.is_file():
                shutil.copy(f, tdir / f.name)
        cmds = [
            ["pdflatex", "-interaction=nonstopmode", "manuscript.tex"],
            ["bibtex", "manuscript"],
            ["pdflatex", "-interaction=nonstopmode", "manuscript.tex"],
            ["pdflatex", "-interaction=nonstopmode", "manuscript.tex"],
        ]
        env_path = str(Path.home() / "Library/TinyTeX/bin/universal-darwin")
        import os

        env = os.environ.copy()
        env["PATH"] = env_path + ":" + env.get("PATH", "")
        for cmd in cmds:
            subprocess.run(cmd, cwd=tdir, env=env, check=False, capture_output=True)
        built = tdir / "manuscript.pdf"
        if built.exists():
            shutil.copy(built, SUB / "manuscript.pdf")
            print("clean compile OK")
        else:
            log = (tdir / "manuscript.log").read_text(errors="ignore")[-3000:]
            raise SystemExit("clean compile FAILED\n" + log)

    # zip with files at archive root (MLJ disallows a wrapping folder).
    # Word exports live in submission_mlj/ for the author but must not enter the zip
    # (Phase 9H: avoid duplicate cover/contribution documents in the journal upload).
    zip_path = ROOT / "submission_mlj.zip"
    if zip_path.exists():
        zip_path.unlink()
    subprocess.check_call(
        ["zip", "-r", str(zip_path), ".", "-x", "*.docx"],
        cwd=str(SUB),
    )

    word_dir = MLJ / "word"
    for name in ("cover_letter.docx", "contribution_information_sheet.docx"):
        src = word_dir / name
        if src.exists():
            shutil.copy(src, SUB / name)

    print(f"Wrote {zip_path} and {SUB}")


if __name__ == "__main__":
    main()
