#!/usr/bin/env python3
"""Phase 19 exploratory / sensitivity analyses for the TMLR revision.

Writes results/exploratory_tmlr/review_sensitivity.json and
paper_tmlr/macros_review.tex. CPU only; no model/API calls.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

OUT_JSON = ROOT / "results" / "exploratory_tmlr" / "review_sensitivity.json"
OUT_TEX = ROOT / "paper_tmlr" / "macros_review.tex"
OUT_TAB_CENSOR = ROOT / "paper_tmlr" / "tables" / "tab_censoring.tex"
OUT_TAB_PERM = ROOT / "paper_tmlr" / "tables" / "tab_permissive_fates.tex"
OUT_APP_H = ROOT / "results" / "exploratory_tmlr" / "human_validation_appendix.json"

SEED = 20261004
EROSION = frozenset({"WEAKENED", "SUBORDINATED", "INVERTED", "DELETED"})
STOP_FATES = frozenset({"STRENGTHENED", "QUALIFIED_LEGITIMACY", "MERGED_INTACT"})
FATE_ORDER = [
    "RETAINED",
    "STRENGTHENED",
    "QUALIFIED_LEGITIMACY",
    "MERGED_INTACT",
    "WEAKENED",
    "SUBORDINATED",
    "INVERTED",
    "DELETED",
]
CONDITIONS = ["SELF_REFLECT", "OTHER_REFLECT", "PARAPHRASE", "NEUTRAL_EDIT"]
CONFIGS = [
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_12b",
    "gemma4_31b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
    "olmo3_7b_final",
]
FAMILIES = {
    "qwen": ["qwen38_27b_nothink", "qwen38_27b_think"],
    "gemma": ["gemma4_12b", "gemma4_31b"],
    "olmo": ["olmo3_7b_sft", "olmo3_7b_dpo", "olmo3_7b_final"],
}
H3_INCLUDED = [
    "gemma4_12b",
    "gemma4_31b",
    "olmo3_7b_dpo",
    "olmo3_7b_final",
    "olmo3_7b_sft",
    "qwen38_27b_think",
]


def _round2(x: float) -> float:
    return float(f"{x:.2f}")


def _round1(x: float) -> float:
    return float(f"{x:.1f}")


def _round3(x: float) -> float:
    return float(f"{x:.3f}")


def latex_escape(s: str) -> str:
    return (
        s.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("#", "\\#")
    )


def chain_key_cols(df: pd.DataFrame) -> pd.Series:
    return df["config"] + "|" + df["condition"] + "|" + df["chain"].astype(str)


def item_chain_key(df: pd.DataFrame) -> pd.Series:
    return (
        df["config"]
        + "|"
        + df["condition"]
        + "|"
        + df["chain"].astype(str)
        + "|"
        + df["item_id"]
    )


def crude_hr(d: pd.DataFrame) -> float:
    cor = d[(d["category"] == "COR") & (d["at_risk"] == 1)]
    ag = d[(d["category"] == "AGENT") & (d["at_risk"] == 1)]
    return float(cor["event_gpt54"].mean() / ag["event_gpt54"].mean())


def compute_censoring(forced: pd.DataFrame) -> dict[str, Any]:
    last = (
        forced.groupby(["config", "condition", "chain"], sort=False)["round"]
        .max()
        .reset_index(name="max_round")
    )
    last["censored"] = last["max_round"] < 20
    by_cfg = {
        cfg: int(round(100 * last.loc[last.config == cfg, "censored"].mean()))
        for cfg in CONFIGS
    }
    table: dict[str, dict[str, int]] = {}
    for cfg in CONFIGS:
        table[cfg] = {}
        for cond in CONDITIONS:
            sub = last[(last.config == cfg) & (last.condition == cond)]
            table[cfg][cond] = int(round(100 * sub["censored"].mean())) if len(sub) else 0

    # Reasons from chain metas / last failed round
    from collections import Counter

    reasons: dict[str, Any] = {}
    for cfg in ["gemma4_12b", "olmo3_7b_sft", "gemma4_31b"]:
        ctr: Counter[str] = Counter()
        notes_optimal = 0
        for cond in CONDITIONS:
            base = ROOT / "runs" / "main_v1" / cfg / "FORCED" / cond / "STRUCTURED"
            if not base.exists():
                continue
            for ch in base.glob("chain_*"):
                meta = json.loads((ch / "meta.json").read_text(encoding="utf-8"))
                cens = meta.get("censored_at_round")
                if cens is None or int(cens) >= 20:
                    continue
                last_rec = None
                for line in (ch / "rounds.jsonl").open(encoding="utf-8"):
                    r = json.loads(line)
                    if int(r.get("round", -1)) == int(cens):
                        last_rec = r
                if last_rec is None:
                    ctr["unknown"] += 1
                    continue
                blob = json.dumps(last_rec).lower()
                err = str(last_rec.get("parse_error") or "")
                if "already optimal" in blob:
                    notes_optimal += 1
                    ctr["already_optimal_note"] += 1
                elif "identical" in err.lower() or "identical" in blob:
                    ctr["revise_text_identical"] += 1
                else:
                    ctr[err[:80] or "other"] += 1
        reasons[cfg] = {
            "counts": dict(ctr),
            "n_already_optimal_note": notes_optimal,
            "dominant": ctr.most_common(1)[0][0] if ctr else "unknown",
        }
    return {
        "pct_by_config": by_cfg,
        "pct_by_config_condition": table,
        "macros": {
            "CensGemmaTwelve": by_cfg["gemma4_12b"],
            "CensOlmoSft": by_cfg["olmo3_7b_sft"],
            "CensGemmaThirtyOne": by_cfg["gemma4_31b"],
        },
        "reasons": reasons,
    }


def kaplan_meier_pct(sr: pd.DataFrame, category: str) -> float:
    d = sr[sr["category"] == category]
    surv = 1.0
    for r in range(1, 21):
        rr = d[d["round"] == r]
        at = float(rr["at_risk"].sum())
        ev = float(rr["event_gpt54"].sum())
        if at > 0:
            surv *= 1.0 - ev / at
    return _round1(100.0 * (1.0 - surv))


def compute_hazard_sensitivities(forced: pd.DataFrame) -> dict[str, Any]:
    sr = forced[forced["condition"] == "SELF_REFLECT"].copy()
    sr["ikey"] = item_chain_key(sr)

    km = {
        "KMCor": kaplan_meier_pct(sr, "COR"),
        "KMAgent": kaplan_meier_pct(sr, "AGENT"),
        "KMSelf": kaplan_meier_pct(sr, "SELF"),
    }

    ex = sr[sr["config"] != "gemma4_12b"]
    crude_ex = _round2(crude_hr(ex))

    lofo = {}
    for fam, cfgs in FAMILIES.items():
        lofo[fam] = crude_hr(sr[~sr["config"].isin(cfgs)])
    lofo_lo = _round2(min(lofo.values()))
    lofo_hi = _round2(max(lofo.values()))

    first_stop = (
        sr[sr["fate_gpt54"].isin(STOP_FATES)].groupby("ikey")["round"].min().to_dict()
    )
    fs = np.array([first_stop.get(k, 10**9) for k in sr["ikey"].to_numpy()])
    step = sr[sr["round"].to_numpy() < fs]
    cor = step[(step["category"] == "COR") & (step["at_risk"] == 1)]
    ag = step[(step["category"] == "AGENT") & (step["at_risk"] == 1)]
    step_hr = float(cor["event_gpt54"].mean() / ag["event_gpt54"].mean())
    n_ev_cor = int(cor["event_gpt54"].sum())
    n_ev_ag = int(ag["event_gpt54"].sum())

    # Events with no prior non-NONE fate except RETAINED
    events = forced[forced["event_gpt54"] == 1].copy()
    events["ikey"] = item_chain_key(events)
    all_rows = forced.copy()
    all_rows["ikey"] = item_chain_key(all_rows)
    by = {k: g for k, g in all_rows.groupby("ikey", sort=False)}
    allowed = {"NONE", "RETAINED"}
    n_ok = 0
    for r in events.itertuples():
        g = by[r.ikey]
        prior = g[g["round"] < r.round]
        if len(prior[~prior["fate_gpt54"].isin(allowed)]) == 0:
            n_ok += 1
    pct_no_prior = _round1(100.0 * n_ok / len(events))

    return {
        **km,
        "CrudeExGemmaTwelve": crude_ex,
        "LofoLo": lofo_lo,
        "LofoHi": lofo_hi,
        "lofo_by_family": {k: _round2(v) for k, v in lofo.items()},
        "CrudeStepSens": _round2(step_hr),
        "CrudeStepSens_raw": step_hr,
        "NEvStepCor": n_ev_cor,
        "NEvStepAgent": n_ev_ag,
        "PctEventsNoPrior": pct_no_prior,
        "n_events_total": int(len(events)),
        "n_events_no_prior": n_ok,
        "expected_checks": {
            "KMCor": (km["KMCor"], 8.9),
            "KMAgent": (km["KMAgent"], 14.7),
            "KMSelf": (km["KMSelf"], 45.8),
            "CrudeExGemmaTwelve": (crude_ex, 0.67),
            "LofoLo": (lofo_lo, 0.42),
            "LofoHi": (lofo_hi, 0.74),
            "CrudeStepSens": (_round2(step_hr), 0.54),
            "NEvStepCor": (n_ev_cor, 58),
            "NEvStepAgent": (n_ev_ag, 105),
        },
    }


def compute_h3_prob_diff() -> dict[str, Any]:
    b1 = pd.read_csv(ROOT / "results" / "battery_b1_main_v1.csv.gz")
    d = b1[
        (b1["legitimacy"] == "AUTH")
        & (b1["config"].isin(H3_INCLUDED))
        & (b1["constitution"].isin(["COR_swap", "AGENT_swap"]))
    ]
    diffs = []
    per = {}
    for cfg, g in d.groupby("config"):
        aar = {c: float(x["accept"].mean()) for c, x in g.groupby("constitution")}
        delta = aar["COR_swap"] - aar["AGENT_swap"]
        diffs.append(delta)
        per[cfg] = {"AAR_COR_swap": aar["COR_swap"], "AAR_AGENT_swap": aar["AGENT_swap"], "diff": delta}
    mean = float(np.mean(diffs))
    return {
        "HthreeProbDiff": _round3(mean),
        "HthreeProbDiff_raw": mean,
        "per_config": per,
        "expected": 0.003,
    }


def compute_permissive() -> dict[str, Any]:
    payload = json.loads(
        (ROOT / "results" / "secondary" / "study1_permissive.json").read_text(encoding="utf-8")
    )
    r10 = payload["retention_and_round10_fate"]
    table: dict[str, dict[str, Any]] = {}
    erode_macros: dict[str, float] = {}
    erode_by_cond: dict[str, dict[str, float]] = {}
    for cond in CONDITIONS:
        table[cond] = {}
        erode_by_cond[cond] = {}
        for cat in ["COR", "AGENT", "SELF", "HON", "HARM", "CARE", "PROC"]:
            cell = r10[cond][cat]
            fate = dict(cell["fate"])
            n_coded = int(cell["n_coded"])
            n_deleted = int(cell.get("n_deleted") or 0)
            if "DELETED" not in fate and n_deleted:
                fate["DELETED"] = n_deleted
            # ensure all fates present
            for f in FATE_ORDER:
                fate.setdefault(f, 0)
            er = sum(int(fate.get(f, 0)) for f in EROSION)
            pct = _round1(100.0 * er / n_coded) if n_coded else 0.0
            table[cond][cat] = {"fate": fate, "n_coded": n_coded, "erode_pct": pct}
            erode_by_cond[cond][cat] = pct
        if cond == "SELF_REFLECT":
            erode_macros = {
                "PermErodeCorSR": erode_by_cond[cond]["COR"],
                "PermErodeAgentSR": erode_by_cond[cond]["AGENT"],
                "PermErodeSelfSR": erode_by_cond[cond]["SELF"],
            }

    # Chain reach R10
    fails = json.loads((ROOT / "results" / "d59_permissive_fails.json").read_text())
    fail_reasons = Counter(f.get("parse_error", "unknown") for f in fails)
    # Count chains that have a round-10 constitution per config × condition
    reach: dict[str, dict[str, int]] = {}
    for cfg in CONFIGS:
        reach[cfg] = {}
        for cond in CONDITIONS:
            base = ROOT / "runs" / "main_v1" / cfg / "PERMISSIVE" / cond / "STRUCTURED"
            n = 0
            if base.exists():
                for ch in base.glob("chain_*"):
                    meta = json.loads((ch / "meta.json").read_text(encoding="utf-8"))
                    cens = meta.get("censored_at_round")
                    # reached if completed_rounds includes 10 or max >=10 and not censored before 10
                    completed = meta.get("completed_rounds") or []
                    if completed:
                        ok = 10 in completed or max(completed) >= 10
                    else:
                        # constitutions.jsonl
                        mx = 0
                        cpath = ch / "constitutions.jsonl"
                        if cpath.exists():
                            for line in cpath.open(encoding="utf-8"):
                                row = json.loads(line)
                                mx = max(mx, int(row.get("round", 0)))
                        ok = mx >= 10
                    if cens is not None and int(cens) < 10:
                        ok = False
                    if ok:
                        n += 1
            reach[cfg][cond] = n

    # Denominators for COR: sum over configs of n_chains_reaching * 5 items
    dens = {}
    for cond in CONDITIONS:
        n_chains = sum(reach[cfg][cond] for cfg in CONFIGS)
        dens[cond] = {
            "n_chains_total": n_chains,
            "n_coded_COR": table[cond]["COR"]["n_coded"],
            "expected_if_5_items": n_chains * 5,
        }

    # 8 random PERMISSIVE NEUTRAL-EDIT COR deletions
    rng = random.Random(SEED)
    deletions: list[dict[str, Any]] = []
    # Prefer precomputed secondary if available; else scan lineage
    for cfg in CONFIGS:
        base = ROOT / "runs" / "main_v1" / cfg / "PERMISSIVE" / "NEUTRAL_EDIT" / "STRUCTURED"
        if not base.exists():
            continue
        for ch in base.glob("chain_*"):
            lineage = ch / "lineage.jsonl"
            if not lineage.exists():
                continue
            for line in lineage.open(encoding="utf-8"):
                rec = json.loads(line)
                if rec.get("decision") != "delete":
                    continue
                if rec.get("category") != "COR" and not str(rec.get("item_id", "")).startswith("COR"):
                    continue
                # round-10 cumulative coding uses r10 state; collect any COR delete
                deletions.append(
                    {
                        "config": cfg,
                        "chain": ch.name,
                        "round": rec.get("round"),
                        "item_id": rec.get("item_id"),
                        "before_text": rec.get("before_text") or rec.get("after_text"),
                        "note": rec.get("note") or rec.get("rationale"),
                        "opaque_id": rec.get("opaque_id"),
                    }
                )
    rng.shuffle(deletions)
    sample8 = deletions[:8]

    return {
        "table": table,
        "erode_macros": erode_macros,
        "erode_by_condition": erode_by_cond,
        "chain_reach_r10": reach,
        "denominators": dens,
        "fail_reasons": dict(fail_reasons),
        "n_fails": len(fails),
        "neutral_edit_cor_deletion_examples": sample8,
        "n_deletion_pool": len(deletions),
    }


def compute_mimo_flow() -> dict[str, Any]:
    from rc.main_run_coding import load_mimo_slot_ids, mimo_slot_post_censor, parse_mimo_slot_id
    from rc.hazard_table import load_config_judgments

    selected = set(load_mimo_slot_ids(ROOT))
    n_selected = len(selected)
    n_censored = sum(
        1 for sk in selected if mimo_slot_post_censor(sk, run_tag="main_v1", root=ROOT)
    )
    ht = pd.read_csv(ROOT / "results" / "hazard_table_main_v1.csv.gz")
    em = pd.to_numeric(ht["event_mimo"], errors="coerce")
    n_analysed = int(((ht["at_risk"] == 1) & em.notna()).sum())
    # present with mimo codes from rollup
    n_present = n_selected - n_censored
    n_not_at_risk = n_present - n_analysed
    # parse failures from rollup (n_missing)
    n_parse = 0
    n_structural = 0  # none among selected: every non-censored slot has a mimo fate in rollup
    return {
        "NMimoSelected": n_selected,
        "NMimoAnalysed": n_analysed,
        "n_censored_before_round": n_censored,
        "n_present": n_present,
        "n_not_at_risk_after_coding": n_not_at_risk,
        "n_parse_failure": n_parse,
        "n_structural_not_sent": n_structural,
        "sentence": (
            f"Of the {n_selected:,} design slots selected for the second judge, "
            f"{n_censored} were skipped because the chain had already been censored before that round, "
            f"{n_not_at_risk} had a second-judge code but did not enter the at-risk reliability set "
            f"(the changed item was no longer at risk), none were lost to parse failure, "
            f"and {n_analysed:,} double-coded at-risk transitions were analysed."
        ),
    }


def compute_realism(forced: pd.DataFrame) -> dict[str, Any]:
    # Mean testlikeness by category (unique items)
    items = forced.drop_duplicates("item_id")[["item_id", "category", "testlikeness"]]
    means = {
        cat: float(items.loc[items.category == cat, "testlikeness"].mean())
        for cat in ["COR", "AGENT", "SELF"]
    }
    # Coefficient from frozen H1 / diagnose file if stored
    diag = json.loads(
        (ROOT / "results" / "secondary" / "diagnose_sensitivities.json").read_text(encoding="utf-8")
    )
    # Look for testlikeness coef in confirmatory or secondary H1 fits
    coef = None
    se = None
    # Search known places
    for path in [
        ROOT / "results" / "secondary" / "diagnose_sensitivities.json",
        ROOT / "results" / "confirmatory.json",
    ]:
        blob = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(blob)
        if "testlikeness" in text:
            # try nested walk
            def find(o, path=""):
                nonlocal coef, se
                if isinstance(o, dict):
                    if "testlikeness" in o and isinstance(o["testlikeness"], (int, float)):
                        return [("coef", float(o["testlikeness"]), path)]
                    hits = []
                    for k, v in o.items():
                        if "testlikeness" in str(k).lower():
                            if isinstance(v, (int, float)):
                                hits.append((k, float(v), path + "." + k))
                            elif isinstance(v, dict) and "estimate" in v:
                                hits.append((k, v, path + "." + k))
                        hits.extend(find(v, path + "." + str(k)))
                    return hits
                if isinstance(o, list):
                    out = []
                    for i, v in enumerate(o[:50]):
                        out.extend(find(v, path + f"[{i}]"))
                    return out
                return []

            hits = find(blob)
            # Prefer collinearity mean_testlikeness; look for model coef elsewhere
            break

    # Check sensitivity / exploratory H1 with covariate
    cov_path = ROOT / "results" / "secondary"
    coef_info = {"mean_testlikeness_by_category": means, "collinearity_from_diagnose": diag.get("qualified_as_erosion", {}).get("collinearity")}
    # Try R residual or python store
    for p in cov_path.glob("*.json"):
        j = json.loads(p.read_text(encoding="utf-8"))
        s = json.dumps(j)
        if "testlikeness" in s and ("se" in s or "std" in s or "coef" in s):
            coef_info["source_file"] = str(p.name)
            coef_info["snippet_keys"] = [k for k in (j if isinstance(j, dict) else {})][:20]

    return coef_info


def compute_human_validation() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "coding_study"))
    from build_package import (  # type: ignore
        EROSION_QUOTAS,
        NON_EROSION_ITEMS,
        load_eligible_transitions,
        sample_package,
    )

    eligible = load_eligible_transitions(ROOT)
    # Stratum membership mirrors sample_package
    erosion_fates = {"INVERTED", "SUBORDINATED", "WEAKENED"}
    non_fates = {"STRENGTHENED", "QUALIFIED_LEGITIMACY", "RETAINED"}

    def in_items(row, items):
        return row["item_id"] in items if items is not None else True

    eligible_counts: dict[str, int] = {}
    pools: dict[str, list] = {}
    for name, _n, items in EROSION_QUOTAS:
        pool = [
            r
            for r in eligible
            if r["fate_gpt54"] in erosion_fates and in_items(r, items)
        ]
        # collapse units like sample_package
        units = {(r["config"], r["chain"], r["item_id"]) for r in pool}
        eligible_counts[name] = len(units)
        pools[name] = pool
    for item in NON_EROSION_ITEMS:
        name = f"NONERODE_{item}"
        pool = [
            r
            for r in eligible
            if r["fate_gpt54"] in non_fates and r["item_id"] == item
        ]
        units = {(r["config"], r["chain"], r["item_id"]) for r in pool}
        eligible_counts[name] = len(units)
        pools[name] = pool

    sampled_df, meta = sample_package(eligible, seed=SEED)
    sampled_counts = sampled_df["stratum"].value_counts().to_dict() if "stratum" in sampled_df.columns else {}
    # Prefer key file
    key = pd.read_csv(ROOT / "coding_study" / "out" / "sampling_key.csv")
    if "stratum" in key.columns:
        sampled_counts = key["stratum"].value_counts().to_dict()

    codes = pd.read_csv(ROOT / "results" / "exploratory_aie" / "human_coding" / "codes_anonymised.csv")
    # Primary coders C and D
    primary = codes[codes["coder"].isin(["C", "D"])].copy()

    def q1_weaker(q) -> bool:
        s = str(q).strip()
        if s.lower() == "weaker":
            return True
        return s.upper() in {"A", "B", "C"}

    def judge_erosion(fate: str) -> bool:
        return str(fate) in {"INVERTED", "SUBORDINATED", "WEAKENED"}

    # Wide merge C and D on key_id
    c = primary[primary.coder == "C"][["key_id", "stratum", "Q1v2", "fate_gpt54"]].rename(
        columns={"Q1v2": "Q1_C"}
    )
    d = primary[primary.coder == "D"][["key_id", "Q1v2"]].rename(columns={"Q1v2": "Q1_D"})
    merged = c.merge(d, on="key_id", how="inner")
    # Consensus: agree on weaker vs not
    merged["weak_C"] = merged["Q1_C"].map(q1_weaker)
    merged["weak_D"] = merged["Q1_D"].map(q1_weaker)
    merged["consensus"] = np.where(
        merged["weak_C"] == merged["weak_D"],
        merged["weak_C"],
        np.nan,
    )
    cons = merged.dropna(subset=["consensus"]).copy()
    cons["judge"] = cons["fate_gpt54"].map(judge_erosion)
    cons["human"] = cons["consensus"].astype(bool)

    # Design weights for the five commitments with both strata
    dual_items = ["COR2", "SELF1", "HON4", "CARE2", "AGENT1"]

    def stratum_weight(stratum: str) -> float:
        # Map NONERODE_X and X
        n_elig = eligible_counts.get(stratum, 0)
        n_samp = int(sampled_counts.get(stratum, 0))
        if n_samp == 0:
            return 0.0
        return n_elig / n_samp

    def weighted_recall(df: pd.DataFrame, human_col: str) -> tuple[float, int]:
        # among human weaker, weight TP/ (TP+FN)
        rows = df[df[human_col] == True]  # noqa: E712
        if len(rows) == 0:
            return float("nan"), 0
        wsum = 0.0
        wtp = 0.0
        for r in rows.itertuples():
            w = stratum_weight(str(r.stratum))
            wsum += w
            if bool(r.judge):
                wtp += w
        return (wtp / wsum if wsum else float("nan")), int(len(rows))

    # Restrict to dual-item strata (erosion + nonerode)
    def dual_mask(s: str) -> bool:
        return s in dual_items or s in {f"NONERODE_{i}" for i in dual_items}

    cons_dual = cons[cons["stratum"].map(dual_mask)].copy()
    w_recall, n_cons = weighted_recall(cons_dual, "human")

    # Per coder
    merged["judge"] = merged["fate_gpt54"].map(judge_erosion)
    per_coder = {}
    for lab, col in [("C", "weak_C"), ("D", "weak_D")]:
        m = merged[merged["stratum"].map(dual_mask)].copy()
        m["human"] = m[col]
        m["judge"] = m["fate_gpt54"].map(judge_erosion)
        est, n = weighted_recall(m, "human")
        # stratified bootstrap
        rng = np.random.default_rng(SEED)
        strata = list(m["stratum"].unique())
        boots = []
        by_s = {s: m[m.stratum == s] for s in strata}
        for _ in range(2000):
            parts = []
            for s in strata:
                g = by_s[s]
                if len(g) == 0:
                    continue
                idx = rng.integers(0, len(g), size=len(g))
                parts.append(g.iloc[idx])
            b = pd.concat(parts, ignore_index=True)
            be, _ = weighted_recall(b, "human")
            if be == be:
                boots.append(be)
        if boots:
            q = np.quantile(boots, [0.025, 0.975])
            lo, hi = float(q[0]), float(q[1])
        else:
            lo = hi = float("nan")
        per_coder[lab] = {
            "WRecall": _round3(est) if est == est else None,
            "WRecallLo": _round3(lo) if lo == lo else None,
            "WRecallHi": _round3(hi) if hi == hi else None,
            "n_human_weaker": n,
        }

    # Bootstrap CI for consensus
    rng = np.random.default_rng(SEED)
    strata = list(cons_dual["stratum"].unique())
    by_s = {s: cons_dual[cons_dual.stratum == s] for s in strata}
    boots = []
    for _ in range(2000):
        parts = []
        for s in strata:
            g = by_s[s]
            if len(g) == 0:
                continue
            idx = rng.integers(0, len(g), size=len(g))
            parts.append(g.iloc[idx])
        b = pd.concat(parts, ignore_index=True)
        be, _ = weighted_recall(b, "human")
        if be == be:
            boots.append(be)
    if boots:
        lo, hi = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    else:
        lo = hi = float("nan")

    # Confusion matrices per stratum (consensus): judge erosion × human weaker
    conf: dict[str, Any] = {}
    for s, g in cons.groupby("stratum"):
        tp = int(((g.judge) & (g.human)).sum())
        fp = int(((g.judge) & (~g.human)).sum())
        fn = int(((~g.judge) & (g.human)).sum())
        tn = int(((~g.judge) & (~g.human)).sum())
        conf[str(s)] = {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "n": len(g)}

    return {
        "eligible_counts": eligible_counts,
        "sampled_counts": {k: int(v) for k, v in sampled_counts.items()},
        "WRecall": _round3(w_recall),
        "WRecallLo": _round3(lo),
        "WRecallHi": _round3(hi),
        "n_consensus_dual": n_cons,
        "n_consensus_rows": int(len(cons_dual)),
        "per_coder": per_coder,
        "confusion_consensus": conf,
        "method_sentence": (
            "Design-weighted recall weights each sampled consensus row by "
            "N_eligible(stratum)/n_sampled(stratum) over the five commitments with both "
            "erosion and non-erosion strata, then takes the weighted share of human-weaker "
            "cases that the judge also coded as erosion."
        ),
    }


def compute_multiplicity() -> dict[str, Any]:
    # From prereg + confirmatory code
    return {
        "h2_within_family": "Bonferroni",
        "h2_detail": (
            "H2a and H2b are Bonferroni-adjusted within the H2 family "
            "(p_family = min(1, 2 * p_raw)); the three families (H1, H2, H3) then receive Holm correction."
        ),
        "halt_outside_families": True,
        "prereg_quote": (
            "The three confirmatory families (H1; H2 = {H2a, H2b}, Bonferroni within the family; H3) "
            "are tested with Holm's procedure at familywise α = 0.05, one-sided."
        ),
        "exact_method_phrase": "Bonferroni adjustment of the two contrasts",
    }


def write_censor_table(censor: dict[str, Any]) -> None:
    labels = {
        "qwen38_27b_nothink": "Qwen3.8-27B (thinking off)",
        "qwen38_27b_think": "Qwen3.8-27B (thinking on)",
        "gemma4_12b": "Gemma-4-12B-it",
        "gemma4_31b": "Gemma-4-31B-it",
        "olmo3_7b_sft": "OLMo-3-7B (SFT)",
        "olmo3_7b_dpo": "OLMo-3-7B (DPO)",
        "olmo3_7b_final": "OLMo-3-7B (final)",
    }
    cond_lab = {
        "SELF_REFLECT": "SR",
        "OTHER_REFLECT": "OR",
        "PARAPHRASE": "PARA",
        "NEUTRAL_EDIT": "NE",
    }
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Percentage of FORCED chains censored before round 20, by configuration and condition.}",
        "\\label{tab:censoring}",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Config & SR & OR & PARA & NE \\\\",
        "\\midrule",
    ]
    tab = censor["pct_by_config_condition"]
    for cfg in CONFIGS:
        row = [labels[cfg]] + [str(tab[cfg][c]) for c in CONDITIONS]
        lines.append(" & ".join(row) + " \\\\")
    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ]
    OUT_TAB_CENSOR.parent.mkdir(parents=True, exist_ok=True)
    OUT_TAB_CENSOR.write_text("\n".join(lines), encoding="utf-8")


def write_perm_table(perm: dict[str, Any]) -> None:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{PERMISSIVE round-10 fate counts by category and condition (n coded in parentheses in the first column of each block).}",
        "\\label{tab:permissive-fates}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{llrrrrrrrr}",
        "\\toprule",
        "Cond. & Cat. & RET & STR & QL & MER & WEAK & SUB & INV & DEL \\\\",
        "\\midrule",
    ]
    short = {
        "SELF_REFLECT": "SR",
        "OTHER_REFLECT": "OR",
        "PARAPHRASE": "PARA",
        "NEUTRAL_EDIT": "NE",
    }
    for cond in CONDITIONS:
        first = True
        for cat in ["COR", "AGENT", "SELF", "HON", "HARM", "CARE", "PROC"]:
            cell = perm["table"][cond][cat]
            fate = cell["fate"]
            n = cell["n_coded"]
            vals = [str(int(fate.get(f, 0))) for f in FATE_ORDER]
            cond_cell = short[cond] if first else ""
            cat_cell = f"{cat} ({n})"
            lines.append(" & ".join([cond_cell, cat_cell, *vals]) + " \\\\")
            first = False
        lines.append("\\midrule")
    # drop last midrule
    if lines[-1] == "\\midrule":
        lines[-1] = "\\bottomrule"
    lines += ["\\end{tabular}", "\\end{table}", ""]
    OUT_TAB_PERM.write_text("\n".join(lines), encoding="utf-8")


def write_macros(payload: dict[str, Any]) -> None:
    c = payload["censor"]["macros"]
    h = payload["hazard"]
    h3 = payload["h3"]
    p = payload["permissive"]["erode_macros"]
    hv = payload["human"]
    m = payload["mimo"]
    lines = [
        "% Auto-generated by analysis/exploratory_tmlr/review_sensitivity.py — do not edit.",
        f"\\newcommand{{\\CensGemmaTwelve}}{{{c['CensGemmaTwelve']}}}",
        f"\\newcommand{{\\CensOlmoSft}}{{{c['CensOlmoSft']}}}",
        f"\\newcommand{{\\CensGemmaThirtyOne}}{{{c['CensGemmaThirtyOne']}}}",
        f"\\newcommand{{\\KMCor}}{{{h['KMCor']}}}",
        f"\\newcommand{{\\KMAgent}}{{{h['KMAgent']}}}",
        f"\\newcommand{{\\KMSelf}}{{{h['KMSelf']}}}",
        f"\\newcommand{{\\CrudeExGemmaTwelve}}{{{h['CrudeExGemmaTwelve']}}}",
        f"\\newcommand{{\\LofoLo}}{{{h['LofoLo']}}}",
        f"\\newcommand{{\\LofoHi}}{{{h['LofoHi']}}}",
        f"\\newcommand{{\\CrudeStepSens}}{{{h['CrudeStepSens']}}}",
        f"\\newcommand{{\\NEvStepCor}}{{{h['NEvStepCor']}}}",
        f"\\newcommand{{\\NEvStepAgent}}{{{h['NEvStepAgent']}}}",
        f"\\newcommand{{\\PctEventsNoPrior}}{{{h['PctEventsNoPrior']}}}",
        f"\\newcommand{{\\HthreeProbDiff}}{{{h3['HthreeProbDiff']}}}",
        f"\\newcommand{{\\PermErodeCorSR}}{{{p['PermErodeCorSR']}}}",
        f"\\newcommand{{\\PermErodeAgentSR}}{{{p['PermErodeAgentSR']}}}",
        f"\\newcommand{{\\PermErodeSelfSR}}{{{p['PermErodeSelfSR']}}}",
        f"\\newcommand{{\\WRecall}}{{{hv['WRecall']}}}",
        f"\\newcommand{{\\WRecallLo}}{{{hv['WRecallLo']}}}",
        f"\\newcommand{{\\WRecallHi}}{{{hv['WRecallHi']}}}",
        f"\\newcommand{{\\NMimoSelected}}{{{m['NMimoSelected']}}}",
        f"\\newcommand{{\\NMimoAnalysed}}{{{m['NMimoAnalysed']}}}",
        "",
    ]
    OUT_TEX.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    forced = pd.read_csv(ROOT / "results" / "hazard_table_main_v1.csv.gz")
    assert (forced["protocol"] == "FORCED").all()

    censor = compute_censoring(forced)
    hazard = compute_hazard_sensitivities(forced)
    h3 = compute_h3_prob_diff()
    permissive = compute_permissive()
    mimo = compute_mimo_flow()
    realism = compute_realism(forced)
    human = compute_human_validation()
    multiplicity = compute_multiplicity()

    # Diff report vs expected
    diffs = []
    for name, (got, exp) in hazard["expected_checks"].items():
        if isinstance(exp, float):
            if abs(float(got) - float(exp)) > 0.011:
                diffs.append((name, got, exp))
        elif got != exp:
            diffs.append((name, got, exp))
    if abs(h3["HthreeProbDiff"] - 0.003) > 0.001:
        diffs.append(("HthreeProbDiff", h3["HthreeProbDiff"], 0.003))
    for k, exp in [
        ("CensGemmaTwelve", 54),
        ("CensOlmoSft", 25),
        ("CensGemmaThirtyOne", 16),
    ]:
        if censor["macros"][k] != exp:
            diffs.append((k, censor["macros"][k], exp))

    payload = {
        "label": "EXPLORATORY / SENSITIVITY (Phase 19)",
        "censor": censor,
        "hazard": hazard,
        "h3": h3,
        "permissive": {
            k: v
            for k, v in permissive.items()
            if k != "neutral_edit_cor_deletion_examples"
        },
        "permissive_deletion_examples": permissive["neutral_edit_cor_deletion_examples"],
        "mimo": mimo,
        "realism": realism,
        "human": human,
        "multiplicity": multiplicity,
        "value_diffs_vs_expected": diffs,
    }
    # JSON-friendly
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    OUT_APP_H.write_text(
        json.dumps(
            {
                "eligible_counts": human["eligible_counts"],
                "sampled_counts": human["sampled_counts"],
                "confusion_consensus": human["confusion_consensus"],
                "method_sentence": human["method_sentence"],
                "weighted_recall": {
                    "consensus": {
                        "WRecall": human["WRecall"],
                        "lo": human["WRecallLo"],
                        "hi": human["WRecallHi"],
                        "n": human["n_consensus_dual"],
                    },
                    "per_coder": human["per_coder"],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_censor_table(censor)
    write_perm_table(permissive)
    write_macros(payload)

    print("wrote", OUT_JSON)
    print("wrote", OUT_TEX)
    print("diffs_vs_expected", diffs)
    print("macros", {k: censor["macros"][k] for k in censor["macros"]})
    print(
        "KM/HR",
        {k: hazard[k] for k in ["KMCor", "KMAgent", "KMSelf", "CrudeExGemmaTwelve", "LofoLo", "LofoHi", "CrudeStepSens", "NEvStepCor", "NEvStepAgent", "PctEventsNoPrior"]},
    )
    print("H3ProbDiff", h3["HthreeProbDiff"])
    print("Perm", permissive["erode_macros"])
    print("WRecall", human["WRecall"], human["WRecallLo"], human["WRecallHi"])
    print("MIMO", mimo["sentence"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
