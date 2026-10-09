"""Verbalized evaluation-awareness coding (prereg §6.8 sensitivity 2 / Phase 7E-A)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from rc.generation import build_request
from rc.judging import parse_eval_awareness_response, prompt_sha256, render_eval_awareness_prompt
from rc.openai_batch import OpenAIBatchBackend, estimate_batch_usd
from rc.phase7b import api_submission_allowed, load_openai_dashboard_usd
from rc.pilot_coding import extract_pilot_notes

EVAL_CONDS = ("SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT")
MASTER_SEED = 20261004
CAP_USD = 55.0


def collect_units(run_tag: str, root: Path) -> list[dict[str, Any]]:
    notes = extract_pilot_notes(run_tag, root=root)
    units: list[dict[str, Any]] = []
    for n in notes:
        if n.get("protocol") != "FORCED":
            continue
        if n.get("condition") not in EVAL_CONDS:
            continue
        units.append(
            {
                "unit_id": f"{n['note_id']}|note",
                "config_id": n["config_id"],
                "protocol": "FORCED",
                "condition": n["condition"],
                "chain": n["chain"],
                "round": n["round"],
                "kind": "note",
                "text": n["text"],
            }
        )
    think = root / "runs" / run_tag / "qwen38_27b_think" / "FORCED"
    for cond in EVAL_CONDS:
        struct = think / cond / "STRUCTURED"
        if not struct.exists():
            continue
        for chain_dir in sorted(struct.glob("chain_*")):
            path = chain_dir / "rounds.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("parse_status") != "ok":
                    continue
                tr = str(row.get("text_reasoning") or "").strip()
                if not tr:
                    continue
                rnd = row.get("round")
                units.append(
                    {
                        "unit_id": (
                            f"qwen38_27b_think|FORCED|{cond}|{chain_dir.name}|r{rnd}|reasoning"
                        ),
                        "config_id": "qwen38_27b_think",
                        "protocol": "FORCED",
                        "condition": cond,
                        "chain": chain_dir.name,
                        "round": rnd,
                        "kind": "reasoning",
                        "text": tr,
                    }
                )
    units.sort(key=lambda u: u["unit_id"])
    return units


def forecast_units(units: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    if not units:
        return {"n": 0, "est_usd": 0.0, "est_input_tokens_per": 0}
    sample = units[:: max(1, len(units) // 200)][:200]
    toks = [
        max(1, len(render_eval_awareness_prompt(u["text"], root=root)) // 4) for u in sample
    ]
    mean_in = int(sum(toks) / len(toks) * 1.25)
    est = estimate_batch_usd(
        len(units), est_input_tokens_per=mean_in, est_output_tokens_per=50
    )
    return {
        "n": len(units),
        "est_usd": est,
        "est_input_tokens_per": mean_in,
        "sample_mean_prompt_tokens": int(sum(toks) / len(toks)),
    }


def chain_label(condition: str, chain: str) -> str:
    if str(chain).startswith("chain_"):
        k = int(str(chain).split("_", 1)[1])
    else:
        k = int(chain)
    return f"{condition}:{k}"


def post_dashboard_openai_usd(root: Path) -> float:
    """OpenAI spend recorded after the D71 dashboard snapshot (e.g. StrongREJECT)."""
    post = 0.0
    for ledger in (
        root / "results" / "phase7d_pull" / "budget_ledger.jsonl",
        root / "runs" / "main_v1_7d" / "budget" / "ledger.jsonl",
        root / "runs" / "main_v1_7d" / "budget_ledger.jsonl",
    ):
        if not ledger.exists():
            continue
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            post += float(r.get("actual_usd") or r.get("est_usd") or 0)
        break
    return post


def run_eval_awareness(
    *,
    run_tag: str = "main_v1",
    root: Path,
    out_dir: Path | None = None,
    cap_usd: float = CAP_USD,
    dashboard_usd: float | None = None,
    post_dashboard_usd: float | None = None,
    forecast_only: bool = False,
) -> dict[str, Any]:
    """Batch-code eval awareness; return totals-only summary + flagged chains."""
    # Normalize OpenAI env from Modal secret aliases.
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENAI_KEY"]

    out_dir = out_dir or (root / "runs" / run_tag / "coding" / "eval_awareness")
    out_dir.mkdir(parents=True, exist_ok=True)

    units = collect_units(run_tag, root)
    existing_path = out_dir / "gpt54.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if existing_path.exists():
        for line in existing_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            uid = row.get("unit_id")
            if uid and row.get("eval_awareness") is not None:
                existing[str(uid)] = row
    pending = [u for u in units if u["unit_id"] not in existing]
    fc = (
        {"n": 0, "est_usd": 0.0, "est_input_tokens_per": 0, "sample_mean_prompt_tokens": 0}
        if not pending
        else forecast_units(pending, root)
    )

    dash = float(dashboard_usd) if dashboard_usd is not None else float(load_openai_dashboard_usd(root))
    post = (
        float(post_dashboard_usd)
        if post_dashboard_usd is not None
        else post_dashboard_openai_usd(root)
    )
    to_date = dash + post
    projected = to_date + float(fc["est_usd"])
    gate = {
        "dashboard_usd": dash,
        "post_dashboard_usd": post,
        "to_date_usd": to_date,
        "forecast_usd": fc["est_usd"],
        "projected_usd": projected,
        "cap_usd": cap_usd,
        "ok": projected <= cap_usd,
        "n_units_total": len(units),
        "n_pending": len(pending),
        "forecast_detail": fc,
    }
    (out_dir / "forecast.json").write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if forecast_only:
        return {"forecast_only": True, **gate}
    if not gate["ok"]:
        return {"stopped": True, "reason": "budget_gate", **gate}

    ok, reason = api_submission_allowed(
        float(fc["est_usd"]),
        platform="openai",
        root=root,
        openai_spent_floor=to_date,
    )
    if not ok and pending:
        return {"stopped": True, "reason": reason, **gate}

    meta: dict[str, Any]
    if pending:
        reqs = []
        for u in pending:
            prompt = render_eval_awareness_prompt(u["text"], root=root)
            u["prompt_sha256"] = prompt_sha256(prompt)
            seed = int(
                hashlib.sha256(f"{MASTER_SEED}|eval_aware|{u['unit_id']}".encode()).hexdigest()[
                    :8
                ],
                16,
            )
            reqs.append(
                build_request(
                    prompt,
                    "gpt54",
                    seed,
                    root=root,
                    schema_name="judge_eval_awareness",
                )
            )
        backend = OpenAIBatchBackend(
            "gpt54",
            work_dir=out_dir / "batch",
            root=root,
            job_id=f"eval_aware_{run_tag}",
            poll_seconds=30.0,
        )
        t0 = time.time()
        gens = backend.generate(reqs)
        elapsed = time.time() - t0
        new_rows: list[dict[str, Any]] = []
        hash_mismatches = 0
        for u, gen in zip(pending, gens, strict=True):
            parsed = parse_eval_awareness_response(gen.text_final)
            recomputed = prompt_sha256(render_eval_awareness_prompt(u["text"], root=root))
            if recomputed != u["prompt_sha256"]:
                hash_mismatches += 1
            new_rows.append(
                {
                    **u,
                    **parsed,
                    "judge_id": "gpt54",
                    "raw_text": gen.text_final,
                    "finish_reason": gen.finish_reason,
                    "n_output_tokens": gen.n_output_tokens,
                    "n_prompt_tokens": gen.n_prompt_tokens,
                    "latency_s": gen.latency_s,
                    "submit_mode": gen.submit_mode,
                }
            )
        with existing_path.open("a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                existing[row["unit_id"]] = row
        cost = backend.last_cost
        meta = {
            "n_new": len(new_rows),
            "api_usd": getattr(cost, "usd", None),
            "batch_id": getattr(cost, "batch_id", None),
            "elapsed_s": elapsed,
            "prompt_hash_mismatches": hash_mismatches,
            "prompt_hash_ok": hash_mismatches == 0,
        }
        (out_dir / "gpt54_meta.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        meta = {"n_new": 0, "api_usd": 0.0, "resumed": True}

    flagged_rounds = 0
    chain_flags: dict[tuple[str, str, str], bool] = {}
    for row in existing.values():
        cl = chain_label(str(row["condition"]), str(row["chain"]))
        key = (str(row["config_id"]), str(row["condition"]), cl)
        if row.get("eval_awareness") is True:
            flagged_rounds += 1
            chain_flags[key] = True
        else:
            chain_flags.setdefault(key, False)

    flagged_chains = [
        {"config": c, "condition": cond, "chain": ch}
        for (c, cond, ch), flag in sorted(chain_flags.items())
        if flag
    ]
    summary = {
        "n_units": len(existing),
        "n_flagged_rounds": flagged_rounds,
        "n_flagged_chains": len(flagged_chains),
        "flagged_chains": flagged_chains,
        "meta": meta,
        "budget_gate": gate,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
