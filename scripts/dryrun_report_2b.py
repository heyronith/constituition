#!/usr/bin/env python3
"""Build reports/PHASE_2B.md from phase2b_dryrun + phase2b_realism_audit."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rc.config import load_models, repo_root
from rc.generation import expects_reasoning
from rc.materials import CATEGORIES

RUN_TAG = "phase2b_dryrun"
REALISM_TAG = "phase2b_realism_audit"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def collect_rounds(config_id: str, root: Path) -> list[dict]:
    base = root / "runs" / RUN_TAG / config_id
    rows: list[dict] = []
    if not base.exists():
        return rows
    for path in base.rglob("rounds.jsonl"):
        for row in _load_jsonl(path):
            parts = path.relative_to(base).parts
            row["_path"] = str(path.relative_to(base))
            row["_protocol"] = parts[0] if parts else None
            row["_condition"] = parts[1] if len(parts) > 1 else None
            rows.append(row)
    return rows


def decision_dist(config_id: str, root: Path) -> dict[str, Counter]:
    """Keyed by protocol|condition."""
    out: dict[str, Counter] = defaultdict(Counter)
    base = root / "runs" / RUN_TAG / config_id
    if not base.exists():
        return out
    for path in base.rglob("lineage.jsonl"):
        parts = path.relative_to(base).parts
        if len(parts) < 2:
            continue
        key = f"{parts[0]}|{parts[1]}"
        for row in _load_jsonl(path):
            if row.get("round", 0) == 0:
                continue
            dec = row.get("decision")
            if dec:
                out[key][dec] += 1
    return out


def forced_selections(config_id: str, root: Path) -> dict[str, Counter]:
    """Per-condition category and action counts under FORCED."""
    cats: dict[str, Counter] = defaultdict(Counter)
    actions: dict[str, Counter] = defaultdict(Counter)
    base = root / "runs" / RUN_TAG / config_id / "FORCED"
    if not base.exists():
        return {"categories": cats, "actions": actions}  # type: ignore[return-value]
    for path in base.rglob("lineage.jsonl"):
        parts = path.relative_to(base).parts
        condition = parts[0] if parts else "?"
        for row in _load_jsonl(path):
            if row.get("round", 0) == 0:
                continue
            dec = row.get("decision")
            if not dec or dec == "add":
                continue
            # Primary change: revise/delete on the kept id, or merge on source.
            if dec in ("revise", "delete", "merge") and row.get("after_text") is not None:
                cat = row.get("category") or "UNKNOWN"
                cats[condition][cat] += 1
                actions[condition][dec] += 1
            elif dec == "delete":
                cats[condition][row.get("category") or "UNKNOWN"] += 1
                actions[condition]["delete"] += 1
            elif dec == "merge" and row.get("after_text") is None:
                # merge-away record; skip double-count
                continue
    return {"categories": cats, "actions": actions}  # type: ignore[return-value]


def realism_means(config_id: str, root: Path) -> dict[str, float]:
    path = root / "runs" / REALISM_TAG / config_id / "calls.jsonl"
    by_cat: dict[str, list[float]] = defaultdict(list)
    for row in _load_jsonl(path):
        if row.get("rating") is not None:
            by_cat[row["category"]].append(float(row["rating"]))
    return {c: statistics.mean(v) for c, v in sorted(by_cat.items()) if v}


def forced_examples(config_id: str, root: Path) -> list[str]:
    lines: list[str] = []
    for cond in ("SELF_REFLECT", "NEUTRAL_EDIT"):
        path = (
            root
            / "runs"
            / RUN_TAG
            / config_id
            / "FORCED"
            / cond
            / "STRUCTURED"
            / "chain_0"
            / "rounds.jsonl"
        )
        rows = [r for r in _load_jsonl(path) if r.get("parse_status") == "ok"]
        if not rows:
            lines.append(f"### FORCED {cond}\n\n_missing_\n")
            continue
        row = rows[0]
        final = row.get("text_final") or ""
        if len(final) > 2000:
            final = final[:2000] + "\n…[truncated]"
        lines.append(
            f"### FORCED {cond} (round {row.get('round')})\n\n"
            f"```\n{final}\n```\n"
        )
    return lines


def job_timings(config_id: str, root: Path) -> dict:
    for name in ("phase2b_dryrun_summary.json", "phase2b_l4_smoke"):
        path = root / "runs" / name
        if name.endswith(".json") and path.exists():
            summary = json.loads(path.read_text())
            for job in summary.get("jobs", []):
                if job.get("config_id") == config_id:
                    return {
                        "load_s": job.get("model_load_s"),
                        "graph_capture_s": job.get("graph_capture_s"),
                    }
    return {}


def main() -> None:
    root = repo_root()
    models = load_models(root)
    subject_ids = [s.config_id for s in models.subjects]
    ledger = []
    ledger_path = root / "budget" / "ledger.jsonl"
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if line.strip():
                ledger.append(json.loads(line))

    modal_2b = [
        r
        for r in ledger
        if r.get("platform") == "modal"
        and str(r.get("phase")) in {"2", "2b", "phase2", "phase2b", "phase2_dryrun"}
    ]
    code_fail = [r for r in modal_2b if r.get("note") == "code_failure"]
    spend = sum(float(r.get("actual_usd") or r.get("est_usd") or 0) for r in modal_2b)
    code_fail_cost = sum(float(r.get("actual_usd") or 0) for r in code_fail)
    # Phase 2B incremental: jobs whose note/job_id mentions 2b or l4 smoke / phase2b
    modal_2b_only = [
        r
        for r in ledger
        if r.get("platform") == "modal"
        and (
            str(r.get("phase")) in {"2b", "phase2b"}
            or "phase2b" in str(r.get("job_id") or "")
            or "l4" in str(r.get("note") or "").lower()
        )
    ]
    spend_2b = sum(float(r.get("actual_usd") or r.get("est_usd") or 0) for r in modal_2b_only)
    code_fail_2b = sum(
        float(r.get("actual_usd") or 0)
        for r in modal_2b_only
        if r.get("note") == "code_failure"
    )

    parts: list[str] = [
        "# Phase 2B — Engineering fixes, materials v2, FORCED protocol, dry run v2\n\n",
        "Run tag `phase2b_dryrun` must never enter confirmatory analysis. "
        "Realism v2 is under `phase2b_realism_audit`. v1 audit data left unchanged.\n\n",
        f"Cumulative Phase 2/2B Modal ledger: **${spend:.4f}** / $11.00 "
        f"(Phase 2B incremental ≈ ${spend_2b:.4f}).\n\n",
        f"Code-failure cost (Phase 2B jobs): **${code_fail_2b:.4f}** "
        f"(all Phase 2/2B code failures in ledger: ${code_fail_cost:.4f}).\n\n",
        "D19–D23: see `docs/DECISIONS.md`.\n",
    ]

    smoke_marker = root / "runs" / "phase2b_l4_smoke" / "PASSED.json"
    parts.append("\n## L4 tiny-model smoke (D23)\n\n")
    if smoke_marker.exists():
        marker = json.loads(smoke_marker.read_text())
        parts.append(
            f"- PASSED: load_s={marker.get('load_s')} "
            f"graph_capture_s={marker.get('graph_capture_s')}\n"
        )
    else:
        parts.append("- **MISSING** — no A100-class job should have run.\n")

    for cid in subject_ids:
        rounds = collect_rounds(cid, root)
        parts.append(f"\n## {cid}\n")
        if not rounds:
            parts.append("_No phase2b_dryrun rounds found._\n")
            continue
        timings = job_timings(cid, root)
        lat = [float(r["latency_s"]) for r in rounds if r.get("latency_s") is not None]
        out_tok = [
            int(r["n_output_tokens"]) for r in rounds if r.get("n_output_tokens") is not None
        ]
        reason_tok = [int(r.get("n_reasoning_tokens") or 0) for r in rounds]
        first_ok = sum(1 for r in rounds if r.get("attempt") == 0 and r.get("parse_status") == "ok")
        first_n = sum(1 for r in rounds if r.get("attempt") == 0)
        by_key: dict[tuple, bool] = {}
        for r in rounds:
            key = (r.get("_path"), r.get("round"))
            by_key[key] = by_key.get(key, False) or r.get("parse_status") == "ok"
        final_rate = (sum(by_key.values()) / len(by_key)) if by_key else 0.0
        first_rate = (first_ok / first_n) if first_n else 0.0
        total_out = sum(out_tok)
        total_lat = sum(lat) if lat else 0.0
        tok_per_s = (total_out / total_lat) if total_lat > 0 else float("nan")

        parts.append(
            f"- load_s: {timings.get('load_s', 'n/a')}\n"
            f"- graph_capture_s: {timings.get('graph_capture_s', 'n/a')}\n"
            f"- aggregate output tok/s: **{tok_per_s:.2f}** "
            f"(Phase 2 was ~20 tok/s; batched should be several× higher)\n"
            f"- first-attempt parse rate: {first_rate:.3f}\n"
            f"- final parse rate: {final_rate:.3f}\n"
            f"- reasoning tokens mean/max: "
            f"{(statistics.mean(reason_tok) if reason_tok else 0):.1f} / "
            f"{(max(reason_tok) if reason_tok else 0)}\n"
        )

        if expects_reasoning(cid):
            ok = all((r.get("n_reasoning_tokens") or 0) > 0 for r in rounds)
            parts.append(f"- thinking toggle: {'PASS' if ok else 'FAIL'}\n")
        else:
            leaks = [r for r in rounds if (r.get("n_reasoning_tokens") or 0) > 0]
            parts.append(
                f"- thinking toggle (expect 0 reasoning): "
                f"{'PASS' if not leaks else f'LEAKS n={len(leaks)}'}\n"
            )

        ddist = decision_dist(cid, root)
        parts.append("- PERMISSIVE vs FORCED decision distributions (descriptive):\n")
        for key, counter in sorted(ddist.items()):
            parts.append(f"  - {key}: {dict(counter)}\n")

        sel = forced_selections(cid, root)
        parts.append("- FORCED selected categories / actions (descriptive):\n")
        for cond in ("SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"):
            parts.append(
                f"  - {cond}: cats={dict(sel['categories'].get(cond, {}))} "
                f"actions={dict(sel['actions'].get(cond, {}))}\n"
            )

        parts.append("\n### Raw FORCED examples\n\n")
        parts.extend(forced_examples(cid, root))

    # Realism v2
    parts.append("\n## Realism audit v2\n\n")
    parts.append(
        "**Primary (D22):** |mean(COR) − mean(AGENT)| ≤ 0.5 on every config.\n\n"
        "**Secondary:** every category's gap from the rest (report).\n\n"
    )
    for cid in subject_ids:
        means = realism_means(cid, root)
        if not means:
            parts.append(f"- {cid}: _missing_\n")
            continue
        parts.append(f"- {cid}: {means}\n")
        if "COR" in means and "AGENT" in means:
            primary = abs(means["COR"] - means["AGENT"])
            parts.append(
                f"  - primary |COR−AGENT|={primary:.3f} → "
                f"{'PASS' if primary <= 0.5 else 'FAIL'}\n"
            )
        else:
            parts.append("  - primary: missing COR or AGENT\n")
        cats = list(means)
        for cat in cats:
            others = [means[c] for c in cats if c != cat]
            gap = means[cat] - statistics.mean(others)
            parts.append(f"  - secondary {cat} gap vs rest: {gap:.3f}\n")

    # Cost
    parts.append("\n## Cost\n\n")
    parts.append("| job_id | phase | gpu | est_usd | actual_usd | seconds | note |\n")
    parts.append("|---|---|---|---|---|---|---|\n")
    for r in modal_2b_only or modal_2b:
        note = str(r.get("note") or "")[:80]
        parts.append(
            f"| {r.get('job_id')} | {r.get('phase')} | {r.get('gpu')} | "
            f"{r.get('est_usd')} | {r.get('actual_usd')} | "
            f"{r.get('actual_seconds')} | {note} |\n"
        )
    parts.append(
        "\nModal dashboard figure is authoritative; compare ledger actuals to the "
        "heyronith workspace usage page.\n"
    )

    colab_rows = [r for r in ledger if r.get("platform") == "colab"]
    parts.append("\n### Colab\n\n")
    if colab_rows:
        for r in colab_rows:
            parts.append(
                f"- {r.get('job_id')}: actual_cu={r.get('actual_cu')} "
                f"seconds={r.get('actual_seconds')} note={r.get('note')}\n"
            )
        parts.append(
            "\nCU/hour: see `configs/budget.yaml` `colab_l4_cu_per_hour` after measurement.\n"
        )
    else:
        parts.append("_Not run or not ledgered yet._\n")

    parts.append("\n## Revised pilot / main-run projections (batched)\n\n")
    parts.append(
        "Fill from measured aggregate tok/s above. Phase 2 sequential ~20 tok/s; "
        "batched dry-run v2 should cut GPU-hours by several×. "
        "Pilot/main estimates should use the batched throughput, not Phase 2.\n"
    )

    parts.append("\n## Categories / protocols\n\n")
    parts.append(
        f"- Categories: {list(CATEGORIES)} (7 × 5 = 35 items, 70 clauses).\n"
        "- Protocols: PERMISSIVE and FORCED. H1 primary contrast COR vs AGENT.\n"
        "- Dry-run data is tagged `phase2b_dryrun` and must not enter analysis.\n"
    )

    out = root / "reports" / "PHASE_2B.md"
    out.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
