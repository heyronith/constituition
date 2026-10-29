#!/usr/bin/env python3
"""Flatten paper_aie into submission_aie/ (no subfolders) and zip.

Refuses to build while any \\PENDING{...} remains in the manuscript sources.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIE = ROOT / "paper_aie"
SUB = ROOT / "submission_aie"


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
        body = path.read_text(encoding="utf-8", errors="replace")
        return expand_inputs(body, root, seen)

    return re.sub(r"\\input\{([^}]+)\}", repl, tex)


def count_pending(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(root.rglob("*.tex")):
        # Skip Springer template samples and the title page (author-facing).
        rel = path.relative_to(root).as_posix()
        if rel.startswith("template/") or path.name == "title_page.tex":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if r"\PENDING{" in line:
                hits.append(f"{rel}:{i}: {line.strip()}")
    return hits


def main() -> None:
    pending = count_pending(AIE)
    if pending:
        print("AIE submission REFUSED: \\PENDING remains in manuscript sources:")
        for h in pending:
            print(" ", h)
        raise SystemExit(1)

    if SUB.exists():
        shutil.rmtree(SUB)
    SUB.mkdir(parents=True)

    main_tex = (AIE / "main.tex").read_text(encoding="utf-8")
    flat = expand_inputs(main_tex, AIE)
    flat = re.sub(
        r"\\input\{macros_numbers\.tex\}",
        lambda _m: (AIE / "macros_numbers.tex").read_text(encoding="utf-8"),
        flat,
    )
    flat = flat.replace("figs/Fig", "Fig")
    flat = re.sub(r"\\includegraphics(\[[^\]]*\])?\{figs/", r"\\includegraphics\1{", flat)

    bbl = AIE / "main.bbl"
    if bbl.exists():
        bbl_text = bbl.read_text(encoding="utf-8")
        flat = re.sub(
            r"\\bibliography\{[^}]+\}",
            lambda _m: bbl_text,
            flat,
            count=1,
        )

    (SUB / "manuscript.tex").write_text(flat, encoding="utf-8")

    shutil.copy(AIE / "sn-jnl.cls", SUB / "sn-jnl.cls")
    shutil.copy(AIE / "sn-mathphys-num.bst", SUB / "sn-mathphys-num.bst")
    shutil.copy(AIE / "refs.bib", SUB / "refs.bib")
    if bbl.exists():
        shutil.copy(bbl, SUB / "manuscript.bbl")

    for n in range(1, 6):
        for ext in (".pdf", ".eps"):
            src = AIE / "figs" / f"Fig{n}{ext}"
            if src.exists():
                shutil.copy(src, SUB / f"Fig{n}{ext}")

    for name, dest_name in (
        ("manuscript.pdf", "manuscript.pdf"),
        ("main.pdf", "manuscript.pdf"),
        ("title_page.pdf", "title_page.pdf"),
    ):
        src = AIE / name
        if src.exists() and not (SUB / dest_name).exists():
            shutil.copy(src, SUB / dest_name)

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

    zip_path = ROOT / "submission_aie.zip"
    if zip_path.exists():
        zip_path.unlink()
    subprocess.check_call(
        ["zip", "-r", str(zip_path), "."],
        cwd=str(SUB),
    )
    print(f"Wrote {zip_path} and {SUB}")


if __name__ == "__main__":
    main()
