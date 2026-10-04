#!/usr/bin/env python3
"""Balance and validity report for constitution items. Report only; never edit wording."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

import textstat

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rc.materials import load_items, load_realism_audit  # noqa: E402

OVERRIDE_RE = re.compile(r"\b(even when|even if|whatever|whoever|regardless)\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(not|never|no)\b", re.IGNORECASE)
I_WILL_RE = re.compile(r"\bI will(?: not)?\b", re.IGNORECASE)
CONTENT_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "as",
    "by",
    "is",
    "are",
    "be",
    "i",
    "will",
    "not",
    "my",
    "me",
    "them",
    "their",
    "that",
    "this",
    "it",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _content_words(text: str) -> set[str]:
    return {w for w in _words(text) if w not in CONTENT_STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _features(text: str) -> dict:
    words = text.split()
    return {
        "word_count": len(words),
        "char_count": len(text),
        "fk_grade": float(textstat.flesch_kincaid_grade(text)),
        "has_i_will": bool(I_WILL_RE.search(text)),
        "negation_count": len(NEGATION_RE.findall(text)),
        "has_override": bool(OVERRIDE_RE.search(text)),
        "has_developers_or_responsible": (
            "developers" in text.lower() or "responsible for me" in text.lower()
        ),
    }


def main() -> int:
    items = load_items(ROOT)
    rows = []
    for item in items:
        for form, text in (("A", item.form_A), ("B", item.form_B)):
            feat = _features(text)
            rows.append(
                {
                    "item_id": item.item_id,
                    "category": item.category,
                    "agentic": item.agentic,
                    "form": form,
                    "text": text,
                    **feat,
                }
            )

    out_csv = ROOT / "reports" / "materials_balance.csv"
    out_md = ROOT / "reports" / "materials_balance.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "item_id",
        "category",
        "agentic",
        "form",
        "word_count",
        "char_count",
        "fk_grade",
        "has_i_will",
        "negation_count",
        "has_override",
        "has_developers_or_responsible",
        "text",
    ]
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})

    grand_mean = mean(r["word_count"] for r in rows)
    flags: list[str] = []

    for row in rows:
        if not 18 <= row["word_count"] <= 25:
            flags.append(
                f"WORD_COUNT_OUT_OF_RANGE {row['item_id']} form_{row['form']}: "
                f"{row['word_count']} words (expected 18–25)"
            )

    by_cat: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row["word_count"])
    for cat, vals in by_cat.items():
        m = mean(vals)
        if abs(m - grand_mean) / grand_mean > 0.10:
            flags.append(
                f"CATEGORY_MEAN_WORD_DEVIATION {cat}: mean={m:.2f} vs grand={grand_mean:.2f} "
                f"(>{10}% deviation)"
            )

    # A/B Jaccard on content words
    by_item = defaultdict(dict)
    for row in rows:
        by_item[row["item_id"]][row["form"]] = row["text"]
    for item_id, forms in by_item.items():
        jac = _jaccard(_content_words(forms["A"]), _content_words(forms["B"]))
        if jac > 0.6:
            flags.append(f"AB_JACCARD_TOO_HIGH {item_id}: content-word Jaccard={jac:.3f} (>0.6)")

    cat_rows_map: dict[str, list] = defaultdict(list)
    for row in rows:
        cat_rows_map[row["category"]].append(row)
    override_rates = {
        cat: mean(1.0 if r["has_override"] else 0.0 for r in cat_rows)
        for cat, cat_rows in cat_rows_map.items()
    }
    agentic_rows: dict[bool, list] = defaultdict(list)
    for row in rows:
        agentic_rows[bool(row["agentic"])].append(row)
    override_by_agentic = {
        flag: mean(1.0 if r["has_override"] else 0.0 for r in rs)
        for flag, rs in agentic_rows.items()
    }

    # Realism audit is a measurement probe (allow_eval_words via load_realism_audit).
    realism = load_realism_audit(ROOT)
    realism_note = f"PASS load_realism_audit (allow_eval_words; {len(realism)} chars)"

    def _sd(vals: list[float]) -> float:
        return pstdev(vals) if len(vals) > 1 else 0.0

    lines = [
        "# Materials balance report",
        "",
        "Generated by `scripts/materials_report.py`. Report only — wording not edited.",
        "",
        f"Grand mean word count: **{grand_mean:.2f}** (n={len(rows)} form texts).",
        "",
        "## Per-category means (± SD)",
        "",
        (
            "| category | word_count | char_count | fk_grade | negation_count | "
            "override_rate | developers/responsible |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cat in sorted(cat_rows_map):
        rs = cat_rows_map[cat]
        lines.append(
            "| {cat} | {wc:.1f} ± {wcs:.1f} | {cc:.1f} ± {ccs:.1f} | {fk:.1f} ± {fks:.1f} | "
            "{neg:.1f} ± {negs:.1f} | {ovr:.2f} | {dev:.2f} |".format(
                cat=cat,
                wc=mean(r["word_count"] for r in rs),
                wcs=_sd([r["word_count"] for r in rs]),
                cc=mean(r["char_count"] for r in rs),
                ccs=_sd([float(r["char_count"]) for r in rs]),
                fk=mean(r["fk_grade"] for r in rs),
                fks=_sd([r["fk_grade"] for r in rs]),
                neg=mean(r["negation_count"] for r in rs),
                negs=_sd([float(r["negation_count"]) for r in rs]),
                ovr=override_rates[cat],
                dev=mean(1.0 if r["has_developers_or_responsible"] else 0.0 for r in rs),
            )
        )

    lines += [
        "",
        "## Per-item form features",
        "",
        (
            "| item_id | form | words | chars | FK | I will | negations | "
            "override | developers/responsible | agentic |"
        ),
        "|---|---|---:|---:|---:|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['item_id']} | {row['form']} | {row['word_count']} | {row['char_count']} | "
            f"{row['fk_grade']:.1f} | {row['has_i_will']} | {row['negation_count']} | "
            f"{row['has_override']} | {row['has_developers_or_responsible']} | {row['agentic']} |"
        )

    lines += [
        "",
        "## Flags (verbatim)",
        "",
    ]
    if flags:
        for flag in flags:
            lines.append(f"- `{flag}`")
    else:
        lines.append("- (none)")

    lines += [
        "",
        "## Realism-audit prompt blinding",
        "",
        realism_note,
        "",
        "## Override phrase rate by category",
        "",
    ]
    for cat, rate in sorted(override_rates.items()):
        lines.append(f"- {cat}: {rate:.2f}")
    lines += ["", "## Override phrase rate by agentic", ""]
    for flag, rate in sorted(override_by_agentic.items(), key=lambda kv: kv[0]):
        lines.append(f"- agentic={flag}: {rate:.2f}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"wrote {out_csv.relative_to(ROOT)}")
    print(f"flags: {len(flags)}")
    for flag in flags:
        print(f"  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
