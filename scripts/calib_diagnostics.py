#!/usr/bin/env python3
"""Phase 4C: enrich judge calib records, diagnostics, D33 vs D38 (CPU only)."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rc.config import load_experiment, repo_root
from rc.judge_metrics import (
    accuracy,
    confusion_matrix,
    metrics_for_judge,
    per_class_prf,
    select_judges_d33,
    select_judges_d38,
)
from rc.judging import (
    FATE_PRECEDENCE,
    JUDGE_FATES,
    load_calibration_items,
    normalize_fate,
    shuffle_items,
)
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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def item_key(item: dict[str, Any]) -> str:
    if item.get("hard_id"):
        return str(item["hard_id"])
    return (
        f"{item.get('item_id')}|{item.get('form')}|"
        f"{item.get('intended_key') or item.get('intended_fate')}|{item.get('generator_rep')}"
    )


def enrich_records(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Join stored judgments with materials; write enriched jsonl under judge_calib_v1."""
    dest = root / "runs" / "judge_calib_v1"
    dest.mkdir(parents=True, exist_ok=True)
    base_items = load_calibration_items(root)
    master = load_experiment(root).master_seed
    per: dict[str, list[dict[str, Any]]] = {}

    for jid in JUDGES:
        raw_path = dest / f"{jid}.jsonl"
        # Prefer unenriched Modal dump if present as *.raw.jsonl; else current file.
        raw_backup = dest / f"{jid}.raw.jsonl"
        if raw_backup.exists():
            stored = _load_jsonl(raw_backup)
        else:
            stored = _load_jsonl(raw_path)
            if stored and "item_key" not in stored[0]:
                _write_jsonl(raw_backup, stored)
        if not stored:
            raise SystemExit(f"missing calibration rows for {jid} at {raw_path}")

        shuffled = shuffle_items(base_items, jid, master)
        if len(shuffled) != len(stored):
            raise SystemExit(
                f"{jid}: materials n={len(shuffled)} != stored n={len(stored)}"
            )

        enriched: list[dict[str, Any]] = []
        for row, item in zip(stored, shuffled, strict=True):
            if row.get("item_id") != item.get("item_id") or normalize_fate(
                row.get("intended_fate")
            ) != normalize_fate(item.get("intended_fate")):
                raise SystemExit(f"{jid}: shuffle join mismatch at index {row.get('item_index')}")
            source = item.get("source") or row.get("source") or "calib"
            if source == "calib":
                source = "generator"
            elif source not in ("generator", "lead"):
                source = "lead" if item.get("hard_id") or row.get("hard_id") else "generator"

            parsed_fate = normalize_fate(row.get("fate"))
            enriched.append(
                {
                    "item_key": item_key(item),
                    "item_id": item.get("item_id"),
                    "hard_id": item.get("hard_id") or row.get("hard_id"),
                    "form": item.get("form"),
                    "generator_rep": item.get("generator_rep"),
                    "intended_key": item.get("intended_key"),
                    "intended_fate": normalize_fate(item.get("intended_fate")),
                    "category": item.get("category") or row.get("category"),
                    "source": source,
                    "original": item.get("original"),
                    "rewrite": item.get("rewrite"),
                    "other": item.get("other") or item.get("second"),
                    "judge_id": jid,
                    "item_index": row.get("item_index"),
                    "raw_text": row.get("raw_text") or row.get("raw"),  # not persisted at calib
                    "parsed_fate": parsed_fate,
                    "fate": parsed_fate,
                    "strength": row.get("strength"),
                    "rationale": row.get("rationale"),
                    "finish_reason": row.get("finish_reason"),  # not persisted at calib
                    "n_output_tokens": row.get("n_output_tokens"),
                    "n_reasoning_tokens": row.get("n_reasoning_tokens"),
                    "text_reasoning": row.get("text_reasoning"),
                    "parse_status": row.get("parse_status"),
                    "structural": bool(row.get("structural")),
                    "latency_s": row.get("latency_s"),
                }
            )
        _write_jsonl(dest / f"{jid}.jsonl", enriched)
        per[jid] = enriched
    return per


def harness_checks(rows: list[dict[str, Any]], judge_id: str) -> dict[str, Any]:
    parse_fail = sum(1 for r in rows if r.get("parse_status") != "ok")
    length = sum(1 for r in rows if r.get("finish_reason") == "length")
    finish_missing = sum(1 for r in rows if r.get("finish_reason") is None)
    raw_missing = sum(1 for r in rows if not r.get("raw_text"))
    invalid = sum(
        1
        for r in rows
        if r.get("parse_status") == "ok"
        and (
            not r.get("parsed_fate")
            or normalize_fate(r.get("parsed_fate")) not in JUDGE_FATES
        )
    )
    defects: list[str] = []
    if finish_missing == len(rows):
        defects.append(
            "finish_reason was not persisted by judge_fate_batch; length truncations "
            "cannot be audited from stored outputs."
        )
    if raw_missing == len(rows):
        defects.append(
            "raw model text was not persisted; only parsed fate/strength/rationale are available."
        )
    out: dict[str, Any] = {
        "n": len(rows),
        "parse_failures": parse_fail,
        "finish_reason_length": length,
        "finish_reason_missing": finish_missing,
        "raw_text_missing": raw_missing,
        "empty_or_invalid_label": invalid,
        "harness_defects": defects,
    }
    if judge_id.startswith("gptoss"):
        reason_toks = [r.get("n_reasoning_tokens") for r in rows]
        reason_missing = sum(1 for v in reason_toks if v is None)
        text_reason_missing = sum(1 for r in rows if r.get("text_reasoning") is None)
        out["reasoning_tokens_missing"] = reason_missing
        out["text_reasoning_missing"] = text_reason_missing
        present = [int(v) for v in reason_toks if v is not None]
        if present:
            out["reasoning_token_distribution"] = {
                "n": len(present),
                "min": min(present),
                "max": max(present),
                "mean": statistics.mean(present),
                "median": statistics.median(present),
            }
            out["final_after_reasoning"] = "unknown_not_persisted"
        else:
            out["reasoning_token_distribution"] = None
            out["final_after_reasoning"] = "unknown_not_persisted"
            defects.append(
                "gpt-oss reasoning tokens / text_reasoning were not persisted; "
                "cannot verify that the final answer followed reasoning."
            )
    return out


def accuracy_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        r
        for r in rows
        if r.get("parse_status") == "ok"
        and normalize_fate(r.get("intended_fate")) in JUDGE_FATES
        and normalize_fate(r.get("parsed_fate") or r.get("fate")) in JUDGE_FATES
    ]
    y_true = [normalize_fate(r["intended_fate"]) or "" for r in scored]
    y_pred = [normalize_fate(r.get("parsed_fate") or r.get("fate")) or "" for r in scored]
    labels = list(FATE_PRECEDENCE)
    prf = per_class_prf(y_true, y_pred, labels)
    hard = [r for r in scored if r.get("source") == "lead" or r.get("hard_id")]
    hard_acc = (
        accuracy(
            [normalize_fate(r["intended_fate"]) or "" for r in hard],
            [normalize_fate(r.get("parsed_fate") or r.get("fate")) or "" for r in hard],
        )
        if hard
        else float("nan")
    )
    by_rep: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r, t, p in zip(scored, y_true, y_pred, strict=True):
        rep = r.get("generator_rep")
        key = "lead" if r.get("source") == "lead" or r.get("hard_id") else str(rep)
        by_rep[key].append((t, p))
    acc_by_rep = {
        k: accuracy([a for a, _ in pairs], [b for _, b in pairs]) for k, pairs in sorted(by_rep.items())
    }
    return {
        "n": len(scored),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels),
        "per_class": prf,
        "hard_accuracy": hard_acc,
        "n_hard": len(hard),
        "accuracy_by_generator_rep": acc_by_rep,
        "overall_metrics": metrics_for_judge(scored),
    }


def consensus_disagreement(per: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_key: dict[str, dict[str, Any]] = {}
    for jid, rows in per.items():
        for r in rows:
            key = r["item_key"]
            slot = by_key.setdefault(
                key,
                {
                    "intended_fate": r.get("intended_fate"),
                    "category": r.get("category"),
                    "labels": {},
                },
            )
            slot["labels"][jid] = normalize_fate(r.get("parsed_fate") or r.get("fate"))

    n = 0
    disagree = 0
    by_fate: Counter[str] = Counter()
    by_fate_dis: Counter[str] = Counter()
    by_cat: Counter[str] = Counter()
    by_cat_dis: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for key, slot in by_key.items():
        labs = [v for v in slot["labels"].values() if v]
        if len(labs) < 3:
            continue
        n += 1
        intended = normalize_fate(slot["intended_fate"]) or ""
        cat = slot.get("category") or "?"
        by_fate[intended] += 1
        by_cat[cat] += 1
        counts = Counter(labs)
        top_lab, top_n = counts.most_common(1)[0]
        if top_n >= 3 and top_lab != intended:
            disagree += 1
            by_fate_dis[intended] += 1
            by_cat_dis[cat] += 1
            if len(examples) < 30:
                examples.append(
                    {
                        "item_key": key,
                        "intended_fate": intended,
                        "category": cat,
                        "consensus_label": top_lab,
                        "n_agree": top_n,
                        "labels": slot["labels"],
                    }
                )

    def rate_map(num: Counter[str], den: Counter[str]) -> dict[str, float]:
        return {k: (num[k] / den[k] if den[k] else float("nan")) for k in sorted(den)}

    return {
        "n_items": n,
        "n_consensus_disagree": disagree,
        "rate": disagree / n if n else float("nan"),
        "rate_by_intended_fate": rate_map(by_fate_dis, by_fate),
        "rate_by_category": rate_map(by_cat_dis, by_cat),
        "examples": examples,
    }


def confusion_examples(per: dict[str, list[dict[str, Any]]], top_k: int = 3, n_ex: int = 10) -> list[dict]:
    # Pool off-diagonal pairs.
    pair_counts: Counter[tuple[str, str]] = Counter()
    # index items
    by_key: dict[str, dict[str, Any]] = {}
    for jid, rows in per.items():
        for r in rows:
            key = r["item_key"]
            slot = by_key.setdefault(
                key,
                {
                    "original": r.get("original"),
                    "rewrite": r.get("rewrite"),
                    "intended_fate": r.get("intended_fate"),
                    "category": r.get("category"),
                    "labels": {},
                },
            )
            pred = normalize_fate(r.get("parsed_fate") or r.get("fate"))
            intended = normalize_fate(r.get("intended_fate"))
            slot["labels"][jid] = pred
            if intended and pred and intended != pred:
                pair_counts[(intended, pred)] += 1

    top_pairs = [p for p, _ in pair_counts.most_common(top_k)]
    out = []
    for intended, predicted in top_pairs:
        examples = []
        for key, slot in by_key.items():
            if normalize_fate(slot["intended_fate"]) != intended:
                continue
            # at least one judge predicted the confused label
            if predicted not in slot["labels"].values():
                continue
            examples.append(
                {
                    "item_key": key,
                    "original": slot["original"],
                    "rewrite": slot["rewrite"],
                    "intended_fate": intended,
                    "category": slot["category"],
                    "judge_labels": slot["labels"],
                }
            )
            if len(examples) >= n_ex:
                break
        out.append(
            {
                "pair": {"intended": intended, "predicted": predicted},
                "pooled_count": pair_counts[(intended, predicted)],
                "examples": examples,
            }
        )
    return out


def _fmt(x: Any, digits: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        if math.isnan(x):
            return "nan"
        return f"{x:.{digits}f}"
    return str(x)


def write_diagnostics_md(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Judge calibration diagnostics (Phase 4C)\n")
    lines.append("CPU-only reanalysis of stored raw judge outputs. No regeneration.\n")

    lines.append("## Harness findings\n")
    for jid in JUDGES:
        h = payload["harness"][jid]
        lines.append(f"### `{jid}`\n")
        lines.append(f"- n = {h['n']}")
        lines.append(f"- parse failures = {h['parse_failures']}")
        lines.append(f"- `finish_reason == length` = {h['finish_reason_length']}")
        lines.append(f"- empty/invalid labels = {h['empty_or_invalid_label']}")
        lines.append(f"- `finish_reason` missing = {h['finish_reason_missing']}")
        lines.append(f"- `raw_text` missing = {h['raw_text_missing']}")
        if jid.startswith("gptoss"):
            lines.append(
                f"- reasoning-token distribution = {h.get('reasoning_token_distribution')}"
            )
            lines.append(
                f"- final answer after reasoning = {h.get('final_after_reasoning')}"
            )
        if h["harness_defects"]:
            lines.append("- **Harness defects:**")
            for d in h["harness_defects"]:
                lines.append(f"  - {d}")
        else:
            lines.append("- Harness defects: none detected in stored fields.")
        lines.append("")

    lines.append("## Per-judge accuracy breakdown\n")
    for jid in JUDGES:
        b = payload["breakdown"][jid]
        lines.append(f"### `{jid}`\n")
        lines.append(
            f"Hard-item accuracy (n={b['n_hard']}): **{_fmt(b['hard_accuracy'])}**\n"
        )
        lines.append("Accuracy by `generator_rep`:\n")
        lines.append("| generator_rep | accuracy |")
        lines.append("|---|---|")
        for k, v in b["accuracy_by_generator_rep"].items():
            lines.append(f"| {k} | {_fmt(v)} |")
        lines.append("")
        lines.append("Per-class precision / recall / F1:\n")
        lines.append("| fate | precision | recall | F1 | support |")
        lines.append("|---|---|---|---|---|")
        for lab in FATE_PRECEDENCE:
            pr = b["per_class"][lab]
            lines.append(
                f"| {lab} | {_fmt(pr['precision'])} | {_fmt(pr['recall'])} | "
                f"{_fmt(pr['f1'])} | {int(pr['support'])} |"
            )
        lines.append("")
        lines.append("<details><summary>7×7 confusion matrix</summary>\n")
        labels = list(FATE_PRECEDENCE)
        header = "| true \\ pred | " + " | ".join(labels) + " |"
        sep = "|---|" + "---|" * len(labels)
        lines.append(header)
        lines.append(sep)
        cm = b["confusion_matrix"]
        for t in labels:
            cells = " | ".join(str(cm[t][p]) for p in labels)
            lines.append(f"| {t} | {cells} |")
        lines.append("\n</details>\n")

    cons = payload["consensus"]
    lines.append("## Consensus disagreement (ground-truth validity)\n")
    lines.append(
        f"Items where ≥3/4 judges agree on a label **different** from intended: "
        f"**{cons['n_consensus_disagree']} / {cons['n_items']}** "
        f"(rate = {_fmt(cons['rate'], 4)}).\n"
    )
    lines.append("### By intended fate\n")
    lines.append("| intended fate | rate |")
    lines.append("|---|---|")
    for k, v in cons["rate_by_intended_fate"].items():
        lines.append(f"| {k} | {_fmt(v, 4)} |")
    lines.append("\n### By category\n")
    lines.append("| category | rate |")
    lines.append("|---|---|")
    for k, v in cons["rate_by_category"].items():
        lines.append(f"| {k} | {_fmt(v, 4)} |")
    lines.append("")

    lines.append("## Confusion examples (top 3 pooled pairs)\n")
    for block in payload["confusion_examples"]:
        pair = block["pair"]
        lines.append(
            f"### {pair['intended']} → {pair['predicted']} "
            f"(pooled count = {block['pooled_count']})\n"
        )
        for i, ex in enumerate(block["examples"], 1):
            labs = ", ".join(f"{j}={lab}" for j, lab in sorted(ex["judge_labels"].items()))
            lines.append(f"**Example {i}** (`{ex['item_key']}`, {ex.get('category')})")
            lines.append(f"- original: {ex['original']}")
            lines.append(f"- rewrite: {ex['rewrite']}")
            lines.append(f"- intended: {ex['intended_fate']}")
            lines.append(f"- judges: {labs}")
            lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_phase4c_md(path: Path, payload: dict[str, Any]) -> None:
    d33 = payload["d33"]
    d38 = payload["d38"]
    lines: list[str] = []
    lines.append("# Phase 4C — Judge calibration diagnostics and D38\n")
    lines.append(
        "**Status:** calibration diagnostics complete (CPU only). "
        "Pilot coding / power / G4 **not** launched.\n"
    )
    lines.append("## Harness findings\n")
    any_defect = False
    for jid in JUDGES:
        h = payload["harness"][jid]
        lines.append(f"- `{jid}`: parse_fail={h['parse_failures']}, "
                     f"length={h['finish_reason_length']}, "
                     f"invalid_label={h['empty_or_invalid_label']}")
        for d in h["harness_defects"]:
            any_defect = True
            lines.append(f"  - DEFECT: {d}")
    if not any_defect:
        lines.append("- No harness defects beyond field persistence gaps listed above.")
    lines.append("")

    lines.append("## Diagnostics summary\n")
    lines.append("| judge | 7-way acc | macro-F1 | hard acc | consensus-disagree rate (shared) |")
    lines.append("|---|---|---|---|---|")
    cons_rate = payload["consensus"]["rate"]
    for jid in JUDGES:
        m = payload["breakdown"][jid]["overall_metrics"]
        lines.append(
            f"| {jid} | {_fmt(m['accuracy'])} | {_fmt(m['macro_f1'])} | "
            f"{_fmt(m['hard_accuracy'])} | {_fmt(cons_rate, 4)} |"
        )
    lines.append("")
    lines.append(
        f"Consensus-disagree (≥3 judges agree ≠ intended): "
        f"{payload['consensus']['n_consensus_disagree']}/"
        f"{payload['consensus']['n_items']} ({_fmt(cons_rate, 4)}). "
        f"Highest by fate: see `reports/calib_diagnostics.md`.\n"
    )

    lines.append("## D33 vs D38 metrics\n")
    lines.append(
        "| judge | D33 macro-F1 | D33 κ | D33 hard | D33 \|COR−AGENT\| | "
        "D33 eligible | D38 F1(ERODED) | D38 P/R(ERODED) | D38 κ | "
        "D38 hard | D38 \|COR−AGENT\| | D38 eligible |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for jid in JUDGES:
        m33 = d33["metrics"][jid]
        e33 = d33["eligibility"][jid]
        m38 = d38["metrics"][jid]
        e38 = d38["eligibility"][jid]
        lines.append(
            f"| {jid} | {_fmt(m33['macro_f1'])} | {_fmt(m33['weighted_kappa'])} | "
            f"{_fmt(m33['hard_accuracy'])} | {_fmt(abs(m33['cor_minus_agent_accuracy']))} | "
            f"{'yes' if e33['eligible'] else 'no'} | "
            f"{_fmt(m38['f1_eroded'])} | "
            f"{_fmt(m38['precision_eroded'])}/{_fmt(m38['recall_eroded'])} | "
            f"{_fmt(m38['cohen_kappa'])} | {_fmt(m38['hard_accuracy'])} | "
            f"{_fmt(abs(m38['cor_minus_agent_accuracy']))} | "
            f"{'yes' if e38['eligible'] else 'no'} |"
        )
    lines.append("")
    lines.append("### D33 ineligibility reasons\n")
    for jid in JUDGES:
        reasons = d33["eligibility"][jid]["reasons"] or ["(eligible)"]
        lines.append(f"- `{jid}`: {'; '.join(reasons)}")
    lines.append("\n### D38 ineligibility reasons\n")
    for jid in JUDGES:
        reasons = d38["eligibility"][jid]["reasons"] or ["(eligible)"]
        lines.append(f"- `{jid}`: {'; '.join(reasons)}")
    lines.append("")

    lines.append("### Sensitivity (QUALIFIED_LEGITIMACY as ERODED)\n")
    lines.append("| judge | F1(ERODED) | P(ERODED) | R(ERODED) | κ | hard |")
    lines.append("|---|---|---|---|---|---|")
    for jid in JUDGES:
        s = d38["sensitivity_qualified_as_eroded"][jid]
        lines.append(
            f"| {jid} | {_fmt(s['f1_eroded'])} | {_fmt(s['precision_eroded'])} | "
            f"{_fmt(s['recall_eroded'])} | {_fmt(s['cohen_kappa'])} | "
            f"{_fmt(s['hard_accuracy'])} |"
        )
    lines.append("")

    lines.append("## D38 selection result\n")
    if d38.get("stopped"):
        lines.append(
            f"**STOPPED under D38:** {d38.get('stop_reason')}. "
            "Thresholds were not relaxed. Pilot coding / power / G4 remain blocked.\n"
        )
    else:
        lines.append(
            f"- J1 = `{d38['j1']}`, J2 = `{d38['j2']}`, J3 = `{d38.get('j3')}` "
            f"(tiebreaker_ineligible={d38.get('tiebreaker_ineligible')})"
        )
        lines.append(f"- J1–J2 binary Krippendorff α = {_fmt(d38.get('j1_j2_alpha'), 4)}")
        lines.append("")
    lines.append(
        "D33 selection (for reference): "
        f"stopped={d33.get('stopped')}, reason={d33.get('stop_reason')}.\n"
    )
    lines.append("Full diagnostics: `reports/calib_diagnostics.md`. D38 logged in `docs/DECISIONS.md`.\n")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    root = repo_root()
    per = enrich_records(root)
    harness = {jid: harness_checks(rows, jid) for jid, rows in per.items()}
    breakdown = {jid: accuracy_breakdown(rows) for jid, rows in per.items()}
    consensus = consensus_disagreement(per)
    examples = confusion_examples(per)

    # D38 rule already logged DECIDED; now compute metrics.
    d33 = select_judges_d33(per)
    d38 = select_judges_d38(per)

    dest = root / "runs" / "judge_calib_v1"
    metrics_payload = {
        "d33": d33,
        "d38": d38,
        "consensus": {
            "n_items": consensus["n_items"],
            "n_consensus_disagree": consensus["n_consensus_disagree"],
            "rate": consensus["rate"],
            "rate_by_intended_fate": consensus["rate_by_intended_fate"],
            "rate_by_category": consensus["rate_by_category"],
        },
        "harness": harness,
    }
    (dest / "calibration_metrics.json").write_text(
        json.dumps(metrics_payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (dest / "selection_d33.json").write_text(
        json.dumps(d33, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (dest / "selection_d38.json").write_text(
        json.dumps(d38, indent=2, default=str) + "\n", encoding="utf-8"
    )

    payload = {
        "harness": harness,
        "breakdown": breakdown,
        "consensus": consensus,
        "confusion_examples": examples,
        "d33": d33,
        "d38": d38,
    }
    (root / "reports" / "phase4c_payload.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    write_diagnostics_md(root / "reports" / "calib_diagnostics.md", payload)
    write_phase4c_md(root / "reports" / "PHASE_4C.md", payload)
    print(
        json.dumps(
            {
                "n_judges": len(per),
                "d33_stopped": d33.get("stopped"),
                "d38_stopped": d38.get("stopped"),
                "d38_j1": d38.get("j1"),
                "d38_j2": d38.get("j2"),
                "d38_j3": d38.get("j3"),
                "consensus_rate": consensus["rate"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
