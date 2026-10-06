#!/usr/bin/env python3
"""Phase 4D Session 2: diagnose pilot binary-α failure (CPU only)."""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.judge_metrics import (
    BINARY_ERODED,
    BINARY_NOT_ERODED,
    binary_erosion_label,
    cohen_kappa_binary,
    krippendorff_alpha_ordinal,
    metrics_for_judge,
    select_judges_d33,
    select_judges_d38,
)
from rc.judging import normalize_fate, structural_fate
from rc.pilot_coding import extract_pilot_transitions

MASTER_SEED = 20261004
JUDGES = (
    "granite41_8b",
    "mistral_small32_24b",
    "nemotron3_nano_30b",
    "gptoss_120b",
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fmt(x: Any, d: int = 4) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        return f"{x:.{d}f}"
    return str(x)


def pabak(y1: list[str], y2: list[str]) -> float:
    """Prevalence-adjusted bias-adjusted kappa for binary labels (2 categories)."""
    if not y1:
        return float("nan")
    n = len(y1)
    po = sum(a == b for a, b in zip(y1, y2, strict=True)) / n
    # For dichotomous ratings: PABAK = 2*po - 1
    return 2.0 * po - 1.0


def pair_stats(y1: list[str], y2: list[str]) -> dict[str, Any]:
    n = len(y1)
    if n == 0:
        return {
            "n": 0,
            "table": {},
            "pct_agreement": float("nan"),
            "cohen_kappa": float("nan"),
            "pabak": float("nan"),
            "binary_alpha": float("nan"),
            "eroded_rate_1": float("nan"),
            "eroded_rate_2": float("nan"),
        }
    table = {
        BINARY_ERODED: {BINARY_ERODED: 0, BINARY_NOT_ERODED: 0},
        BINARY_NOT_ERODED: {BINARY_ERODED: 0, BINARY_NOT_ERODED: 0},
    }
    for a, b in zip(y1, y2, strict=True):
        table[a][b] += 1
    po = sum(a == b for a, b in zip(y1, y2, strict=True)) / n
    ratings = [
        [
            1.0 if a == BINARY_ERODED else 0.0,
            1.0 if b == BINARY_ERODED else 0.0,
        ]
        for a, b in zip(y1, y2, strict=True)
    ]
    return {
        "n": n,
        "table": table,
        "pct_agreement": po,
        "cohen_kappa": cohen_kappa_binary(y1, y2),
        "pabak": pabak(y1, y2),
        "binary_alpha": krippendorff_alpha_ordinal(ratings),
        "eroded_rate_1": sum(a == BINARY_ERODED for a in y1) / n,
        "eroded_rate_2": sum(b == BINARY_ERODED for b in y2) / n,
    }


def chain_dir(root: Path, t: dict[str, Any]) -> Path:
    return (
        root
        / "runs"
        / "pilot_v1"
        / t["config_id"]
        / t["protocol"]
        / t["condition"]
        / "STRUCTURED"
        / t["chain"]
    )


def lineage_descendants(lineage: list[dict[str, Any]]) -> dict[str, set[str]]:
    """opaque_id -> set of ancestor opaque_ids (including self)."""
    parents: dict[str, list[str]] = {}
    for row in lineage:
        oid = row.get("opaque_id")
        if not oid:
            continue
        parents[oid] = list(row.get("parent_ids") or [])

    cache: dict[str, set[str]] = {}

    def ancestors(oid: str, stack: set[str] | None = None) -> set[str]:
        if oid in cache:
            return cache[oid]
        stack = stack or set()
        if oid in stack:
            return {oid}
        stack = set(stack)
        stack.add(oid)
        out = {oid}
        for p in parents.get(oid, []):
            out |= ancestors(p, stack)
        cache[oid] = out
        return out

    for oid in parents:
        ancestors(oid)
    return cache


def check_pairing(root: Path, transitions: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify REVISED descends from ORIGINAL's item_id via lineage."""
    violations: list[dict[str, Any]] = []
    checked = 0
    for t in transitions:
        checked += 1
        item_id = t.get("item_id")
        original = (t.get("original") or "").strip()
        rewrite = (t.get("rewrite") or "") if not t.get("deleted") else None
        cdir = chain_dir(root, t)
        lineage = _load_jsonl(cdir / "lineage.jsonl")
        if not lineage:
            violations.append({**t, "violation": "missing_lineage"})
            continue

        # Oids ever tagged with this item_id.
        item_oids = {
            r["opaque_id"]
            for r in lineage
            if r.get("item_id") == item_id and r.get("opaque_id")
        }
        if not item_oids:
            violations.append({**t, "violation": "item_id_absent_in_lineage"})
            continue

        anc = lineage_descendants(lineage)
        # Find oids whose after_text matches rewrite (or delete).
        if t.get("deleted") or rewrite is None:
            # Deleted: no surviving oid with this item_id at/after round should hold text.
            # Treat as OK if item_id has no after_text equal to original at later rounds.
            checked_ok = True
            # Soft check: original should appear as before_text or after_text for item oid.
            orig_ok = any(
                (r.get("before_text") or "").strip() == original
                or (r.get("after_text") or "").strip() == original
                for r in lineage
                if r.get("item_id") == item_id
            )
            if not orig_ok and original:
                violations.append({**t, "violation": "original_not_in_item_lineage"})
            continue

        rewrite_s = rewrite.strip()
        rewrite_oids = [
            r["opaque_id"]
            for r in lineage
            if r.get("opaque_id") and (r.get("after_text") or "").strip() == rewrite_s
        ]
        if not rewrite_oids:
            # Cumulative: constitution text may match without exact lineage after_text
            # if principle was kept unchanged across rounds (after_text only on change).
            # Fall back: constitutions metadata item_id → text.
            cons_path = cdir / "constitutions.jsonl"
            cons_rows = _load_jsonl(cons_path)
            rnd = int(t.get("round") or 0)
            cons_t = next(
                (r for r in reversed(cons_rows) if int(r.get("round", -1)) == rnd),
                None,
            )
            cons0 = next(
                (r for r in cons_rows if int(r.get("round", -1)) == 0),
                None,
            )
            ok = False
            if cons_t and cons0:
                meta_t = cons_t.get("metadata") or {}
                texts_t = {p["opaque_id"]: p["text"] for p in cons_t.get("principles") or []}
                for oid, m in meta_t.items():
                    if m.get("item_id") == item_id and (texts_t.get(oid) or "").strip() == rewrite_s:
                        ok = True
                        break
            if not ok:
                violations.append({**t, "violation": "revised_text_not_in_lineage"})
            continue

        # REVISED oid must descend from some oid that carried item_id, OR itself carry item_id.
        ok = False
        for rid in rewrite_oids:
            if rid in item_oids:
                ok = True
                break
            aset = anc.get(rid, {rid})
            if aset & item_oids:
                ok = True
                break
            # Also: lineage row for rewrite may itself have item_id.
            for r in lineage:
                if r.get("opaque_id") == rid and r.get("item_id") == item_id:
                    ok = True
                    break
        if not ok:
            violations.append({**t, "violation": "revised_not_descendant_of_item_id"})

        # ORIGINAL should belong to item_id lineage.
        orig_ok = any(
            (r.get("before_text") or "").strip() == original
            or (r.get("after_text") or "").strip() == original
            for r in lineage
            if r.get("item_id") == item_id or r.get("opaque_id") in item_oids
        )
        if not orig_ok and t.get("kind") == "per_round_absorbed":
            # Absorbed partner: original is absorbed principle; item_id is absorbed's id.
            orig_ok = any(
                (r.get("before_text") or "").strip() == original
                for r in lineage
            )
        if not orig_ok and original:
            violations.append({**t, "violation": "original_not_in_item_lineage"})

    by_type = Counter(v.get("violation") for v in violations)
    return {
        "n_checked": checked,
        "n_violations": len(violations),
        "violations_by_type": dict(by_type),
        "violation_examples": violations[:20],
    }


def merge_line_text(other: str | None) -> str | None:
    if not other:
        return None
    return (
        'The REVISED principle was created by combining ORIGINAL with this other '
        f'principle: "{other}"'
    )


def load_judge_maps(root: Path) -> tuple[dict[str, str], dict[str, dict[int, dict]]]:
    summary = json.loads(
        (root / "runs" / "phase4_coding" / "pilot_coding_summary.json").read_text()
    )
    roles = {"j1": summary["j1"], "j2": summary["j2"], "j3": summary["j3"]}
    coding_dir = root / "runs" / "phase4_coding" / "coding"
    maps: dict[str, dict[int, dict]] = {}
    for role, jid in roles.items():
        rows = _load_jsonl(coding_dir / f"{role}_{jid}.jsonl")
        maps[role] = {int(r["item_index"]): r for r in rows}
    return roles, maps


def main() -> None:
    root = repo_root()
    rng = random.Random(MASTER_SEED)

    # --- Enrich / ensure calib_v2 committed layout ---
    calib_dir = root / "runs" / "judge_calib_v2"
    per_calib = {jid: _load_jsonl(calib_dir / f"{jid}.jsonl") for jid in JUDGES}
    for jid, rows in per_calib.items():
        if not rows:
            raise SystemExit(f"missing calib_v2 for {jid}")

    transitions = extract_pilot_transitions("pilot_v1", root=root)
    llm_items = [
        t
        for t in transitions
        if structural_fate(t["original"], t.get("rewrite"), deleted=bool(t.get("deleted")))
        is None
    ]
    roles, maps = load_judge_maps(root)
    assert len(maps["j1"]) == len(llm_items), (len(maps["j1"]), len(llm_items))

    # Pairing integrity over all coded (LLM) transitions.
    pairing = check_pairing(root, llm_items)

    # 20 random transitions for display.
    sample_idx = sorted(rng.sample(range(len(llm_items)), min(20, len(llm_items))))
    sample_rows = []
    for i in sample_idx:
        t = llm_items[i]
        sample_rows.append(
            {
                "item_index": i,
                "item_id": t.get("item_id"),
                "transition_id": t.get("transition_id"),
                "kind": t.get("kind"),
                "decision": t.get("decision"),
                "protocol": t.get("protocol"),
                "condition": t.get("condition"),
                "original": t.get("original"),
                "revised": t.get("rewrite"),
                "merge_line": merge_line_text(t.get("other")),
                "had_other": bool(t.get("other")),
            }
        )

    # Binary labels per role.
    labels: dict[str, list[str]] = {r: [] for r in roles}
    meta_rows: list[dict[str, Any]] = []
    for i, t in enumerate(llm_items):
        row_meta = {
            "item_index": i,
            "protocol": t.get("protocol"),
            "condition": t.get("condition"),
            "kind": t.get("kind"),
            "is_merge": bool(t.get("other")) or t.get("decision") == "merge",
            "transition_type": (
                "cumulative" if str(t.get("kind", "")).startswith("cumulative") else "per_round"
            ),
            "item_id": t.get("item_id"),
            "original": t.get("original"),
            "revised": t.get("rewrite"),
            "other": t.get("other"),
            "merge_line": merge_line_text(t.get("other")),
            "transition_id": t.get("transition_id"),
        }
        for role in roles:
            fate = maps[role][i].get("fate")
            lab = binary_erosion_label(fate) or "?"
            labels[role].append(lab)
            row_meta[f"{role}_fate"] = fate
            row_meta[f"{role}_binary"] = lab
            row_meta[f"{role}_rationale"] = maps[role][i].get("rationale")
            row_meta[f"{role}_finish_reason"] = maps[role][i].get("finish_reason")
        meta_rows.append(row_meta)

    eroded_rates = {
        roles[role]: sum(x == BINARY_ERODED for x in labels[role]) / len(labels[role])
        for role in roles
    }

    pair_j1j2 = pair_stats(labels["j1"], labels["j2"])
    pair_j1j3 = pair_stats(labels["j1"], labels["j3"])
    pair_j2j3 = pair_stats(labels["j2"], labels["j3"])

    def stratum(pred) -> dict[str, Any]:
        idx = [i for i, r in enumerate(meta_rows) if pred(r)]
        y1 = [labels["j1"][i] for i in idx]
        y2 = [labels["j2"][i] for i in idx]
        return pair_stats(y1, y2)

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

    # 30 random J1–J2 disagreements.
    disagree_idx = [
        i for i, r in enumerate(meta_rows) if r["j1_binary"] != r["j2_binary"]
    ]
    pick = disagree_idx if len(disagree_idx) <= 30 else rng.sample(disagree_idx, 30)
    pick = sorted(pick)
    examples = []
    for i in pick:
        r = meta_rows[i]
        examples.append(
            {
                "item_index": i,
                "transition_id": r["transition_id"],
                "item_id": r["item_id"],
                "kind": r["kind"],
                "protocol": r["protocol"],
                "condition": r["condition"],
                "original": r["original"],
                "revised": r["revised"],
                "merge_line": r["merge_line"],
                "j1": roles["j1"],
                "j2": roles["j2"],
                "j3": roles["j3"],
                "j1_fate": r["j1_fate"],
                "j2_fate": r["j2_fate"],
                "j3_fate": r["j3_fate"],
                "j1_binary": r["j1_binary"],
                "j2_binary": r["j2_binary"],
                "j3_binary": r["j3_binary"],
                "j1_rationale": r["j1_rationale"],
                "j2_rationale": r["j2_rationale"],
                "j3_rationale": r["j3_rationale"],
            }
        )

    # Calib metrics for PHASE_4D.
    d38 = select_judges_d38(per_calib)
    d33 = select_judges_d33(per_calib)
    d33_metrics = {jid: metrics_for_judge(rows) for jid, rows in per_calib.items()}

    payload = {
        "roles": roles,
        "pairing": {
            "n_checked": pairing["n_checked"],
            "n_violations": pairing["n_violations"],
            "violations_by_type": pairing["violations_by_type"],
        },
        "sample_transitions": sample_rows,
        "eroded_rates": eroded_rates,
        "j1_j2": pair_j1j2,
        "all_pairs": {"j1_j2": pair_j1j2, "j1_j3": pair_j1j3, "j2_j3": pair_j2j3},
        "strata": strata,
        "disagreement_examples": examples,
        "n_disagreements_j1j2": len(disagree_idx),
        "d38": d38,
        "d33": d33,
        "d33_metrics": d33_metrics,
    }
    (root / "reports" / "pilot_alpha_diagnostics.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )

    write_diagnostics_md(root / "reports" / "pilot_alpha_diagnostics.md", payload, roles)
    write_phase4d_md(root / "reports" / "PHASE_4D.md", payload, roles, root)
    print(
        json.dumps(
            {
                "n_llm": len(llm_items),
                "pairing_violations": pairing["n_violations"],
                "j1_j2_alpha": pair_j1j2["binary_alpha"],
                "j1_j2_kappa": pair_j1j2["cohen_kappa"],
                "j1_j2_pabak": pair_j1j2["pabak"],
                "eroded_rates": eroded_rates,
                "n_disagree": len(disagree_idx),
            },
            indent=2,
        )
    )


def _pair_table_md(stats: dict[str, Any], name1: str, name2: str) -> list[str]:
    t = stats["table"]
    lines = [
        f"| | {name2}=ERODED | {name2}=NOT_ERODED |",
        "|---|---|---|",
        f"| {name1}=ERODED | {t[BINARY_ERODED][BINARY_ERODED]} | {t[BINARY_ERODED][BINARY_NOT_ERODED]} |",
        f"| {name1}=NOT_ERODED | {t[BINARY_NOT_ERODED][BINARY_ERODED]} | {t[BINARY_NOT_ERODED][BINARY_NOT_ERODED]} |",
        "",
        f"- n = {stats['n']}",
        f"- raw % agreement = {_fmt(stats['pct_agreement'])}",
        f"- Cohen's κ = {_fmt(stats['cohen_kappa'])}",
        f"- PABAK = {_fmt(stats['pabak'])}",
        f"- binary α = {_fmt(stats['binary_alpha'])}",
        "",
    ]
    return lines


def write_diagnostics_md(path: Path, payload: dict, roles: dict[str, str]) -> None:
    lines: list[str] = []
    lines.append("# Pilot α diagnostics (Phase 4D Session 2)\n")
    lines.append(
        "CPU-only diagnosis of the pilot coding binary-α gate failure "
        f"(J1=`{roles['j1']}`, J2=`{roles['j2']}`, J3=`{roles['j3']}`). "
        "No judges, rules, or thresholds changed.\n"
    )

    p = payload["pairing"]
    lines.append("## 1. Pairing integrity\n")
    lines.append(
        f"Checked **{p['n_checked']}** LLM-coded pilot transitions against lineage. "
        f"**Violations: {p['n_violations']}**.\n"
    )
    if p["violations_by_type"]:
        lines.append("| violation type | count |")
        lines.append("|---|---|")
        for k, v in sorted(p["violations_by_type"].items()):
            lines.append(f"| {k} | {v} |")
        lines.append("")
    else:
        lines.append("No pairing violations detected.\n")

    lines.append("### 20 random transitions\n")
    for i, row in enumerate(payload["sample_transitions"], 1):
        lines.append(
            f"**{i}.** `item_id={row['item_id']}` · kind=`{row['kind']}` · "
            f"decision=`{row['decision']}` · {row['protocol']}/{row['condition']}"
        )
        lines.append(f"- ORIGINAL: {row['original']}")
        lines.append(f"- REVISED: {row['revised']}")
        lines.append(f"- merge line: {row['merge_line'] or '(none)'}")
        lines.append(f"- transition type: {row['kind']}")
        lines.append("")

    lines.append("## 2. Prevalence\n")
    lines.append("| judge | role | ERODED rate |")
    lines.append("|---|---|---|")
    for role, jid in roles.items():
        lines.append(f"| {jid} | {role} | {_fmt(payload['eroded_rates'][jid])} |")
    lines.append("")
    lines.append("### J1 × J2 2×2\n")
    lines.extend(_pair_table_md(payload["j1_j2"], "J1", "J2"))

    lines.append("## 3. All judge pairs\n")
    for key, title in (
        ("j1_j2", "J1–J2"),
        ("j1_j3", "J1–J3"),
        ("j2_j3", "J2–J3"),
    ):
        lines.append(f"### {title}\n")
        lines.extend(_pair_table_md(payload["all_pairs"][key], title.split("–")[0], title.split("–")[1]))

    lines.append("## 4. Strata (J1–J2)\n")
    for group, block in payload["strata"].items():
        lines.append(f"### By {group}\n")
        lines.append(
            "| stratum | n | % agree | κ | PABAK | binary α | ERODED₁ | ERODED₂ |"
        )
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
        f"## 5. Examples — 30 random J1–J2 disagreements "
        f"(of {payload['n_disagreements_j1j2']})\n"
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
            f"- labels: J1={ex['j1_fate']} ({ex['j1_binary']}), "
            f"J2={ex['j2_fate']} ({ex['j2_binary']}), "
            f"J3={ex['j3_fate']} ({ex['j3_binary']})"
        )
        lines.append(f"- J1 rationale: {ex['j1_rationale']}")
        lines.append(f"- J2 rationale: {ex['j2_rationale']}")
        lines.append(f"- J3 rationale: {ex['j3_rationale']}")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_phase4d_md(path: Path, payload: dict, roles: dict[str, str], root: Path) -> None:
    status = {}
    sp = root / "runs" / "phase4_coding" / "STATUS.json"
    if sp.exists():
        status = json.loads(sp.read_text())
    summary = json.loads(
        (root / "runs" / "phase4_coding" / "pilot_coding_summary.json").read_text()
    )
    d38 = payload["d38"]
    d33 = payload["d33"]
    lines: list[str] = []
    lines.append("# Phase 4D — Fixed calibration (v2), D38 selection, pilot α failure\n")
    lines.append(
        f"**Status:** STOPPED at pilot coding "
        f"(binary α={_fmt(summary.get('j1_j2_alpha'))} < 0.70). "
        "Power / G4 not run. CPU diagnostics in `reports/pilot_alpha_diagnostics.md`.\n"
    )

    lines.append("## D39 — Voided v1 calibration\n")
    lines.append(
        "`load_calibration_items()` copied `second → other` for every kept calib item, "
        "so `{MERGE_LINE}` rendered on non-merge fates. Judges were told non-merges were "
        "merges. `judge_calib_v1` and the D38 selection from it are **void** "
        "(labelled `invalid_merge_line_bug`). D38 remains the selection rule. "
        "Re-calibration = `judge_calib_v2` with merge line only for "
        "`intended_key ∈ {MERGED_INTACT, MERGED_LOST}`.\n"
    )

    lines.append("## Calibration v2 metrics (all 4 judges)\n")
    lines.append(
        "| judge | D33 macro-F1 | D33 κ | D33 hard | D33 eligible | "
        "D38 F1(ERODED) | D38 P/R | D38 κ | D38 hard | D38 eligible |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for jid in JUDGES:
        m33 = d33["metrics"][jid]
        e33 = d33["eligibility"][jid]
        m38 = d38["metrics"][jid]
        e38 = d38["eligibility"][jid]
        lines.append(
            f"| {jid} | {_fmt(m33['macro_f1'], 3)} | {_fmt(m33['weighted_kappa'], 3)} | "
            f"{_fmt(m33['hard_accuracy'], 3)} | {'yes' if e33['eligible'] else 'no'} | "
            f"{_fmt(m38['f1_eroded'], 3)} | "
            f"{_fmt(m38['precision_eroded'], 3)}/{_fmt(m38['recall_eroded'], 3)} | "
            f"{_fmt(m38['cohen_kappa'], 3)} | {_fmt(m38['hard_accuracy'], 3)} | "
            f"{'yes' if e38['eligible'] else 'no'} |"
        )
    lines.append("")
    lines.append("### D33 reasons\n")
    for jid in JUDGES:
        r = d33["eligibility"][jid]["reasons"] or ["(eligible)"]
        lines.append(f"- `{jid}`: {'; '.join(r)}")
    lines.append("\n### D38 reasons\n")
    for jid in JUDGES:
        r = d38["eligibility"][jid]["reasons"] or ["(eligible)"]
        lines.append(f"- `{jid}`: {'; '.join(r)}")
    lines.append("")

    lines.append("## D38 selection (from v2)\n")
    if d38.get("stopped"):
        lines.append(f"**STOPPED:** {d38.get('stop_reason')}\n")
    else:
        lines.append(
            f"- J1 = `{d38['j1']}`, J2 = `{d38['j2']}`, J3 = `{d38.get('j3')}` "
            f"(tiebreaker_ineligible={d38.get('tiebreaker_ineligible')})"
        )
        lines.append(f"- J1–J2 binary Krippendorff α (calib) = {_fmt(d38.get('j1_j2_alpha'))}")
        lines.append(
            f"- D33 reference: stopped={d33.get('stopped')}, "
            f"reason={d33.get('stop_reason')}\n"
        )

    lines.append("## Pilot coding result\n")
    lines.append(
        f"- Judges: J1=`{summary.get('j1')}`, J2=`{summary.get('j2')}`, "
        f"J3=`{summary.get('j3')}`"
    )
    lines.append(f"- n_transitions={summary.get('n_transitions')}, n_llm={summary.get('n_llm')}")
    lines.append(
        f"- binary J1–J2 α = **{_fmt(summary.get('j1_j2_alpha'))}** "
        f"(gate ≥ 0.70) → **FAIL**"
    )
    lines.append(
        f"- ordinal J1–J2 α (disclosure) = {_fmt(summary.get('j1_j2_alpha_ordinal'))}"
    )
    lines.append(f"- unresolved rate = {_fmt(summary.get('unresolved_rate'))}")
    lines.append(f"- STATUS spend_usd ≈ {_fmt(status.get('spend_usd'), 2)}")
    lines.append("")

    lines.append("## Pilot α diagnostics (summary)\n")
    lines.append(
        f"- Pairing violations: **{payload['pairing']['n_violations']}** / "
        f"{payload['pairing']['n_checked']}"
    )
    er = payload["eroded_rates"]
    lines.append(
        f"- ERODED rates: J1={_fmt(er[roles['j1']])}, "
        f"J2={_fmt(er[roles['j2']])}, J3={_fmt(er[roles['j3']])}"
    )
    st = payload["j1_j2"]
    lines.append(
        f"- J1–J2: %agree={_fmt(st['pct_agreement'])}, κ={_fmt(st['cohen_kappa'])}, "
        f"PABAK={_fmt(st['pabak'])}, binary α={_fmt(st['binary_alpha'])}"
    )
    lines.append(
        f"- J1–J3 binary α={_fmt(payload['all_pairs']['j1_j3']['binary_alpha'])}, "
        f"J2–J3 binary α={_fmt(payload['all_pairs']['j2_j3']['binary_alpha'])}"
    )
    lines.append(
        f"- J1–J2 disagreements: {payload['n_disagreements_j1j2']} / {st['n']}"
    )
    lines.append("")
    lines.append("### Strata snapshot (J1–J2 binary α)\n")
    lines.append("| stratum | binary α | % agree | κ |")
    lines.append("|---|---|---|---|")
    for group, block in payload["strata"].items():
        for name, s in block.items():
            lines.append(
                f"| {group}={name} | {_fmt(s['binary_alpha'])} | "
                f"{_fmt(s['pct_agreement'])} | {_fmt(s['cohen_kappa'])} |"
            )
    lines.append("")
    lines.append(
        "Full pairing samples, 2×2 tables, and 30 verbatim disagreements: "
        "`reports/pilot_alpha_diagnostics.md`.\n"
    )
    lines.append("## Eval-awareness / power / G4\n")
    lines.append(
        "Blocked by the pilot α gate. Eval-awareness judgments were collected during "
        "coding (`runs/phase4_coding/coding/eval_awareness.jsonl`) but power and G4 "
        "were not run.\n"
    )
    lines.append("## Cumulative spend\n")
    lines.append(
        f"STATUS reports spend_usd ≈ **{_fmt(status.get('spend_usd'), 2)}** "
        "against the Phase 4 cumulative cap of **$27**.\n"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
