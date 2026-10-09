#!/usr/bin/env python3
"""Grep anonymized PDF text for identifying strings (Phase 8C)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

NEEDLES = [
    "Ronith",
    "Sharmila",
    "Agrawal",
    "heyronith",
    "swosu.edu",
    "nku.edu",
    "github.com",
    "osf.io",
    "modal",
    "constituition",
]


def pdf_text(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["pdftotext", "-layout", str(path), "-"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        raw = path.read_bytes()
        return "\n".join(
            m.decode("latin1", "ignore") for m in re.findall(rb"[\x20-\x7e]{4,}", raw)
        )


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "paper/main_anon.pdf")
    if not path.exists():
        print(f"MISSING {path}")
        return 2
    text = pdf_text(path)
    hits = []
    for n in NEEDLES:
        if re.search(re.escape(n), text, re.I):
            # Avoid false positive: 'model' contains no 'modal'; word-ish for modal
            if n.lower() == "modal":
                if re.search(r"(?i)\bmodal\b", text):
                    hits.append(n)
            else:
                hits.append(n)
    if hits:
        print("ANON CHECK FAIL:", ", ".join(hits))
        return 1
    print("ANON CHECK PASS: zero hits for", ", ".join(NEEDLES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
