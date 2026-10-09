#!/usr/bin/env python3
"""SECONDARY (preregistered motivation): H1 / H-alt robustness on locked hazard table.

Does not modify confirmatory outputs. Item permutation, leave-one-item-out,
chain-cluster bootstrap of the crude HR, leave-one-config-out.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

LABEL = "SECONDARY (preregistered)"
MASTER_SEED = 20261004
HAZARD = Path("results/hazard_table_main_v1.csv.gz")
OUT = Path("results/secondary/h1_robustness.json")
FIG_LOIO = Path("results/figs/loio_hr.png")


def _h1_slice(h: pd.DataFrame) -> pd.DataFrame:
    return h[
        (h.protocol == "FORCED")
        & (h.condition == "SELF_REFLECT")
        & (h.category.isin(["COR", "AGENT"]))
        & (h.at_risk == 1)
    ].copy()


def crude_hr(d: pd.DataFrame) -> dict:
    cor = d[d.category == "COR"]
    ag = d[d.category == "AGENT"]
    e_c, r_c = int(cor.event_gpt54.sum()), int(len(cor))
    e_a, r_a = int(ag.event_gpt54.sum()), int(len(ag))
    hz_c = e_c / r_c if r_c else float("nan")
    hz_a = e_a / r_a if r_a else float("nan")
    hr = hz_c / hz_a if hz_a > 0 else float("nan")
    return {
        "n_cor_events": e_c,
        "n_agent_events": e_a,
        "n_cor_at_risk": r_c,
        "n_agent_at_risk": r_a,
        "hz_cor": hz_c,
        "hz_agent": hz_a,
        "crude_hr": hr,
    }


def chain_cluster_bootstrap(d: pd.DataFrame, n_reps: int = 2000, seed: int = MASTER_SEED) -> dict:
    """Resample chains (config::chain) with replacement; recompute crude HR."""
    rng = np.random.default_rng(seed)
    d = d.copy()
    d["chain_key"] = d["config"].astype(str) + "::" + d["chain"].astype(str)
    keys = d["chain_key"].unique()
    hrs = []
    for _ in range(n_reps):
        samp = rng.choice(keys, size=len(keys), replace=True)
        parts = [d[d.chain_key == k] for k in samp]
        boot = pd.concat(parts, ignore_index=True)
        hrs.append(crude_hr(boot)["crude_hr"])
    arr = np.asarray(hrs, dtype=float)
    arr = arr[np.isfinite(arr)]
    return {
        "n_reps": n_reps,
        "seed": seed,
        "crude_hr_point": crude_hr(d)["crude_hr"],
        "mean": float(arr.mean()),
        "ci_low": float(np.quantile(arr, 0.025)),
        "ci_high": float(np.quantile(arr, 0.975)),
        "n_finite": int(arr.size),
    }


def item_permutation(d: pd.DataFrame) -> dict:
    """Exact: choose which 5 of the 10 COR∪AGENT items are labelled COR (C(10,5)=252)."""
    items = sorted(d.item_id.unique())
    assert len(items) == 10, items
    obs = crude_hr(d)["crude_hr"]
    # Observed COR set
    true_cor = frozenset(d.loc[d.category == "COR", "item_id"].unique())
    more_extreme = 0  # one-sided: HR >= obs under H1 alternative greater
    # For H-alt / robustness of observed HR<1: one-sided p = P(HR_perm <= obs)
    le_obs = 0
    dist = []
    for combo in itertools.combinations(items, 5):
        cor_set = frozenset(combo)
        dd = d.copy()
        dd["category"] = np.where(dd.item_id.isin(cor_set), "COR", "AGENT")
        hr = crude_hr(dd)["crude_hr"]
        dist.append(hr)
        if hr <= obs + 1e-15:
            le_obs += 1
        if hr >= obs - 1e-15:
            more_extreme += 1
    n = len(dist)
    return {
        "n_permutations": n,
        "observed_crude_hr": obs,
        "true_cor_items": sorted(true_cor),
        "p_one_sided_le_obs": le_obs / n,  # matches lead "p=0.23" for HR as low as observed
        "p_one_sided_ge_obs": more_extreme / n,
        "perm_hr_mean": float(np.mean(dist)),
        "perm_hr_min": float(np.min(dist)),
        "perm_hr_max": float(np.max(dist)),
        "n_perm_hr_le_obs": le_obs,
    }


def leave_one_item_out(d: pd.DataFrame) -> dict:
    items = sorted(d.item_id.unique())
    out = {}
    for it in items:
        sub = d[d.item_id != it]
        row = crude_hr(sub)
        out[it] = row
    return out


def leave_one_config_out(d: pd.DataFrame) -> dict:
    out = {}
    for cfg in sorted(d.config.unique()):
        sub = d[d.config != cfg]
        out[cfg] = crude_hr(sub)
    return out


def _plot_loio(loio: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    # Prefer R if matplotlib missing — try both
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        # write csv for R
        rows = [{"item": k, **v} for k, v in loio.items()]
        pd.DataFrame(rows).to_csv(path.with_suffix(".csv"), index=False)
        return
    items = list(loio.keys())
    hrs = [loio[i]["crude_hr"] for i in items]
    colors = ["#c0392b" if i == "AGENT1" else "#34495e" for i in items]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(items, hrs, color=colors)
    ax.axhline(0.495, color="#2980b9", ls="--", lw=1, label="confirmatory HR 0.495")
    ax.axhline(1.0, color="gray", ls=":", lw=1)
    ax.set_ylabel("Crude HR (COR/AGENT)")
    ax.set_title("SECONDARY: leave-one-item-out crude HR")
    ax.legend(frameon=False)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    h = pd.read_csv(HAZARD)
    d = _h1_slice(h)
    point = crude_hr(d)
    boot = chain_cluster_bootstrap(d)
    perm = item_permutation(d)
    loio = leave_one_item_out(d)
    loco = leave_one_config_out(d)
    # Also model-free logistic HR via simple Mantel-style log rates CI not needed

    out = {
        "label": LABEL,
        "phase": "7E-C",
        "locked_hazard": str(HAZARD),
        "point_crude": point,
        "chain_cluster_bootstrap": boot,
        "item_permutation": perm,
        "leave_one_item_out": loio,
        "leave_one_config_out": loco,
        "notes": [
            "Crude HR = (e_COR/n_COR) / (e_AGENT/n_AGENT) on locked at-risk rows.",
            "Item permutation: all C(10,5)=252 assignments of COR label among COR∪AGENT items.",
            "One-sided p_one_sided_le_obs = fraction of permutations with crude HR <= observed (lead reported ≈0.23).",
            "Confirmatory model HR 0.495 is separate; this file does not re-run confirmatory GLMM.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    # plot via R for reliability
    rows = [{"item": k, **v} for k, v in loio.items()]
    csv_path = Path("results/figs/loio_hr.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(json.dumps({"wrote": str(OUT), "crude_hr": point["crude_hr"], "boot_ci": [boot["ci_low"], boot["ci_high"]], "perm_p": perm["p_one_sided_le_obs"], "loio_AGENT1": loio.get("AGENT1", {}).get("crude_hr")}, indent=2))


if __name__ == "__main__":
    main()
