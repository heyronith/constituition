#!/usr/bin/env python3
"""Grep anonymized PDF text for identifying strings (Phase 8D)."""

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
    "osf.io",
    "modal",
    "constituition",
]

# Third-party concurrent-work repos (allowed in the review PDF).
# Match on repo path so line-wrapped bibliography URLs still pass.
GITHUB_ALLOW_REPOS = {
    "heyuday/const-drift-inspect",
    "wu-jinzhou/constitutional-value-drift",
}


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


def github_hits(text: str) -> list[str]:
    found = re.findall(r"github\.com/[^\s)\]>,;]+", text, flags=re.I)
    # Also catch split URLs: "github.com / Wu-Jinzhou / constitutional-..."
    compact = re.sub(r"\s+", "", text).lower()
    bad = []
    for hit in found:
        norm = hit.rstrip(".,;)").lower()
        allowed = any(repo in norm or repo in compact for repo in GITHUB_ALLOW_REPOS)
        if not allowed:
            bad.append(hit)
    # Any github.com mention of a non-allowlisted repo path
    for repo_m in re.finditer(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", compact):
        repo = repo_m.group(1)
        if repo not in GITHUB_ALLOW_REPOS and not any(repo.startswith(a) for a in GITHUB_ALLOW_REPOS):
            bad.append("github.com/" + repo)
    return bad


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "paper/main_anon.pdf")
    if not path.exists():
        print(f"MISSING {path}")
        return 2
    text = pdf_text(path)
    hits = []
    for n in NEEDLES:
        if n.lower() == "modal":
            if re.search(r"(?i)\bmodal\b", text):
                hits.append(n)
        elif re.search(re.escape(n), text, re.I):
            hits.append(n)
    gh_bad = github_hits(text)
    if gh_bad:
        hits.append("github.com:" + ",".join(sorted(set(gh_bad))))
    if hits:
        print("ANON CHECK FAIL:", "; ".join(hits))
        return 1
    print(
        "ANON CHECK PASS: zero hits for",
        ", ".join(NEEDLES),
        "+ non-allowlisted github.com",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
