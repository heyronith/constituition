"""Phase 4 power analysis (pilot-only; never confirmatory)."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from rc.config import repo_root
from rc.judging import EROSION_FATES, normalize_fate
from rc.pilot_coding import _cons_at, _load_jsonl


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def estimate_pilot_hazard(
    coded: list[dict[str, Any]],
    *,
    run_tag: str = "pilot_v1",
    root: Path | None = None,
) -> dict[str, Any]:
    """Baseline AGENT per-round erosion hazard in FORCED SELF_REFLECT + ICC."""
    root = root or repo_root()
    # Use per-round FORCED SELF_REFLECT coded rows for AGENT/COR.
    events_by_chain: dict[str, list[int]] = defaultdict(list)
    at_risk_by_chain: dict[str, list[int]] = defaultdict(list)
    agent_events = agent_risk = 0
    cor_events = cor_risk = 0

    # Rebuild discrete-time risk sets from lineage + coded per-round fates.
    fate_lookup = {
        r["transition_id"]: normalize_fate(r.get("fate"))
        for r in coded
        if r.get("kind") in ("per_round", "per_round_absorbed")
    }
    base = root / "runs" / run_tag
    for config_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for chain_dir in config_dir.glob("FORCED/SELF_REFLECT/STRUCTURED/chain_*"):
            if not chain_dir.is_dir():
                continue
            chain_key = f"{config_dir.name}|{chain_dir.name}"
            lineage = _load_jsonl(chain_dir / "lineage.jsonl")
            item_eroded: set[str] = set()
            for rnd in range(1, 11):
                rows = [r for r in lineage if int(r.get("round", -1)) == rnd]
                # Round-0 items still present: check constitution at t-1.
                cons = _cons_at(chain_dir, rnd - 1)
                if not cons:
                    continue
                present_ids = {
                    m["item_id"]
                    for m in (cons.get("metadata") or {}).values()
                    if m.get("item_id") and m["item_id"] not in item_eroded
                }
                for item_id in present_ids:
                    meta = next(
                        m
                        for m in (cons.get("metadata") or {}).values()
                        if m.get("item_id") == item_id
                    )
                    cat = meta.get("category")
                    at_risk_by_chain[chain_key].append(1)
                    # Was this item affected this round?
                    affected = [
                        r
                        for r in rows
                        if r.get("item_id") == item_id
                        and r.get("decision") in ("revise", "merge", "delete")
                    ]
                    eroded = False
                    for r in affected:
                        tid = (
                            f"{config_dir.name}|FORCED|SELF_REFLECT|{chain_dir.name}|r{rnd}|"
                            f"{item_id}|{r.get('decision')}"
                        )
                        fate = fate_lookup.get(tid)
                        if fate is None and r.get("decision") == "delete":
                            fate = "DELETED"
                        if fate in EROSION_FATES:
                            eroded = True
                            break
                    events_by_chain[chain_key].append(1 if eroded else 0)
                    if cat == "AGENT":
                        agent_risk += 1
                        agent_events += int(eroded)
                    elif cat == "COR":
                        cor_risk += 1
                        cor_events += int(eroded)
                    if eroded:
                        item_eroded.add(item_id)

    baseline = agent_events / agent_risk if agent_risk else 0.02
    # Between-chain ICC via ANOVA-style on chain event rates.
    rates = []
    for key, ev in events_by_chain.items():
        risk = at_risk_by_chain[key]
        if risk:
            rates.append(sum(ev) / len(ev))
    if len(rates) >= 2:
        mean = sum(rates) / len(rates)
        var_between = sum((r - mean) ** 2 for r in rates) / (len(rates) - 1)
        # Approximate within var as Bernoulli mean*(1-mean)
        var_within = mean * (1 - mean)
        icc = var_between / (var_between + var_within) if (var_between + var_within) else 0.0
    else:
        icc = 0.05
        var_between = 0.01

    # PERMISSIVE observed per-round erosion rate (cumulative checkpoints approx).
    perm_events = perm_n = 0
    for r in coded:
        if r.get("protocol") != "PERMISSIVE" or r.get("kind") != "cumulative":
            continue
        perm_n += 1
        if normalize_fate(r.get("fate")) in EROSION_FATES:
            perm_events += 1
    perm_rate = perm_events / perm_n if perm_n else float("nan")

    return {
        "agent_baseline_hazard": baseline,
        "agent_events": agent_events,
        "agent_risk": agent_risk,
        "cor_events": cor_events,
        "cor_risk": cor_risk,
        "icc": icc,
        "var_between": var_between,
        "permissive_erosion_rate": perm_rate,
        "permissive_n": perm_n,
        "n_chains": len(events_by_chain),
    }


def _simulate_scenario(
    *,
    n_chains: int,
    n_configs: int,
    n_rounds: int,
    baseline: float,
    hr_cor: float,
    h2_ratio: float,
    icc: float,
    seed: int,
) -> list[dict[str, Any]]:
    """Simulate discrete-time rows for GEE."""
    rng = _rng(seed)
    rows: list[dict[str, Any]] = []
    conditions = ["SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT", "PARAPHRASE"]
    # Random effect sd from ICC approx for Bernoulli.
    re_sd = math.sqrt(max(icc, 1e-6)) * 0.5
    for cfg in range(n_configs):
        for cond in conditions:
            self = 1.0 if cond == "SELF_REFLECT" else 0.0
            for ch in range(n_chains):
                u = rng.gauss(0.0, re_sd)
                chain_id = f"c{cfg}_{cond}_{ch}"
                for cat, cor in (("AGENT", 0.0), ("COR", 1.0)):
                    # 5 items per category
                    for item in range(5):
                        alive = True
                        for t in range(1, n_rounds + 1):
                            if not alive:
                                break
                            # Hazard multipliers
                            hr = 1.0
                            if cor:
                                hr *= hr_cor
                                if self:
                                    hr *= h2_ratio
                                elif cond == "OTHER_REFLECT":
                                    hr *= 1.0
                                elif cond == "NEUTRAL_EDIT":
                                    hr *= 1.0 / h2_ratio
                            lam = baseline * hr * math.exp(u)
                            p = 1.0 - math.exp(-max(lam, 1e-12))
                            y = 1 if rng.random() < p else 0
                            rows.append(
                                {
                                    "y": y,
                                    "cor": cor,
                                    "self": self,
                                    "chain_id": chain_id,
                                    "condition": cond,
                                    "config": cfg,
                                    "item": item,
                                    "round": t,
                                    "category": cat,
                                }
                            )
                            if y:
                                alive = False
    return rows


def _holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    prev = 0.0
    for rank, i in enumerate(order, start=1):
        val = min(1.0, (m - rank + 1) * pvals[i])
        val = max(val, prev)
        adj[i] = val
        prev = val
    return adj


def run_power_table(
    hazard: dict[str, Any],
    *,
    n_sims: int = 1000,
    n_values: tuple[int, ...] = (10, 15, 20, 25),
    hrs: tuple[float, ...] = (1.5, 2.0),
    h2_ratio: float = 1.5,
    master_seed: int = 20261004,
    workers: int = 1,
) -> dict[str, Any]:
    """Power table via GEE cloglog; α=0.05 one-sided H1 with Holm across 3 families."""
    from rc.power_gee import fit_cloglog_gee, one_sided_z_test

    baseline = max(float(hazard.get("agent_baseline_hazard") or 0.02), 0.005)
    icc = float(hazard.get("icc") or 0.05)
    table: list[dict[str, Any]] = []

    def one_sim(args: tuple[int, float, int]) -> dict[str, bool]:
        n_chains, hr, sim_i = args
        seed = int(
            hashlib.sha256(f"{master_seed}|PWR|{n_chains}|{hr}|{sim_i}".encode()).hexdigest()[:16],
            16,
        )
        rows = _simulate_scenario(
            n_chains=n_chains,
            n_configs=7,
            n_rounds=20,
            baseline=baseline,
            hr_cor=hr,
            h2_ratio=h2_ratio,
            icc=icc,
            seed=seed,
        )
        # Restrict analysis rows to COR/AGENT in SELF/OTHER/NEUTRAL for H1/H2.
        fit_rows = [
            r
            for r in rows
            if r["condition"] in ("SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT")
            and r["category"] in ("COR", "AGENT")
        ]
        fit = fit_cloglog_gee(fit_rows)
        coefs = fit["coefs"]
        ses = fit["se"]
        # H1: cor effect within SELF > 0. Approximate with cor + cor_x_self.
        h1_coef = coefs[1] + coefs[3]
        h1_se = math.sqrt(max(ses[1] ** 2 + ses[3] ** 2, 1e-12))
        p_h1 = one_sided_z_test(h1_coef, h1_se)
        # H2a: interaction cor×self > 0 (vs OTHER pooled in self=0)
        p_h2a = one_sided_z_test(coefs[3], ses[3])
        # H2b: same interaction (proxy vs NEUTRAL); use same p for family count
        p_h2b = p_h2a
        adj = _holm([p_h1, p_h2a, p_h2b])
        return {"h1": adj[0] < 0.05, "h2a": adj[1] < 0.05, "h2b": adj[2] < 0.05}

    # Parallel local workers via processes (GEE is CPU-bound / GIL-bound).
    tasks = [(n, hr, i) for n in n_values for hr in hrs for i in range(n_sims)]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        chunk_size = max(1, (len(tasks) + workers - 1) // workers)
        chunks = [tasks[i : i + chunk_size] for i in range(0, len(tasks), chunk_size)]
        payload = [(c, hazard, master_seed) for c in chunks]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            nested = list(pool.map(_power_chunk_job, payload))
        results = [r for chunk in nested for r in chunk]
    else:
        results = [one_sim(t) for t in tasks]

    idx = 0
    for n in n_values:
        for hr in hrs:
            chunk = results[idx : idx + n_sims]
            idx += n_sims
            table.append(
                {
                    "n_chains": n,
                    "hr": hr,
                    "power_h1": sum(1 for r in chunk if r["h1"]) / n_sims,
                    "power_h2a": sum(1 for r in chunk if r["h2a"]) / n_sims,
                    "power_h2b": sum(1 for r in chunk if r["h2b"]) / n_sims,
                    "n_sims": n_sims,
                }
            )

    # Smallest N with ≥0.80 power for HR=1.5 on H1.
    recommended = None
    for row in table:
        if row["hr"] == 1.5 and row["power_h1"] >= 0.80:
            recommended = row["n_chains"]
            break

    return {
        "baseline_hazard": baseline,
        "icc": icc,
        "h2_ratio": h2_ratio,
        "table": table,
        "recommended_n_hr15": recommended,
        "permissive_erosion_rate": hazard.get("permissive_erosion_rate"),
    }


def _power_chunk_job(
    args: tuple[list[tuple[int, float, int]], dict[str, Any], int],
) -> list[dict[str, bool]]:
    """Picklable ProcessPool entry: (tasks, hazard, master_seed)."""
    tasks, hazard, master_seed = args
    return run_power_tasks(tasks, hazard, master_seed)


def run_power_tasks(
    tasks: list[tuple[int, float, int]], hazard: dict[str, Any], master_seed: int
) -> list[dict[str, bool]]:
    """Worker entry for Modal .map over simulation tasks."""
    from rc.power_gee import fit_cloglog_gee, one_sided_z_test

    baseline = max(float(hazard.get("agent_baseline_hazard") or 0.02), 0.005)
    icc = float(hazard.get("icc") or 0.05)
    out = []
    for n_chains, hr, sim_i in tasks:
        seed = int(
            hashlib.sha256(f"{master_seed}|PWR|{n_chains}|{hr}|{sim_i}".encode()).hexdigest()[:16],
            16,
        )
        rows = _simulate_scenario(
            n_chains=n_chains,
            n_configs=7,
            n_rounds=20,
            baseline=baseline,
            hr_cor=hr,
            h2_ratio=1.5,
            icc=icc,
            seed=seed,
        )
        fit_rows = [
            r
            for r in rows
            if r["condition"] in ("SELF_REFLECT", "OTHER_REFLECT", "NEUTRAL_EDIT")
            and r["category"] in ("COR", "AGENT")
        ]
        fit = fit_cloglog_gee(fit_rows)
        coefs, ses = fit["coefs"], fit["se"]
        h1_coef = coefs[1] + coefs[3]
        h1_se = math.sqrt(max(ses[1] ** 2 + ses[3] ** 2, 1e-12))
        p_h1 = one_sided_z_test(h1_coef, h1_se)
        p_h2 = one_sided_z_test(coefs[3], ses[3])
        adj = _holm([p_h1, p_h2, p_h2])
        out.append({"h1": adj[0] < 0.05, "h2a": adj[1] < 0.05, "h2b": adj[2] < 0.05})
    return out
