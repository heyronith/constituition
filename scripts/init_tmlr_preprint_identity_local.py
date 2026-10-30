#!/usr/bin/env python3
"""One-shot local helper: build gitignored preprint_identity.local.json.

Reads paper_aie/title_page.tex, git remote, and TMLR_OSF_URL from the
environment. Embeds no identity literals in this file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLE = ROOT / "paper_aie" / "title_page.tex"
OUT = ROOT / "paper_tmlr" / "preprint_identity.local.json"


def main() -> int:
    if not TITLE.exists():
        print(f"missing {TITLE}", file=sys.stderr)
        return 2
    osf_url = os.environ.get("TMLR_OSF_URL", "").strip()
    if not osf_url and OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        osf_url = str(prev.get("osf_url", "")).strip()
    if not osf_url:
        print(
            "Set TMLR_OSF_URL to the full OSF registration URL "
            "(export TMLR_OSF_URL=<scheme>://<osf-host>/<id>).",
            file=sys.stderr,
        )
        return 2

    text = TITLE.read_text(encoding="utf-8")
    m1 = re.search(
        r"^([A-Za-z][A-Za-z .'\-]+)\\textsuperscript\{1\*?\}\s*\\\\",
        text,
        flags=re.M,
    )
    m2 = re.search(
        r"^([A-Za-z][A-Za-z .'\-]+)\\textsuperscript\{2\}\s*$",
        text,
        flags=re.M,
    )
    m_aff = re.search(
        r"\\textsuperscript\{1\}(.*?)\\\\\s*\\textsuperscript\{2\}(.*?)$",
        text,
        flags=re.M | re.S,
    )
    m_email = re.search(r"^Email:\s*(\S+)\s*$", text, flags=re.M)
    if not (m1 and m2 and m_aff and m_email):
        print("could not parse title_page.tex", file=sys.stderr)
        return 2

    origin = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    if origin.endswith(".git"):
        origin = origin[:-4]
    if origin.startswith("git@"):
        origin = "https://" + origin.split("@", 1)[1].replace(":", "/", 1)

    aff1 = re.sub(r"\s+", " ", m_aff.group(1)).strip().rstrip("\\").strip()
    aff2 = re.sub(r"\s+", " ", m_aff.group(2)).strip().rstrip("\\").strip()
    aff2 = aff2.split("\\par")[0].strip()

    data = {
        "osf_url": osf_url,
        "github_url": origin,
        "authors": [
            {
                "name": m1.group(1).strip(),
                "email": m_email.group(1).strip(),
                "affiliation": aff1,
            },
            {
                "name": m2.group(1).strip(),
                "affiliation": aff2,
            },
        ],
    }
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
