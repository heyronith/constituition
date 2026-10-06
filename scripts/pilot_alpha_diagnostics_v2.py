#!/usr/bin/env python3
"""Phase 4E Session 2: keyed pilot_v1_coding_v2 α diagnostics (CPU only)."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.judge_integrity import run_integrity_gates
from rc.judge_metrics import BINARY_ERODED, BINARY_NOT_ERODED, binary_erosion_label
from rc.judging import normalize_fate, structural_fate
from rc.pilot_coding import extract_pilot_transitions

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pilot_alpha_diagnostics import (  # noqa: E402
    MASTER_SEED,
    _fmt,
    _pair_table_md,
    check_pairing,
    merge_line_text,
    pair_stats,
)

SEVERE = frozenset({"SUBORDINATED", "INVERTED", "DELETED"})
CODING_ROOT = Path("runs/pilot_v1_coding_v2")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_role_by_key(path: Path) -> dict[str, dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(path):
        key = row.get("judgment_key") or row.get("transition_id")
        if not key:
            raise SystemExit(f"missing key in {path}")
        if key in by:
            raise SystemExit(f"duplicate key {key} in {path}")
        by[str(key)] = row
    return by


def severe_label(fate: str | None) -> str:
    n = normalize_fate(fate) or ""
    return "SEVERE" if n in SEVERE else "OTHER"


def icc_2_1(ratings: list[list[float]]) -> dict[str, float]:
    """Shrout & Fleiss ICC(2,1) two-way random, single rater, absolute agreement."""
    n = len(ratings)
    k = len(ratings[0]) if ratings else 0
    if n < 2 or k < 2:
        return {"icc": float("nan"), "n": float(n), "k": float(k)}
    grand = sum(sum(row) for row in ratings) / (n * k)
    row_means = [sum(row) / k for row in ratings]
    col_means = [sum(row[j] for row in ratings) / n for j in range(k)]
    ss_between_subjects = k * sum((m - grand) ** 2 for m in row_means)
    ss_between_raters = n * sum((m - grand) ** 2 for m in col_means)
    ss_total = sum((x - grand) ** 2 for row in ratings for x in row)
    ss_error = ss_total - ss_between_subjects - ss_between_raters
    msr = ss_between_subjects / (n - 1)
    msc = ss_between_raters / (k - 1)
    mse = ss_error / ((n - 1) * (k - 1)) if n > 1 and k > 1 else float("nan")
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    icc = (msr - mse) / denom if denom else float("nan")
    return {
        "icc": icc,
        "n": float(n),
        "k": float(k),
        "msr": msr,
        "msc": msc,
        "mse": mse,
    }


def main() -> None:
    root = repo_root()
    rng = random.Random(MASTER_SEED)
    summary = json.loads((root / CODING_ROOT / "pilot_coding_summary_v2.json").read_text())
    roles = {"j1": summary["j1"], "j2": summary["j2"], "j3": summary["j3"]}
    coding_dir = root / CODING_ROOT / "coding_v2"
    maps = {
        "j1": load_role_by_key(coding_dir / f"j1_{roles['j1']}.jsonl"),
        "j2": load_role_by_key(coding_dir / f"j2_{roles['j2']}.jsonl"),
        "j3": load_role_by_key(coding_dir / f"j3_{roles['j3']}.jsonl"),
    }

    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = [
        t
        for t in transitions
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted")))
        is None
    ]
    for t in llm_items:
        tid = t["transition_id"]
        for role in roles:
            if tid not in maps[role]:
                raise SystemExit(f"{role} missing {tid}")

    pairing = check_pairing(root, llm_items)
    by_role_rows = {role: [maps[role][t["transition_id"]] for t in llm_items] for role in roles}
    gates_by_role = {role: run_integrity_gates(rows, root=root) for role, rows in by_role_rows.items()}
    # Orchestrator stored J1+J2 only (finalize_coding).
    gates_j1j2 = run_integrity_gates(by_role_rows["j1"] + by_role_rows["j2"], root=root)
    gates_all = run_integrity_gates(
        by_role_rows["j1"] + by_role_rows["j2"] + by_role_rows["j3"], root=root
    )

    labels: dict[str, list[str]] = {r: [] for r in roles}
    severe: dict[str, list[str]] = {r: [] for r in roles}
    strengths: list[list[float]] = []
    meta_rows: list[dict[str, Any]] = []
    for t in llm_items:
        tid = t["transition_id"]
        row_meta: dict[str, Any] = {
            "transition_id": tid,
            "item_id": t.get("item_id"),
            "protocol": t.get("protocol"),
            "condition": t.get("condition"),
            "kind": t.get("kind"),
            "is_merge": bool(t.get("other")) or t.get("decision") == "merge",
            "transition_type": (
                "cumulative" if str(t.get("kind", "")).startswith("cumulative") else "per_round"
            ),
            "original": t.get("original"),
            "revised": t.get("rewrite"),
            "other": t.get("other"),
            "merge_line": merge_line_text(t.get("other")),
        }
        srow: list[float] = []
        for role in roles:
            j = maps[role][tid]
            fate = j.get("fate")
            lab = binary_erosion_label(fate) or "?"
            labels[role].append(lab)
            severe[role].append(severe_label(fate))
            try:
                srow.append(float(j.get("strength") if j.get("strength") is not None else float("nan")))
            except (TypeError, ValueError):
                srow.append(float("nan"))
            row_meta[f"{role}_fate"] = fate
            row_meta[f"{role}_binary"] = lab
            row_meta[f"{role}_strength"] = j.get("strength")
            row_meta[f"{role}_rationale"] = j.get("rationale")
        strengths.append(srow)
        meta_rows.append(row_meta)

    n = len(meta_rows)
    eroded_rates = {
        roles[role]: sum(x == BINARY_ERODED for x in labels[role]) / n for role in roles
    }
    severe_mapped = {
        role: [BINARY_ERODED if x == "SEVERE" else BINARY_NOT_ERODED for x in severe[role]]
        for role in roles
    }
    pair_j1j2 = pair_stats(labels["j1"], labels["j2"])
    pair_j1j3 = pair_stats(labels["j1"], labels["j3"])
    pair_j2j3 = pair_stats(labels["j2"], labels["j3"])
    severe_j1j2 = pair_stats(severe_mapped["j1"], severe_mapped["j2"])
    severe_j1j3 = pair_stats(severe_mapped["j1"], severe_mapped["j3"])
    severe_j2j3 = pair_stats(severe_mapped["j2"], severe_mapped["j3"])

    def stratum(pred) -> dict[str, Any]:
        idx = [i for i, r in enumerate(meta_rows) if pred(r)]
        return pair_stats([labels["j1"][i] for i in idx], [labels["j2"][i] for i in idx])

    strata = {
        "protocol": {
            "FORCED": stratum(lambda r: r["protocol"] == "FORCED"),
            "PERMISSIVE": stratum(lambda r: r["protocol"] == "PERMISSIVE"),
        },
        "condition": {
            c: stratum(lambda r, cc=c: r["condition"] == cc)
            for c in sorted({r["condition"] for r in meta_rows})
        },
        "transition_type": {
            "per_round": stratum(lambda r: r["transition_type"] == "per_round"),
            "cumulative": stratum(lambda r: r["transition_type"] == "cumulative"),
        },
        "merge": {
            "merge": stratum(lambda r: r["is_merge"]),
            "non_merge": stratum(lambda r: not r["is_merge"]),
        },
    }

    icc_rows = [row for row in strengths if all(not math.isnan(x) for x in row)]
    icc = icc_2_1(icc_rows)

    disagree_idx = [i for i, r in enumerate(meta_rows) if r["j1_binary"] != r["j2_binary"]]
    pick = disagree_idx if len(disagree_idx) <= 40 else rng.sample(disagree_idx, 40)
    examples = []
    for i in sorted(pick):
        r = meta_rows[i]
        examples.append(
            {
                "transition_id": r["transition_id"],
                "item_id": r["item_id"],
                "kind": r["kind"],
                "protocol": r["protocol"],
                "condition": r["condition"],
                "original": r["original"],
                "revised": r["revised"],
                "merge_line": r["merge_line"],
                "j1_fate": r["j1_fate"],
                "j2_fate": r["j2_fate"],
                "j3_fate": r["j3_fate"],
                "j1_strength": r["j1_strength"],
                "j2_strength": r["j2_strength"],
                "j3_strength": r["j3_strength"],
                "j1_binary": r["j1_binary"],
                "j2_binary": r["j2_binary"],
                "j3_binary": r["j3_binary"],
                "j1_rationale": r["j1_rationale"],
                "j2_rationale": r["j2_rationale"],
                "j3_rationale": r["j3_rationale"],
            }
        )

    payload = {
        "roles": roles,
        "n_llm": n,
        "pairing": {
            "n_checked": pairing["n_checked"],
            "n_violations": pairing["n_violations"],
            "violations_by_type": pairing["violations_by_type"],
        },
        "integrity_gates": {
            "orchestrator_j1_j2": gates_j1j2,
            "per_role": gates_by_role,
            "all_three": gates_all,
        },
        "eroded_rates": eroded_rates,
        "all_pairs": {"j1_j2": pair_j1j2, "j1_j3": pair_j1j3, "j2_j3": pair_j2j3},
        "severe_pairs": {"j1_j2": severe_j1j2, "j1_j3": severe_j1j3, "j2_j3": severe_j2j3},
        "strata": strata,
        "icc_2_1": icc,
        "n_disagreements_j1j2": len(disagree_idx),
        "disagreement_examples": examples,
        "summary": {
            "j1_j2_alpha": summary.get("j1_j2_alpha"),
            "alpha_gate_pass": summary.get("alpha_gate_pass"),
            "n_transitions": summary.get("n_transitions"),
            "n_structural": summary.get("n_structural"),
        },
    }
    (root / "reports" / "pilot_alpha_diagnostics_v2.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    write_md(root / "reports" / "pilot_alpha_diagnostics_v2.md", payload, roles)
    print(
        json.dumps(
            {
                "n_llm": n,
                "pairing_violations": pairing["n_violations"],
                "j1j2_gates_ok": gates_j1j2["ok"],
                "j1_j2_alpha": pair_j1j2["binary_alpha"],
                "eroded_rates": eroded_rates,
                "icc": icc["icc"],
                "n_disagree": len(disagree_idx),
            },
            indent=2,
        )
    )


def write_md(path: Path, payload: dict[str, Any], roles: dict[str, str]) -> None:
    lines: list[str] = []
    lines.append("# Pilot α diagnostics v2 (Phase 4E Session 2)\n")
    lines.append(
        "Keyed `pilot_v1_coding_v2` join (D40). "
        f"J1=`{roles['j1']}`, J2=`{roles['j2']}`, J3=`{roles['j3']}`. "
        "No judges, rules, or thresholds changed.\n"
    )
    p = payload["pairing"]
    g = payload["integrity_gates"]
    lines.append("## Integrity and pairing\n")
    lines.append(
        f"- Pairing violations: **{p['n_violations']}** / {p['n_checked']}"
        + (f" ({p['violations_by_type']})" if p["violations_by_type"] else "")
    )
    oj = g["orchestrator_j1_j2"]
    lines.append(
        f"- Orchestrator gate (J1+J2, as run before α): "
        f"**{'PASS' if oj['ok'] else 'FAIL'}**; "
        f"prompt-hash {oj['prompt_hash']['n_checked']} checked / "
        f"{oj['prompt_hash']['n_mismatch']} mismatch; "
        f"quote hit_rate={_fmt(oj['quote_audit']['hit_rate'])} "
        f"(n_phrases={oj['quote_audit']['n_phrases']})"
    )
    for role, jid in roles.items():
        gr = g["per_role"][role]
        lines.append(
            f"- `{jid}` ({role}): prompt-hash "
            f"{'PASS' if gr['prompt_hash']['ok'] else 'FAIL'} "
            f"({gr['prompt_hash']['n_checked']} checked); "
            f"quote hit_rate={_fmt(gr['quote_audit']['hit_rate'])} "
            f"(n_phrases={gr['quote_audit']['n_phrases']})"
        )
    ga = g["all_three"]
    lines.append(
        f"- All three judges pooled: quote hit_rate={_fmt(ga['quote_audit']['hit_rate'])} "
        f"(n_phrases={ga['quote_audit']['n_phrases']}; J3 gpt-oss supplies nearly all quoted spans)"
    )
    lines.append("")

    lines.append("## Prevalence (binary ERODED)\n")
    lines.append("| judge | role | ERODED rate |")
    lines.append("|---|---|---|")
    for role, jid in roles.items():
        lines.append(f"| {jid} | {role} | {_fmt(payload['eroded_rates'][jid])} |")
    lines.append("")

    lines.append("## All judge pairs (binary ERODED)\n")
    for key, title in (("j1_j2", "J1–J2"), ("j1_j3", "J1–J3"), ("j2_j3", "J2–J3")):
        lines.append(f"### {title}\n")
        left, right = title.split("–")
        lines.extend(_pair_table_md(payload["all_pairs"][key], left, right))

    lines.append("## J1–J2 strata\n")
    for group, block in payload["strata"].items():
        lines.append(f"### By {group}\n")
        lines.append("| stratum | n | % agree | κ | PABAK | binary α | ERODED₁ | ERODED₂ |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for name, st in block.items():
            lines.append(
                f"| {name} | {st['n']} | {_fmt(st['pct_agreement'])} | "
                f"{_fmt(st['cohen_kappa'])} | {_fmt(st['pabak'])} | "
                f"{_fmt(st['binary_alpha'])} | {_fmt(st['eroded_rate_1'])} | "
                f"{_fmt(st['eroded_rate_2'])} |"
            )
        lines.append("")

    lines.append(
        "## Severe erosion (SUBORDINATED / INVERTED / DELETED vs everything else)\n"
    )
    for key, title in (("j1_j2", "J1–J2"), ("j1_j3", "J1–J3"), ("j2_j3", "J2–J3")):
        st = payload["severe_pairs"][key]
        lines.append(
            f"- **{title}**: n={st['n']}, %agree={_fmt(st['pct_agreement'])}, "
            f"κ={_fmt(st['cohen_kappa'])}, PABAK={_fmt(st['pabak'])}, "
            f"α={_fmt(st['binary_alpha'])}, "
            f"SEVERE₁={_fmt(st['eroded_rate_1'])}, SEVERE₂={_fmt(st['eroded_rate_2'])}"
        )
    lines.append("")
    lines.append("### J1–J2 severe 2×2\n")
    t = payload["severe_pairs"]["j1_j2"]["table"]
    lines.append("| | J2=SEVERE | J2=OTHER |")
    lines.append("|---|---|---|")
    lines.append(f"| J1=SEVERE | {t['ERODED']['ERODED']} | {t['ERODED']['NOT_ERODED']} |")
    lines.append(
        f"| J1=OTHER | {t['NOT_ERODED']['ERODED']} | {t['NOT_ERODED']['NOT_ERODED']} |"
    )
    lines.append("")
    lines.append(
        "Table cells reuse the binary pair_stats layout (SEVERE mapped to ERODED, OTHER to NOT_ERODED).\n"
    )

    icc = payload["icc_2_1"]
    lines.append("## ICC(2,1) of 0–4 strength scores (J1, J2, J3)\n")
    lines.append(
        f"ICC(2,1) = **{_fmt(icc['icc'])}** (n={int(icc['n'])} items, k={int(icc['k'])} raters; "
        f"MSR={_fmt(icc.get('msr'))}, MSC={_fmt(icc.get('msc'))}, MSE={_fmt(icc.get('mse'))}).\n"
    )

    lines.append(
        f"## 40 random J1–J2 disagreements (of {payload['n_disagreements_j1j2']})\n"
    )
    for i, ex in enumerate(payload["disagreement_examples"], 1):
        lines.append(
            f"### Disagreement {i} (`{ex['item_id']}`, {ex['kind']}, "
            f"{ex['protocol']}/{ex['condition']})\n"
        )
        lines.append(f"- ORIGINAL: {ex['original']}")
        lines.append(f"- REVISED: {ex['revised']}")
        lines.append(f"- merge line: {ex['merge_line'] or '(none)'}")
        lines.append(
            f"- labels: J1={ex['j1_fate']} (str {ex['j1_strength']}, {ex['j1_binary']}), "
            f"J2={ex['j2_fate']} (str {ex['j2_strength']}, {ex['j2_binary']}), "
            f"J3={ex['j3_fate']} (str {ex['j3_strength']}, {ex['j3_binary']})"
        )
        lines.append(f"- J1 rationale: {ex['j1_rationale']}")
        lines.append(f"- J2 rationale: {ex['j2_rationale']}")
        lines.append(f"- J3 rationale: {ex['j3_rationale']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
