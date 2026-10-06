"""D49: corrected binomial power (Holm worst-case) + main-run G4 scope."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.budget import estimate_modal_usd, spent_api_usd, spent_modal_usd
from rc.config import load_budget, load_models, repo_root
from rc.cost_projection import (
    COMPUTE_GPU,
    dryrun_load_seconds,
    gpu_seconds_per_unit_round_from_pilot,
)
from rc.d48_design import build_primary_coded
from rc.judging import EROSION_FATES, normalize_fate
from rc.pilot_coding import _cons_at, _load_jsonl

MASTER_SEED = 20261004
N_CONFIGS = 7
N_ITEMS_PER_CAT = 5
N_ROUNDS_FORCED = 20
N_ROUNDS_PERMISSIVE = 10
N_CONDITIONS = 4
HOLM_FAMILY = 3  # H1, H2a, H2b — worst-case α = 0.05 / 3


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _nppf(p: float) -> float:
    """Inverse standard normal (Acklam)."""
    if not 0.0 < p < 1.0:
        raise ValueError(p)
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def wilson_ci(events: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = events / n
    den = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return ((centre - half) / den, (centre + half) / den)


def estimate_forced_agent_hazard(
    coded: list[dict[str, Any]] | None = None,
    *,
    run_tag: str = "pilot_v1",
    root: Path | None = None,
) -> dict[str, Any]:
    """AGENT per-round erosion hazard from discrete-time risk sets.

    Pooled over all FORCED conditions × both pilot configs (D49). Uses lineage
    constitutions for at-risk counts (not edit-only coded rows).
    """
    root = root or repo_root()
    if coded is None:
        coded = build_primary_coded(root=root)

    fate_lookup = {
        r["transition_id"]: (
            bool(r["eroded_event"])
            if r.get("eroded_event") is not None
            else normalize_fate(r.get("fate")) in EROSION_FATES
        )
        for r in coded
        if r.get("kind") in ("per_round", "per_round_absorbed")
    }
    # Also map structural deletes.
    for r in coded:
        if r.get("kind") in ("per_round", "per_round_absorbed") and r.get("decision") == "delete":
            fate_lookup.setdefault(r["transition_id"], True)

    agent_events = agent_risk = 0
    cor_events = cor_risk = 0
    by_condition: dict[str, dict[str, int]] = defaultdict(
        lambda: {"agent_events": 0, "agent_risk": 0, "cor_events": 0, "cor_risk": 0}
    )
    by_config: dict[str, dict[str, int]] = defaultdict(
        lambda: {"agent_events": 0, "agent_risk": 0, "cor_events": 0, "cor_risk": 0}
    )

    base = root / "runs" / run_tag
    conditions = ("SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT", "PARAPHRASE")
    for config_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for cond in conditions:
            for chain_dir in sorted(
                (config_dir / "FORCED" / cond / "STRUCTURED").glob("chain_*")
            ):
                if not chain_dir.is_dir():
                    continue
                lineage = _load_jsonl(chain_dir / "lineage.jsonl")
                item_eroded: set[str] = set()
                # Pilot chains are 10 rounds; count whatever rounds exist.
                max_round = 0
                for row in lineage:
                    try:
                        max_round = max(max_round, int(row.get("round", 0)))
                    except (TypeError, ValueError):
                        continue
                for rnd in range(1, max_round + 1):
                    rows = [r for r in lineage if int(r.get("round", -1)) == rnd]
                    cons = _cons_at(chain_dir, rnd - 1)
                    if not cons:
                        continue
                    present = [
                        m
                        for m in (cons.get("metadata") or {}).values()
                        if m.get("item_id") and m["item_id"] not in item_eroded
                    ]
                    for meta in present:
                        item_id = meta["item_id"]
                        cat = meta.get("category")
                        if cat not in ("AGENT", "COR"):
                            continue
                        affected = [
                            r
                            for r in rows
                            if r.get("item_id") == item_id
                            and r.get("decision") in ("revise", "merge", "delete")
                        ]
                        eroded = False
                        for r in affected:
                            tid = (
                                f"{config_dir.name}|FORCED|{cond}|{chain_dir.name}|r{rnd}|"
                                f"{item_id}|{r.get('decision')}"
                            )
                            if fate_lookup.get(tid):
                                eroded = True
                                break
                            if r.get("decision") == "delete":
                                eroded = True
                                break
                        if cat == "AGENT":
                            agent_risk += 1
                            agent_events += int(eroded)
                            by_condition[cond]["agent_risk"] += 1
                            by_condition[cond]["agent_events"] += int(eroded)
                            by_config[config_dir.name]["agent_risk"] += 1
                            by_config[config_dir.name]["agent_events"] += int(eroded)
                        else:
                            cor_risk += 1
                            cor_events += int(eroded)
                            by_condition[cond]["cor_risk"] += 1
                            by_condition[cond]["cor_events"] += int(eroded)
                            by_config[config_dir.name]["cor_risk"] += 1
                            by_config[config_dir.name]["cor_events"] += int(eroded)
                        if eroded:
                            item_eroded.add(item_id)

    baseline = agent_events / agent_risk if agent_risk else float("nan")
    lo, hi = wilson_ci(agent_events, agent_risk)
    return {
        "decision": "D49",
        "pool": "FORCED discrete-time risk sets × all 4 conditions × both pilot configs",
        "category": "AGENT",
        "agent_events": agent_events,
        "agent_risk": agent_risk,
        "agent_baseline_hazard": baseline,
        "agent_hazard_ci95": [lo, hi],
        "ci_method": "Wilson",
        "cor_events": cor_events,
        "cor_risk": cor_risk,
        "cor_hazard": (cor_events / cor_risk) if cor_risk else float("nan"),
        "by_condition": dict(by_condition),
        "by_config": dict(by_config),
        "n_configs_pilot": len(by_config),
        "n_conditions": len(by_condition),
        "note": (
            "D48 used SELF_REFLECT only (agent_events=2 / risk=285 → 0.007). "
            "D49 pools all FORCED conditions. Coded edit rows alone are not a risk set."
        ),
    }


def binomial_h1_power(
    n_chains: int,
    *,
    baseline: float,
    hr: float = 1.5,
    alpha: float = 0.05 / HOLM_FAMILY,
    n_configs: int = N_CONFIGS,
    n_items: int = N_ITEMS_PER_CAT,
    n_rounds: int = N_ROUNDS_FORCED,
    n_sims: int = 20000,
    seed: int = MASTER_SEED,
) -> dict[str, Any]:
    """One-sided two-proportion score test; Holm worst-case α = 0.05/3.

    SELF-only COR vs AGENT (lead audit). At-risk = configs × chains × 5 items × 20
    rounds with no attrition (matches lead independent check).
    """
    p0 = float(baseline)
    p1 = min(0.999999, p0 * hr)
    n_obs = n_configs * n_chains * n_items * n_rounds
    za = _nppf(1.0 - alpha)
    rng = random.Random(
        int(
            __import__("hashlib")
            .sha256(f"{seed}|D49BIN|{n_chains}|{hr}|{baseline:.8f}".encode())
            .hexdigest()[:16],
            16,
        )
    )
    hits = 0
    for _ in range(n_sims):
        e0 = sum(1 for _ in range(n_obs) if rng.random() < p0)
        e1 = sum(1 for _ in range(n_obs) if rng.random() < p1)
        ph = (e0 + e1) / (2 * n_obs)
        se = math.sqrt(max(ph * (1 - ph) * (2 / n_obs), 1e-18))
        z = ((e1 / n_obs) - (e0 / n_obs)) / se
        if z > za:
            hits += 1
    # Analytic normal approximation (score / pooled H0 variance) for reporting.
    se0 = math.sqrt(p0 * (1 - p0) * (2 / n_obs))
    se1 = math.sqrt(p0 * (1 - p0) / n_obs + p1 * (1 - p1) / n_obs)
    analytic = _ncdf(((p1 - p0) - za * se0) / se1)
    return {
        "n_chains": n_chains,
        "hr": hr,
        "baseline": p0,
        "alpha": alpha,
        "holm_worst_case": True,
        "n_obs_per_arm": n_obs,
        "power_sim": hits / n_sims,
        "power_analytic": analytic,
        "n_sims": n_sims,
    }


def run_d49_power_table(
    hazard: dict[str, Any],
    *,
    n_values: tuple[int, ...] = (10, 15, 20, 25),
    hrs: tuple[float, ...] = (1.5, 2.0),
    n_sims: int = 20000,
    master_seed: int = MASTER_SEED,
) -> dict[str, Any]:
    baseline = float(hazard["agent_baseline_hazard"])
    lo, hi = hazard["agent_hazard_ci95"]
    table = []
    for n in n_values:
        for hr in hrs:
            row = binomial_h1_power(
                n, baseline=baseline, hr=hr, n_sims=n_sims, seed=master_seed
            )
            table.append(row)

    sens_table = []
    for n in n_values:
        sens_table.append(
            binomial_h1_power(
                n, baseline=float(lo), hr=1.5, n_sims=n_sims, seed=master_seed + 1
            )
        )

    recommended = None
    for row in table:
        if row["hr"] == 1.5 and row["power_sim"] >= 0.80:
            recommended = row["n_chains"]
            break

    return {
        "decision": "D49",
        "method": (
            "binomial two-proportion score test, one-sided, Holm worst-case α=0.05/3; "
            "SELF-only COR vs AGENT; at-risk = 7×N×5×20 (no attrition)"
        ),
        "discrepancy_d48": {
            "d48_power_h1_n10_hr15": 0.909,
            "lead_binomial_n10_hr15": 0.51,
            "causes": [
                "D48 GEE pooled SELF/OTHER/NEUTRAL rows (~3× information for shared params)",
                "D48 simulation set SELF COR hazard = HR × h2_ratio (=2.25 at HR=1.5), overstating H1",
                "Holm used three p-values but H2a≡H2b, so H1 rarely paid the full 0.05/3 penalty",
                "D48 hazard risk sets were SELF-only over 10 pilot rounds, not pooled FORCED",
            ],
        },
        "baseline_hazard": baseline,
        "baseline_ci95": [lo, hi],
        "agent_events": hazard["agent_events"],
        "agent_risk": hazard["agent_risk"],
        "table": table,
        "sensitivity_lower_ci": {
            "baseline": lo,
            "hr": 1.5,
            "table": sens_table,
        },
        "recommended_n_hr15": recommended,
        "n_sims": n_sims,
    }


def estimate_transition_counts(n_forced: int) -> dict[str, Any]:
    """Approximate LLM-judged transition counts under D49 judging scope."""
    # Pilot FORCED confirmatory LLM density: ~230 LLM / 251 confirmatory ≈ 0.92
    # of per-round targets; use pilot rates from coding_v3 primary.
    # Conservative: assume ~1 changed target/round/chain on average needing a judge
    # plus absorbed partners — calibrated from pilot n_llm / (configs×conds×chains×rounds).
    # Pilot: 2 configs × 4 cond × 3 chains × 10 rounds ≈ 240 unit-rounds; n_llm FORCED
    # per-round ≈ from d46 (230 confirmatory LLM / similar).
    # Use: forced_per_round_llm ≈ 0.96 × configs × conds × N × rounds  (almost every
    # target edit is LLM-coded; structural deletes are few).
    # From pilot_v1_coding: n_llm=2018 over mixed protocols. Better: count from coded.
    return {
        "forced_per_round_unit_rounds": N_CONFIGS * N_CONDITIONS * n_forced * N_ROUNDS_FORCED,
        "forced_cumulative_checkpoints": N_CONFIGS * N_CONDITIONS * n_forced * 2,  # r10, r20
        "permissive_cumulative_checkpoints": N_CONFIGS * N_CONDITIONS * 5 * 1,  # r10 only
        "note": "Exact LLM counts depend on change rate; G4 uses pilot-calibrated densities below.",
    }


def pilot_llm_densities(root: Path | None = None) -> dict[str, float]:
    """LLM-judged items per unit-round (or per cumulative checkpoint) from pilot."""
    root = root or repo_root()
    coded = build_primary_coded(root=root)
    # FORCED per-round LLM (non-structural) per unit-round.
    forced_pr = [
        r
        for r in coded
        if r.get("protocol") == "FORCED"
        and r.get("kind") in ("per_round", "per_round_absorbed")
        and not r.get("structural")
    ]
    # Unit-rounds in pilot: 2 configs × 4 cond × 3 chains × 10 rounds
    unit_rounds = 2 * 4 * 3 * 10
    # FORCED cumulative LLM at a checkpoint — approximate from cumulative rows.
    forced_cum = [
        r
        for r in coded
        if r.get("protocol") == "FORCED"
        and r.get("kind") == "cumulative"
        and not r.get("structural")
    ]
    # Pilot FORCED cumulative checkpoints: typically rounds 5/10 or similar — count unique
    # (config, cond, chain, round) from transition ids when possible.
    cum_keys = set()
    for r in forced_cum:
        parts = str(r["transition_id"]).split("|")
        # config|prot|cond|chain|cumK|...
        if len(parts) >= 5:
            cum_keys.add(tuple(parts[:5]))
    n_cum_checkpoints = max(len(cum_keys), 1)
    perm_cum = [
        r
        for r in coded
        if r.get("protocol") == "PERMISSIVE"
        and r.get("kind") == "cumulative"
        and not r.get("structural")
    ]
    perm_keys = set()
    for r in perm_cum:
        parts = str(r["transition_id"]).split("|")
        if len(parts) >= 5:
            perm_keys.add(tuple(parts[:5]))
    n_perm_checkpoints = max(len(perm_keys), 1)
    return {
        "forced_per_round_llm_per_unit_round": len(forced_pr) / unit_rounds,
        "forced_cumulative_llm_per_checkpoint": len(forced_cum) / n_cum_checkpoints,
        "permissive_cumulative_llm_per_checkpoint": len(perm_cum) / n_perm_checkpoints,
        "pilot_forced_per_round_llm": len(forced_pr),
        "pilot_forced_cum_llm": len(forced_cum),
        "pilot_perm_cum_llm": len(perm_cum),
        "pilot_forced_unit_rounds": unit_rounds,
        "pilot_forced_cum_checkpoints": n_cum_checkpoints,
        "pilot_perm_cum_checkpoints": n_perm_checkpoints,
    }


# Phase 2B batched aggregate output tok/s (reports/PHASE_2B.md) for scaling.
DRYRUN_TOK_S = {
    "qwen38_27b_nothink": 67.81,
    "qwen38_27b_think": 101.62,
    "gemma4_31b": 60.80,
    "gemma4_12b": 101.16,
    "olmo3_7b_final": 39.52,  # PHASE_2B olmo aggregate
    "olmo3_7b_sft": 39.52,
    "olmo3_7b_dpo": 39.52,
}


def scale_timings_d49(
    piloted: dict[tuple[str, str], float],
) -> dict[tuple[str, str], float]:
    """Scale unpiloted config×protocol cells by dry-run tok/s ratios.

    Anchors: Qwen-nothink (A100 family) and OLMo-final (L40S family) from pilot_v1.
    """
    out = dict(piloted)
    a100_family = {
        "qwen38_27b_nothink",
        "qwen38_27b_think",
        "gemma4_31b",
    }
    l40s_family = {
        "olmo3_7b_final",
        "olmo3_7b_sft",
        "olmo3_7b_dpo",
        "gemma4_12b",
    }
    for protocol in ("FORCED", "PERMISSIVE"):
        qwen = piloted.get(("qwen38_27b_nothink", protocol))
        olmo = piloted.get(("olmo3_7b_final", protocol))
        for cid in list(a100_family) + list(l40s_family):
            key = (cid, protocol)
            if key in out:
                continue
            if cid == "qwen38_27b_think" and qwen is not None:
                # Think emits far more tokens/round; Phase 2 wall-clock ≈1.8–2.0× nothink.
                # Do not use tok/s alone (2B aggregate tok/s is higher but rounds are longer).
                out[key] = qwen * 1.8
            elif cid in a100_family and qwen is not None:
                ref_tok = DRYRUN_TOK_S["qwen38_27b_nothink"]
                tok = DRYRUN_TOK_S.get(cid, ref_tok)
                out[key] = qwen * (ref_tok / tok)
            elif cid in l40s_family and olmo is not None:
                ref_tok = DRYRUN_TOK_S["olmo3_7b_final"]
                tok = DRYRUN_TOK_S.get(cid, ref_tok)
                out[key] = olmo * (ref_tok / tok)
    return out


def project_g4_d49(
    n_forced: int,
    *,
    root: Path | None = None,
    gpt54_usd_per_transition: float | None = None,
    mimo_usd_per_transition: float | None = None,
    h3_modal_usd: tuple[float, float] = (10.0, 15.0),
) -> dict[str, Any]:
    """G4 under D49 scope: FORCED N×20, PERMISSIVE 5×10, no FREE arm."""
    root = root or repo_root()
    budget = load_budget(root)
    models = load_models(root)
    piloted = gpu_seconds_per_unit_round_from_pilot(root=root)
    timings = scale_timings_d49(piloted)
    loads = dryrun_load_seconds(root)
    dens = pilot_llm_densities(root=root)

    if gpt54_usd_per_transition is None:
        meta = root / "runs" / "pilot_v1_coding_v3" / "coding_v3" / "gpt54_meta.json"
        m = json.loads(meta.read_text(encoding="utf-8"))
        gpt54_usd_per_transition = float(m["api_usd"]) / int(m["n"])
    if mimo_usd_per_transition is None:
        # From D48 MiMo pilot subsample cost / n
        mimo_usd_per_transition = 0.006323586 / 65

    spent_modal = spent_modal_usd(root)
    # Prefer phase ledger if richer
    pending = root / "runs" / "phase4_coding" / "ledger_pending_4f.jsonl"
    if pending.exists():
        extra_m = extra_a = 0.0
        for line in pending.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            usd = float(row.get("actual_usd") or 0)
            if row.get("platform") == "modal":
                extra_m += usd
            elif row.get("platform") in {"openai", "openrouter"}:
                extra_a += usd
        # spent_modal_usd already reads budget/ledger; pending is additive for report.
        pending_modal = extra_m
        pending_api = extra_a
    else:
        pending_modal = 0.0
        pending_api = spent_api_usd(root)

    remaining_modal = budget.modal_hard_cap_usd - spent_modal

    gen_seconds_by_gpu: dict[str, float] = defaultdict(float)
    n_unit_rounds = 0
    for subject in models.subjects:
        gpu = COMPUTE_GPU.get(subject.compute, "A100-80GB")
        # FORCED: N chains × 4 conditions × 20 rounds
        sec_f = timings.get((subject.config_id, "FORCED"), 6.0)
        units_f = N_CONDITIONS * n_forced
        gen_seconds_by_gpu[gpu] += units_f * N_ROUNDS_FORCED * sec_f
        n_unit_rounds += units_f * N_ROUNDS_FORCED
        # PERMISSIVE: 5 chains × 4 conditions × 10 rounds
        sec_p = timings.get((subject.config_id, "PERMISSIVE"), 6.0)
        units_p = N_CONDITIONS * 5
        gen_seconds_by_gpu[gpu] += units_p * N_ROUNDS_PERMISSIVE * sec_p
        n_unit_rounds += units_p * N_ROUNDS_PERMISSIVE
        # one model load per config
        gen_seconds_by_gpu[gpu] += loads.get(subject.config_id, 180.0)

    generation_usd = 0.0
    gen_by_gpu_usd = {}
    for gpu, seconds in sorted(gen_seconds_by_gpu.items()):
        usd = estimate_modal_usd(gpu, int(seconds) + 1, root=root)
        gen_by_gpu_usd[gpu] = {"seconds": seconds, "usd": usd}
        generation_usd += usd

    # Judging counts
    forced_unit_rounds = N_CONFIGS * N_CONDITIONS * n_forced * N_ROUNDS_FORCED
    forced_pr_llm = forced_unit_rounds * dens["forced_per_round_llm_per_unit_round"]
    forced_cum_checkpoints = N_CONFIGS * N_CONDITIONS * n_forced * 2  # r10, r20
    forced_cum_llm = forced_cum_checkpoints * dens["forced_cumulative_llm_per_checkpoint"]
    perm_cum_checkpoints = N_CONFIGS * N_CONDITIONS * 5 * 1  # r10
    perm_cum_llm = perm_cum_checkpoints * dens["permissive_cumulative_llm_per_checkpoint"]

    gpt54_n = forced_pr_llm + forced_cum_llm + perm_cum_llm
    mimo_n = 0.25 * forced_pr_llm
    api_gpt54 = gpt54_n * gpt54_usd_per_transition
    api_mimo = mimo_n * mimo_usd_per_transition
    api_usd = api_gpt54 + api_mimo

    return {
        "decision": "D49",
        "n_forced": n_forced,
        "n_permissive": 5,
        "rounds_forced": N_ROUNDS_FORCED,
        "rounds_permissive": N_ROUNDS_PERMISSIVE,
        "free_arm": "dropped",
        "scope": {
            "FORCED": f"{N_CONFIGS} configs × {N_CONDITIONS} conditions × {n_forced} chains (idx 0..) × {N_ROUNDS_FORCED} rounds",
            "PERMISSIVE": f"{N_CONFIGS} configs × {N_CONDITIONS} conditions × 5 chains (idx 0–4) × {N_ROUNDS_PERMISSIVE} rounds",
            "FREE": "dropped (limitation)",
        },
        "piloted_gpu_seconds_per_unit_round": {
            f"{c}|{p}": v for (c, p), v in sorted(piloted.items())
        },
        "scaled_gpu_seconds_per_unit_round": {
            f"{c}|{p}": v for (c, p), v in sorted(timings.items())
        },
        "dryrun_tok_s": DRYRUN_TOK_S,
        "model_load_seconds": loads,
        "generation": {
            "unit_rounds": n_unit_rounds,
            "by_gpu": gen_by_gpu_usd,
            "modal_usd": generation_usd,
        },
        "judging": {
            "densities": dens,
            "gpt54_n_transitions_est": gpt54_n,
            "mimo_n_transitions_est": mimo_n,
            "gpt54_usd_per_transition": gpt54_usd_per_transition,
            "mimo_usd_per_transition": mimo_usd_per_transition,
            "api_gpt54_usd": api_gpt54,
            "api_mimo_usd": api_mimo,
            "api_usd": api_usd,
            "api_cap_usd": "TBD (to be approved)",
        },
        "h3_behaviour_battery_modal_usd": {
            "low": h3_modal_usd[0],
            "high": h3_modal_usd[1],
            "note": "placeholder",
        },
        "budget": {
            "modal_hard_cap_usd": budget.modal_hard_cap_usd,
            "spent_modal_usd_ledger": spent_modal,
            "remaining_modal_usd": remaining_modal,
            "pending_4f_modal_usd": pending_modal,
            "pending_4f_api_usd": pending_api,
            "generation_fits_remaining_modal": generation_usd <= remaining_modal,
            "generation_plus_h3_high_fits": (generation_usd + h3_modal_usd[1])
            <= remaining_modal,
        },
        "totals": {
            "modal_generation_usd": generation_usd,
            "modal_with_h3_high_usd": generation_usd + h3_modal_usd[1],
            "api_judging_usd": api_usd,
        },
    }


def run_d49(*, root: Path | None = None, n_sims: int = 20000) -> dict[str, Any]:
    root = root or repo_root()
    out_dir = root / "runs" / "phase4_coding"
    out_dir.mkdir(parents=True, exist_ok=True)

    coded = build_primary_coded(root=root)
    hazard = estimate_forced_agent_hazard(coded, root=root)
    (out_dir / "hazard_estimates_d49.json").write_text(
        json.dumps(hazard, indent=2) + "\n", encoding="utf-8"
    )

    power = run_d49_power_table(hazard, n_sims=n_sims)
    (out_dir / "power_table_d49.json").write_text(
        json.dumps(power, indent=2) + "\n", encoding="utf-8"
    )

    n_star = power["recommended_n_hr15"]
    if n_star is None:
        n_star = max(r["n_chains"] for r in power["table"])

    g4 = project_g4_d49(int(n_star), root=root)
    # Also tabulate G4 at each candidate N for the report.
    g4_by_n = {n: project_g4_d49(n, root=root) for n in (10, 15, 20, 25)}
    payload = {"chosen_n": n_star, "at_chosen_n": g4, "by_n": {str(k): v for k, v in g4_by_n.items()}}
    (out_dir / "g4_projection_d49.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    return {"hazard": hazard, "power": power, "g4": payload}
