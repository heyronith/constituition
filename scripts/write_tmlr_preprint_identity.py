#!/usr/bin/env python3
"""Write gitignored paper_tmlr/preprint_identity.tex from preprint_identity.local.json.

All author-identifying strings live only in the gitignored JSON. This script
embeds none of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "paper_tmlr" / "preprint_identity.local.json"
OUT = ROOT / "paper_tmlr" / "preprint_identity.tex"


def latex_escape_url(url: str) -> str:
    return url.replace("%", "\\%")


def main() -> int:
    if not LOCAL.exists():
        print(
            f"missing {LOCAL}\n"
            "Create it (gitignored) with keys: osf_url, github_url, authors "
            "[{name, email?, affiliation}, ...]. See scripts/init_tmlr_preprint_identity_local.py.",
            file=sys.stderr,
        )
        return 2

    data = json.loads(LOCAL.read_text(encoding="utf-8"))
    for key in ("osf_url", "github_url", "authors"):
        if key not in data:
            print(f"{LOCAL} missing required key {key!r}", file=sys.stderr)
            return 2
    authors = data["authors"]
    if not isinstance(authors, list) or len(authors) < 2:
        print(f"{LOCAL}: authors must be a list of at least two entries", file=sys.stderr)
        return 2

    def author_tex(a: dict, *, with_email: bool) -> str:
        name = a["name"]
        aff = a["affiliation"]
        if with_email and a.get("email"):
            return f"  \\name {name} \\email {a['email']} \\\\\n  \\addr {aff}"
        return f"  \\name {name} \\\\\n  \\addr {aff}"

    a0, a1 = authors[0], authors[1]
    github = latex_escape_url(str(data["github_url"]))
    osf = latex_escape_url(str(data["osf_url"]))

    tex = f"""%% Generated from preprint_identity.local.json — DO NOT COMMIT
\\renewcommand{{\\PreregAvailabilityClause}}{{%
  the preregistration, all materials, model generations, codes and analysis code are available at \\url{{{github}}}, and the preregistration is registered on OSF (\\url{{{osf}}})%
}}
\\newcommand{{\\TMLRAuthorBlock}}{{%
\\author{{%
{author_tex(a0, with_email=True)}
  \\AND
{author_tex(a1, with_email=False)}
}}}}
\\newcommand{{\\TMLRPreprintBackMatter}}{{%
\\section*{{Author Contributions}}
R.S.\\ conceived and designed the study and methodology, performed the literature review, conducted the experiments, curated the data, performed the formal analysis, prepared the figures and tables, administered the project and wrote the original draft with the AI assistance described in Section~\\ref{{sec:ai-tools}}. R.A.\\ supervised the project and reviewed and edited the manuscript.

\\section*{{Funding and Competing Interests}}
No funding was received for this study. The authors have no competing interests to declare.
}}
"""
    OUT.write_text(tex, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
