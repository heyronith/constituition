#!/usr/bin/env python3
"""Generate paper/numbers.tex and paper/MACROS.md from locked results (no hand-typed numbers)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_TEX = ROOT / "paper" / "numbers.tex"
OUT_MD = ROOT / "paper" / "MACROS.md"
OUT_JSON = ROOT / "paper" / "numbers_manifest.json"


@dataclass(frozen=True)
class Macro:
    name: str
    value: str
    source: str
    key: str


def _fmt(x: float, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and (x != x)):
        return "NA"
    if abs(x) >= 100 or (abs(x) >= 1 and digits <= 2):
        return f"{x:.{max(0, digits - 1)}f}".rstrip("0").rstrip(".") if digits else str(int(round(x)))
    return f"{x:.{digits}f}"


def _sci_p(p: float) -> str:
    if p < 1e-4:
        # LaTeX-friendly scientific
        s = f"{p:.2e}".replace("e-0", "e-").replace("e+", "e")
        mant, exp = s.split("e")
        return rf"{mant}\!\times\!10^{{{int(exp)}}}"
    return _fmt(p, 4)


def compute() -> list[Macro]:
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    rob = json.loads((ROOT / "results/secondary/h1_robustness.json").read_text())
    ia = json.loads((ROOT / "results/secondary/h1_item_aware.json").read_text())
    desc = (ROOT / "results/descriptives_main_v1.md").read_text()
    sim = json.loads((ROOT / "results/phase6_sims/summary.json").read_text())
    eval_aware = json.loads((ROOT / "results/eval_awareness_main_v1.json").read_text()) if (
        ROOT / "results/eval_awareness_main_v1.json"
    ).exists() else {}

    h1 = conf["hypotheses"]["H1"]
    h2a = conf["hypotheses"]["H2"]["H2a"]
    h2b = conf["hypotheses"]["H2"]["H2b"]
    h3 = conf["hypotheses"]["H3"]
    rel = conf["reliability"]
    tost = conf["tost"]

    h = pd.read_csv(ROOT / "results/hazard_table_main_v1.csv.gz")
    n_events = int(h.event_gpt54.sum())
    n_itemrounds = int(len(h))
    n_chains = int(h.groupby(["config", "condition", "chain"]).ngroups)

    # Cumulative erosion rates from descriptives (parse table)
    def cum(cond: str, cat: str) -> float:
        # | SELF_REFLECT | SELF | 875 | 381 | 0.4354 |
        m = re.search(
            rf"\| {re.escape(cond)} \| {re.escape(cat)} \| \d+ \| \d+ \| ([0-9.]+) \|",
            desc,
        )
        if not m:
            raise RuntimeError(f"missing cum prop {cond} {cat}")
        return float(m.group(1))

    self_sr = cum("SELF_REFLECT", "SELF")
    self_ne = cum("NEUTRAL_EDIT", "SELF")
    cor_sr = cum("SELF_REFLECT", "COR")
    agent_sr = cum("SELF_REFLECT", "AGENT")

    # Item-aware HR range (successful fits)
    hrs = []
    for key in ("glm_item_cluster_bootstrap", "gee_item", "glmmTMB"):
        row = ia.get(key) or {}
        if row.get("ok") and row.get("hr") is not None:
            hrs.append(float(row["hr"]))
    for row in (ia.get("lme4_optimizers") or {}).values():
        if row.get("ok") and row.get("hr") is not None:
            hrs.append(float(row["hr"]))
    if (ia.get("brms") or {}).get("ok") and ia["brms"].get("hr") is not None:
        hrs.append(float(ia["brms"]["hr"]))

    eval_n = eval_aware.get("n_flagged_chains")
    if eval_n is None:
        # fallback from hazard
        eval_n = int(
            h[h.eval_aware_flag == 1]
            .groupby(["config", "condition", "chain"])
            .ngroups
        )

    type_i = float(sim["scenarios"]["S0"]["h1_reject_rate"])
    power_s = float(sim["power_S1"])

    macros = [
        Macro("HoneHR", _fmt(h1["hr"]), "results/confirmatory.json", "hypotheses.H1.hr"),
        Macro("HoneLo", _fmt(h1["ci_low"]), "results/confirmatory.json", "hypotheses.H1.ci_low"),
        Macro("HoneHi", _fmt(h1["ci_high"]), "results/confirmatory.json", "hypotheses.H1.ci_high"),
        Macro("HaltP", _sci_p(tost["p_halt_lt_1"]), "results/confirmatory.json", "tost.p_halt_lt_1"),
        Macro("Alpha", _fmt(rel["alpha"]), "results/confirmatory.json", "reliability.alpha"),
        Macro("AlphaLo", _fmt(rel["ci_low"]), "results/confirmatory.json", "reliability.ci_low"),
        Macro("AlphaHi", _fmt(rel["ci_high"]), "results/confirmatory.json", "reliability.ci_high"),
        Macro("Nevents", f"{n_events}", "results/hazard_table_main_v1.csv.gz", "sum(event_gpt54)"),
        Macro("Nitemrounds", f"{n_itemrounds}", "results/hazard_table_main_v1.csv.gz", "nrow"),
        Macro("Nchains", f"{n_chains}", "results/hazard_table_main_v1.csv.gz", "nunique(config,condition,chain)"),
        Macro("SelfErodedSR", _fmt(self_sr, 3), "results/descriptives_main_v1.md", "KM SELF SELF_REFLECT cum_prop_r20"),
        Macro("SelfErodedNE", _fmt(self_ne, 3), "results/descriptives_main_v1.md", "KM SELF NEUTRAL_EDIT cum_prop_r20"),
        Macro("CorErodedSR", _fmt(cor_sr, 3), "results/descriptives_main_v1.md", "KM COR SELF_REFLECT cum_prop_r20"),
        Macro("AgentErodedSR", _fmt(agent_sr, 3), "results/descriptives_main_v1.md", "KM AGENT SELF_REFLECT cum_prop_r20"),
        Macro("HtwoaGap", _fmt(h2a["log_hr_gap"]), "results/confirmatory.json", "hypotheses.H2.H2a.log_hr_gap"),
        Macro("HtwoaLo", _fmt(h2a["ci_low"]), "results/confirmatory.json", "hypotheses.H2.H2a.ci_low"),
        Macro("HtwoaHi", _fmt(h2a["ci_high"]), "results/confirmatory.json", "hypotheses.H2.H2a.ci_high"),
        Macro("HtwobGap", _fmt(h2b["log_hr_gap"]), "results/confirmatory.json", "hypotheses.H2.H2b.log_hr_gap"),
        Macro("HtwobLo", _fmt(h2b["ci_low"]), "results/confirmatory.json", "hypotheses.H2.H2b.ci_low"),
        Macro("HtwobHi", _fmt(h2b["ci_high"]), "results/confirmatory.json", "hypotheses.H2.H2b.ci_high"),
        Macro("HthreeEst", _fmt(h3["estimate"]), "results/confirmatory.json", "hypotheses.H3.estimate"),
        Macro("HthreeLo", _fmt(h3["ci_low"]), "results/confirmatory.json", "hypotheses.H3.ci_low"),
        Macro("HthreeHi", _fmt(h3["ci_high"]), "results/confirmatory.json", "hypotheses.H3.ci_high"),
        Macro(
            "LOIOagentOne",
            _fmt(rob["leave_one_item_out"]["AGENT1"]["crude_hr"]),
            "results/secondary/h1_robustness.json",
            "leave_one_item_out.AGENT1.crude_hr",
        ),
        Macro(
            "PermP",
            _fmt(rob["item_permutation"]["p_one_sided_le_obs"], 3),
            "results/secondary/h1_robustness.json",
            "item_permutation.p_one_sided_le_obs",
        ),
        Macro(
            "BootLo",
            _fmt(rob["chain_cluster_bootstrap"]["ci_low"]),
            "results/secondary/h1_robustness.json",
            "chain_cluster_bootstrap.ci_low",
        ),
        Macro(
            "BootHi",
            _fmt(rob["chain_cluster_bootstrap"]["ci_high"]),
            "results/secondary/h1_robustness.json",
            "chain_cluster_bootstrap.ci_high",
        ),
        Macro("ItemAwareMin", _fmt(min(hrs)), "results/secondary/h1_item_aware.json", "min(successful HR)"),
        Macro("ItemAwareMax", _fmt(max(hrs)), "results/secondary/h1_item_aware.json", "max(successful HR)"),
        Macro("EvalAwareChains", f"{int(eval_n)}", "results/eval_awareness_main_v1.json|hazard", "n_flagged_chains"),
        Macro("TypeI", _fmt(type_i, 2), "results/phase6_sims/summary.json", "scenarios.S0.h1_reject_rate"),
        Macro("PowerS", _fmt(power_s, 2), "results/phase6_sims/summary.json", "power_S1"),
        # extras used in tables
        Macro("HoneNevents", f"{int(h1['n_events'])}", "results/confirmatory.json", "hypotheses.H1.n_events"),
        Macro("HonePraw", _fmt(h1["p_raw"], 4), "results/confirmatory.json", "hypotheses.H1.p_raw"),
        Macro("HoneMethod", str(h1["method"]).replace("_", r"\_"), "results/confirmatory.json", "hypotheses.H1.method"),
        Macro("CrudeHR", _fmt(rob["point_crude"]["crude_hr"]), "results/secondary/h1_robustness.json", "point_crude.crude_hr"),
    ]
    return macros


def write(macros: list[Macro]) -> None:
    OUT_TEX.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by scripts/paper_numbers.py — do not edit by hand.",
        "% Re-run: uv run python scripts/paper_numbers.py",
        "",
    ]
    for m in macros:
        # Protect special chars already handled for method
        lines.append(f"\\newcommand{{\\{m.name}}}{{{m.value}}}")
    OUT_TEX.write_text("\n".join(lines) + "\n")

    md = [
        "# Number macros (`paper/numbers.tex`)",
        "",
        "Generated by `scripts/paper_numbers.py`. Do not hand-edit values.",
        "",
        "| Macro | Value | Source file | Key |",
        "|---|---|---|---|",
    ]
    for m in macros:
        md.append(f"| `\\{m.name}` | `{m.value}` | `{m.source}` | `{m.key}` |")
    OUT_MD.write_text("\n".join(md) + "\n")

    OUT_JSON.write_text(
        json.dumps(
            [{"name": m.name, "value": m.value, "source": m.source, "key": m.key} for m in macros],
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {OUT_TEX} ({len(macros)} macros)")
    print(f"Wrote {OUT_MD}")


def main() -> None:
    write(compute())


if __name__ == "__main__":
    main()
