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

# Fragments that deanonymise the double-blind submission (case-insensitive).
# Built at runtime so this file does not contain contiguous identifying literals.
def _frag(*parts: str) -> str:
    return "".join(parts)


TRACKED_IDENTITY_FRAGMENTS = [
    _frag("m", "w", "8", "6"),
    _frag("o", "sf", r"\.io/", r"\S*"),
    _frag("hey", "ronith"),
    _frag("ron", "ith"),
    _frag("shar", "mila"),
    _frag("agra", "wal"),
    _frag("ru", "pesh"),
    _frag("swo", "su"),
    _frag("kent", "ucky"),
]

ANON_FORBIDDEN_PDF = [
    _frag("hey", "ronith"),
    _frag("Ron", "ith"),
    _frag("Shar", "mila"),
    _frag("Agra", "wal"),
    _frag("Ru", "pesh"),
    _frag("SWO", "SU"),
    _frag("Southwestern ", "Oklahoma"),
    _frag("Northern ", "Kentucky"),
    _frag("m", "w", "8", "6", "p"),
    _frag("o", "sf", ".io"),
    _frag("github.com/", "hey", "ronith"),
    _frag("swo", "su", ".edu"),
    _frag("nku", ".edu"),
]

# Paths where a hit fails the check (paper package + preprint identity writers).
FAIL_PATH_PREFIXES = (
    "paper_tmlr/",
    "scripts/write_tmlr_preprint_identity.py",
    "scripts/init_tmlr_preprint_identity_local.py",
)

# Checker / anonymiser tooling may name the needles; skip self-matches.
SKIP_SCAN_PREFIXES = (
    "paper_mlj/",
    "scripts/tmlr_checks.py",
    "scripts/aie_checks.py",
    "reports/anonymisation_terms.md",
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


def anon_hits_in_text(text: str, where: str, needles: list[str] | None = None) -> list[str]:
    hits = []
    for needle in needles or ANON_FORBIDDEN_PDF:
        if re.search(re.escape(needle), text, flags=re.I):
            m = re.search(re.escape(needle), text, flags=re.I)
            ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
            hits.append(f"{where}: {needle!r} :: {ctx}")
    return hits


def tracked_identity_scan() -> tuple[list[str], list[str]]:
    """Scan git-tracked files for identity fragments.

    Returns (fail_hits, report_hits). Fail hits are in the paper package or
    preprint identity writers. Report hits are every other match outside
    paper_mlj/ (not silently fixed).
    """
    listed = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, text=True
    ).split("\0")
    fail_hits: list[str] = []
    report_hits: list[str] = []
    skip_ext = {
        ".pdf",
        ".eps",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".zip",
        ".gz",
        ".tar",
        ".xz",
        ".whl",
        ".so",
        ".dylib",
        ".pyc",
        ".pkl",
        ".joblib",
        ".npy",
        ".npz",
        ".pt",
        ".bin",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    }
    patterns = [(frag, re.compile(frag, flags=re.I)) for frag in TRACKED_IDENTITY_FRAGMENTS]
    for rel in listed:
        if not rel:
            continue
        if any(rel == p or rel.startswith(p) for p in SKIP_SCAN_PREFIXES):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in skip_ext:
            continue
        try:
            raw = path.read_bytes()
        except OSError as e:
            report_hits.append(f"{rel}: read failed: {e}")
            continue
        if b"\0" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                continue
        file_hits: list[str] = []
        for frag, cre in patterns:
            for m in cre.finditer(text):
                ctx = text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
                file_hits.append(f"{rel}: /{frag}/ :: ...{ctx}...")
        if not file_hits:
            continue
        if any(rel == p or rel.startswith(p) for p in FAIL_PATH_PREFIXES):
            fail_hits.extend(file_hits)
        else:
            report_hits.extend(file_hits)
    return fail_hits, report_hits


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

    fail_hits, report_hits = tracked_identity_scan()
    print(f"anon_hits_tracked_fail={len(fail_hits)}")
    for h in fail_hits[:50]:
        print(" ", h)
        errors.append(h)
    print(f"anon_hits_tracked_report={len(report_hits)}")
    # Report other hits; do not silently fix. Summarise by path for the log.
    from collections import Counter

    by_path = Counter(h.split(":", 1)[0] for h in report_hits)
    for path, n in sorted(by_path.items(), key=lambda x: (-x[1], x[0]))[:40]:
        print(f"  REPORT {n:3d}  {path}")
    if len(by_path) > 40:
        print(f"  REPORT ... and {len(by_path) - 40} more paths")
    for h in report_hits[:15]:
        print(f"  REPORT_CTX {h}")

    if PREPRINT_PDF.exists():
        pre_txt = pdf_text(PREPRINT_PDF)
        need_any = [_frag("Ron", "ith"), _frag("Shar", "mila"), _frag("Agra", "wal")]
        missing = [n for n in need_any if n.lower() not in pre_txt.lower()]
        print(f"preprint_required_present={not missing}")
        if missing:
            errors.append(f"preprint.pdf missing: {missing}")
        if _frag("o", "sf", ".io/") not in pre_txt.lower():
            errors.append("preprint.pdf missing OSF URL")
        if "github.com/" not in pre_txt.lower():
            errors.append("preprint.pdf missing GitHub URL")
        if "Broader Impact" not in pre_txt:
            errors.append("preprint.pdf missing Broader Impact Statement")
    else:
        print("preprint.pdf: not built yet (run make tmlr-preprint)")

    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "paper_number_audit.py"), "--tmlr"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        print((r.stdout or "")[-500:])
        if r.stderr:
            print((r.stderr or "")[-300:])
        if r.returncode != 0 or "PASS" not in (r.stdout or ""):
            errors.append("number audit did not PASS (--tmlr)")
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
