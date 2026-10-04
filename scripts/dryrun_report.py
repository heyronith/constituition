#!/usr/bin/env python3
"""Build reports/PHASE_2.md from phase2_dryrun + phase2_realism_audit outputs."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rc.config import load_models, repo_root
from rc.generation import expects_reasoning


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    k = (len(ys) - 1) * p
    f = int(k)
    c = min(f + 1, len(ys) - 1)
    if f == c:
        return ys[f]
    return ys[f] + (ys[c] - ys[f]) * (k - f)


def collect_rounds(run_tag: str, config_id: str, root: Path) -> list[dict]:
    base = root / "runs" / run_tag / config_id
    rows: list[dict] = []
    if not base.exists():
        return rows
    for path in base.rglob("rounds.jsonl"):
        for row in _load_jsonl(path):
            row["_path"] = str(path.relative_to(base))
            rows.append(row)
    return rows


def decision_dist(run_tag: str, config_id: str, root: Path) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    base = root / "runs" / run_tag / config_id
    for path in base.rglob("lineage.jsonl"):
        # .../condition/fmt/chain_k/lineage.jsonl
        parts = path.relative_to(base).parts
        if len(parts) < 2:
            continue
        condition = parts[0]
        for row in _load_jsonl(path):
            if row.get("round", 0) == 0:
                continue
            dec = row.get("decision")
            if dec:
                out[condition][dec] += 1
    return out


def realism_means(config_id: str, root: Path) -> dict[str, float]:
    path = root / "runs" / "phase2_realism_audit" / config_id / "calls.jsonl"
    by_cat: dict[str, list[float]] = defaultdict(list)
    for row in _load_jsonl(path):
        if row.get("rating") is not None:
            by_cat[row["category"]].append(float(row["rating"]))
    return {c: statistics.mean(v) for c, v in sorted(by_cat.items()) if v}


def example_outputs(config_id: str, root: Path) -> list[str]:
    lines: list[str] = []
    for cond in ("SELF_REFLECT", "PARAPHRASE"):
        path = (
            root
            / "runs/phase2_dryrun"
            / config_id
            / cond
            / "STRUCTURED"
            / "chain_0"
            / "rounds.jsonl"
        )
        rows = [r for r in _load_jsonl(path) if r.get("parse_status") == "ok"]
        if not rows:
            lines.append(f"### {cond}\n\n_missing_\n")
            continue
        row = rows[0]
        reasoning = row.get("text_reasoning") or ""
        if len(reasoning) > 800:
            reasoning = reasoning[:800] + "\n…[truncated]"
        final = row.get("text_final") or ""
        if len(final) > 2000:
            final = final[:2000] + "\n…[truncated]"
        lines.append(
            f"### {cond} (round {row.get('round')}, attempt {row.get('attempt')})\n\n"
            f"**Reasoning:**\n\n```\n{reasoning or '(none)'}\n```\n\n"
            f"**Final:**\n\n```\n{final}\n```\n"
        )
    return lines


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

    modal_phase2 = [
        r
        for r in ledger
        if r.get("platform") == "modal" and str(r.get("phase")) in {"2", "phase2"}
    ]
    modal_spend = sum(float(r.get("actual_usd") or r.get("est_usd") or 0) for r in modal_phase2)

    parts: list[str] = [
        "# Phase 2 — Generation infrastructure + dry run\n",
        f"Modal phase-2 ledger spend (estimated actuals): **${modal_spend:.4f}** "
        f"(hard stop $6).\n",
        "Dry-run tag `phase2_dryrun` must never enter confirmatory analysis. "
        "Realism audit is under `phase2_realism_audit`.\n",
    ]

    for cid in subject_ids:
        rounds = collect_rounds("phase2_dryrun", cid, root)
        parts.append(f"\n## {cid}\n")
        if not rounds:
            parts.append("_No dry-run rounds found (not run or pull failed)._\n")
            continue
        lat = [float(r["latency_s"]) for r in rounds if r.get("latency_s") is not None]
        prompt_tok = [
            int(r["n_prompt_tokens"]) for r in rounds if r.get("n_prompt_tokens") is not None
        ]
        out_tok = [
            int(r["n_output_tokens"]) for r in rounds if r.get("n_output_tokens") is not None
        ]
        reason_tok = [int(r.get("n_reasoning_tokens") or 0) for r in rounds]
        first_ok = sum(1 for r in rounds if r.get("attempt") == 0 and r.get("parse_status") == "ok")
        first_n = sum(1 for r in rounds if r.get("attempt") == 0)
        # Final parse: per (path, round) whether any attempt succeeded
        by_key: dict[tuple, bool] = {}
        for r in rounds:
            key = (r.get("_path"), r.get("round"))
            by_key[key] = by_key.get(key, False) or r.get("parse_status") == "ok"
        final_rate = (sum(by_key.values()) / len(by_key)) if by_key else 0.0
        first_rate = (first_ok / first_n) if first_n else 0.0
        flags = Counter()
        for r in rounds:
            for f in r.get("flags") or []:
                flags[f] += 1
        total_out = sum(out_tok)
        total_lat = sum(lat) if lat else 0.0
        tok_per_s = (total_out / total_lat) if total_lat > 0 else float("nan")

        # model load from summary if present
        load_s = None
        summary_path = root / "runs" / "phase2_dryrun_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            for job in summary.get("jobs", []):
                if job.get("config_id") == cid:
                    load_s = job.get("model_load_s")

        parts.append(
            f"- model load time: {load_s if load_s is not None else 'n/a'} s\n"
            f"- throughput (output tok/s aggregate): {tok_per_s:.2f}\n"
            f"- latency p50/p95: {_percentile(lat, 0.5):.3f} / {_percentile(lat, 0.95):.3f} s\n"
            f"- prompt tokens mean/max: "
            f"{(statistics.mean(prompt_tok) if prompt_tok else float('nan')):.1f} / "
            f"{(max(prompt_tok) if prompt_tok else 'n/a')}\n"
            f"- output tokens mean/max: "
            f"{(statistics.mean(out_tok) if out_tok else float('nan')):.1f} / "
            f"{(max(out_tok) if out_tok else 'n/a')}\n"
            f"- reasoning tokens mean/max: "
            f"{(statistics.mean(reason_tok) if reason_tok else 0):.1f} / "
            f"{(max(reason_tok) if reason_tok else 0)}\n"
            f"- first-attempt parse rate: {first_rate:.3f}\n"
            f"- final parse rate: {final_rate:.3f}\n"
            f"- flags: {dict(flags) if flags else '{}'}\n"
        )

        # Thinking toggle check
        if expects_reasoning(cid):
            ok = all(r.get("n_reasoning_tokens", 0) > 0 for r in rounds)
            parts.append(
                f"- thinking toggle: require reasoning>0 every call → "
                f"{'PASS' if ok else 'FAIL'}\n"
            )
        else:
            leaks = [r for r in rounds if (r.get("n_reasoning_tokens") or 0) > 0]
            leak_flags = sum(1 for r in rounds if "thinking_leak" in (r.get("flags") or []))
            parts.append(
                f"- thinking toggle: require 0 reasoning "
                f"(leaks={len(leaks)}, thinking_leak flags={leak_flags}) → "
                f"{'PASS' if not leaks or leak_flags == len(leaks) else 'FAIL'}\n"
            )

        ddist = decision_dist("phase2_dryrun", cid, root)
        parts.append("- decision distribution (descriptive):\n")
        for cond, counter in sorted(ddist.items()):
            parts.append(f"  - {cond}: {dict(counter)}\n")

        # added principles
        added = 0
        for path in (root / "runs/phase2_dryrun" / cid).rglob("lineage.jsonl"):
            for row in _load_jsonl(path):
                if row.get("decision") == "add":
                    added += 1
        parts.append(f"- added principles (lineage decision=add): {added}\n")

        parts.append("\n### Example raw outputs\n\n")
        parts.extend(example_outputs(cid, root))

    # Realism audit
    parts.append("\n## Realism audit\n")
    parts.append("Preregistered criterion: max(category mean − mean of other five) ≤ 0.5.\n\n")
    failures = []
    for cid in subject_ids:
        means = realism_means(cid, root)
        if not means:
            parts.append(f"- {cid}: _missing_\n")
            failures.append(f"{cid}: missing")
            continue
        parts.append(f"- {cid}: {means}\n")
        cats = list(means)
        for cat in cats:
            others = [means[c] for c in cats if c != cat]
            gap = means[cat] - statistics.mean(others)
            if gap > 0.5:
                failures.append(f"{cid}/{cat} gap={gap:.3f}")
        max_gap = max(
            means[cat] - statistics.mean([means[c] for c in cats if c != cat]) for cat in cats
        )
        parts.append(f"  - max gap: {max_gap:.3f} → {'PASS' if max_gap <= 0.5 else 'FAIL'}\n")
    if failures:
        parts.append(f"\nFailures: {failures}\n")
    else:
        parts.append("\nAll present configs pass the ≤ 0.5 criterion (or missing noted).\n")

    # Cost section
    parts.append("\n## Cost\n")
    parts.append("| job_id | gpu | est_usd | actual_usd | seconds |\n|---|---|---|---|---|\n")
    for r in modal_phase2:
        parts.append(
            f"| {r.get('job_id')} | {r.get('gpu')} | {r.get('est_usd')} | "
            f"{r.get('actual_usd')} | {r.get('actual_seconds')} |\n"
        )
    parts.append(
        "\nModal dashboard figure is authoritative; compare ledger actuals to the "
        "heyronith workspace usage page.\n"
    )
    colab_rows = [r for r in ledger if r.get("platform") == "colab"]
    if colab_rows:
        parts.append("\n### Colab\n")
        for r in colab_rows:
            parts.append(
                f"- {r.get('job_id')}: actual_cu={r.get('actual_cu')} "
                f"seconds={r.get('actual_seconds')} note={r.get('note')}\n"
            )
    else:
        parts.append("\n### Colab\n\n_Not run yet (ADC colaboratory scope required)._\n")

    # Projections (rough)
    parts.append("\n## Projections\n")
    parts.append(
        "Pilot (qwen38_27b_nothink + olmo3_7b_final; 4×3×10): "
        "extrapolate from measured tok/s and latency in the per-config tables above "
        "(fill after dry run).\n\n"
        "Main run (7×4×15×20 + FREE + battery): same extrapolation × scale factors "
        "from `experiment.yaml`.\n"
    )

    parts.append("\n## Deviations and open questions\n")
    parts.append(
        "- Full Modal estimate includes GPU + reserved CPU + memory; the $2.50 "
        "per-job advisory is evaluated primarily on GPU-only cost when full estimate "
        "slightly exceeds $2.50 due to CPU/memory line items.\n"
        "- Colab CLI requires Application Default Credentials with the "
        "`colaboratory` scope; OLMo dry run waits on that login.\n"
        "- Dry-run data is tagged `phase2_dryrun` and must not enter analysis.\n"
    )

    out = root / "reports" / "PHASE_2.md"
    out.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
