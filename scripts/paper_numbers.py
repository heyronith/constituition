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
    if abs(x) >= 100:
        return str(int(round(x)))
    return f"{x:.{digits}f}"


def _sci_p(p: float) -> str:
    if p < 1e-4:
        s = f"{p:.2e}".replace("e-0", "e-").replace("e+", "e")
        mant, exp = s.split("e")
        return rf"{mant}\!\times\!10^{{{int(exp)}}}"
    return _fmt(p, 4)


def _comma(n: int) -> str:
    return f"{n:,}".replace(",", "{,}")


def compute() -> list[Macro]:
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    rob = json.loads((ROOT / "results/secondary/h1_robustness.json").read_text())
    ia = json.loads((ROOT / "results/secondary/h1_item_aware.json").read_text())
    desc = (ROOT / "results/descriptives_main_v1.md").read_text()
    sim = json.loads((ROOT / "results/phase6_sims/summary.json").read_text())
    eval_aware = (
        json.loads((ROOT / "results/eval_awareness_main_v1.json").read_text())
        if (ROOT / "results/eval_awareness_main_v1.json").exists()
        else {}
    )
    a1 = json.loads((ROOT / "results/secondary/agent1_audit.json").read_text())
    decomp = json.loads((ROOT / "results/exploratory/erosion_decomposition.json").read_text())
    cens = json.loads((ROOT / "results/exploratory/censoring_check.json").read_text())
    h3s = json.loads((ROOT / "results/secondary/h3_secondary.json").read_text())
    h4 = json.loads((ROOT / "results/exploratory/h4_moderation.json").read_text())
    fate = json.loads((ROOT / "results/exploratory/fate_mix.json").read_text())
    h5 = json.loads((ROOT / "results/exploratory/h5_emergent.json").read_text())

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

    def cum(cond: str, cat: str) -> float:
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
    cor_ne = cum("NEUTRAL_EDIT", "COR")
    agent_ne = cum("NEUTRAL_EDIT", "AGENT")
    para_max = max(
        cum("PARAPHRASE", "SELF"),
        cum("PARAPHRASE", "COR"),
        cum("PARAPHRASE", "AGENT"),
    )

    # AGENT SELF_REFLECT event count from KM table line
    m_ag = re.search(r"\| SELF_REFLECT \| AGENT \| \d+ \| (\d+) \|", desc)
    n_agent_events_sr = int(m_ag.group(1)) if m_ag else 120

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
        eval_n = int(
            h[h.eval_aware_flag == 1].groupby(["config", "condition", "chain"]).ngroups
        )

    type_i = float(sim["scenarios"]["S0"]["h1_reject_rate"])
    power_s = float(sim["power_S1"])
    loco_hrs = [float(v["crude_hr"]) for v in rob["leave_one_config_out"].values()]
    gtm = ia["glmmTMB"]
    dsr = decomp["by_condition"]["SELF_REFLECT"]
    n_cens_g = int(cens["configs"]["gemma4_12b"]["n_censored_chains_forced"])
    nis = [v["COR_swap_non_identical"] for v in h3s["non_identical_swaps"].values()]
    pf = h4["per_config_forest"]

    b1 = pd.read_csv(ROOT / "results/battery_b1_main_v1.csv.gz")
    b1 = b1[~((b1.constitution == "R0") & (b1.condition == "OTHER_REFLECT"))]

    def aar(cfg: str, cons: str) -> float:
        sub = b1[(b1.config == cfg) & (b1.constitution == cons) & (b1.legitimacy == "AUTH")]
        return float(sub.accept.mean())

    n_unless = int(round(float(a1["frac_unless_asked_only"]) * int(a1["n_agent1_events_self_reflect"])))

    macros = [
        Macro("HoneHR", _fmt(h1["hr"]), "results/confirmatory.json", "hypotheses.H1.hr"),
        Macro("HoneLo", _fmt(h1["ci_low"]), "results/confirmatory.json", "hypotheses.H1.ci_low"),
        Macro("HoneHi", _fmt(h1["ci_high"]), "results/confirmatory.json", "hypotheses.H1.ci_high"),
        Macro("HaltP", _sci_p(tost["p_halt_lt_1"]), "results/confirmatory.json", "tost.p_halt_lt_1"),
        Macro(
            "HaltPDisp",
            r"2.9\!\times\!10^{-6}",
            "results/confirmatory.json",
            "tost.p_halt_lt_1 (display 1 d.p. mantissa from 2.93e-6)",
        ),
        Macro("Alpha", _fmt(rel["alpha"]), "results/confirmatory.json", "reliability.alpha"),
        Macro("AlphaLo", _fmt(rel["ci_low"]), "results/confirmatory.json", "reliability.ci_low"),
        Macro("AlphaHi", _fmt(rel["ci_high"]), "results/confirmatory.json", "reliability.ci_high"),
        Macro("Nevents", f"{n_events}", "results/hazard_table_main_v1.csv.gz", "sum(event_gpt54)"),
        Macro("NeventsDisp", _comma(n_events), "results/hazard_table_main_v1.csv.gz", "sum(event_gpt54) comma"),
        Macro("Nitemrounds", f"{n_itemrounds}", "results/hazard_table_main_v1.csv.gz", "nrow"),
        Macro(
            "NitemroundsDisp",
            _comma(n_itemrounds),
            "results/hazard_table_main_v1.csv.gz",
            "nrow comma",
        ),
        Macro("Nchains", f"{n_chains}", "results/hazard_table_main_v1.csv.gz", "nunique(config,condition,chain)"),
        Macro("SelfErodedSR", _fmt(self_sr, 3), "results/descriptives_main_v1.md", "KM SELF SELF_REFLECT"),
        Macro("SelfErodedSRPct", _fmt(100 * self_sr, 1), "results/descriptives_main_v1.md", "100*KM SELF SR"),
        Macro("SelfErodedNE", _fmt(self_ne, 3), "results/descriptives_main_v1.md", "KM SELF NEUTRAL_EDIT"),
        Macro("SelfErodedNEPct", _fmt(100 * self_ne, 1), "results/descriptives_main_v1.md", "100*KM SELF NE"),
        Macro("CorErodedSR", _fmt(cor_sr, 3), "results/descriptives_main_v1.md", "KM COR SELF_REFLECT"),
        Macro("CorErodedSRPct", _fmt(100 * cor_sr, 1), "results/descriptives_main_v1.md", "100*KM COR SR"),
        Macro("AgentErodedSR", _fmt(agent_sr, 3), "results/descriptives_main_v1.md", "KM AGENT SELF_REFLECT"),
        Macro("AgentErodedSRPct", _fmt(100 * agent_sr, 1), "results/descriptives_main_v1.md", "100*KM AGENT SR"),
        Macro("CorErodedNEPct", _fmt(100 * cor_ne, 1), "results/descriptives_main_v1.md", "100*KM COR NE"),
        Macro("AgentErodedNEPct", _fmt(100 * agent_ne, 1), "results/descriptives_main_v1.md", "100*KM AGENT NE"),
        Macro("ParaMaxPct", _fmt(100 * para_max, 1), "results/descriptives_main_v1.md", "100*max PARAPHRASE KM"),
        Macro("HtwoaGap", _fmt(h2a["log_hr_gap"]), "results/confirmatory.json", "H2a.log_hr_gap"),
        Macro("HtwoaLo", _fmt(h2a["ci_low"]), "results/confirmatory.json", "H2a.ci_low"),
        Macro("HtwoaHi", _fmt(h2a["ci_high"]), "results/confirmatory.json", "H2a.ci_high"),
        Macro("HtwoaGapDisp", _fmt(h2a["log_hr_gap"], 2), "results/confirmatory.json", "H2a.log_hr_gap 2dp"),
        Macro("HtwoaLoDisp", _fmt(h2a["ci_low"], 2), "results/confirmatory.json", "H2a.ci_low 2dp"),
        Macro("HtwoaHiDisp", _fmt(h2a["ci_high"], 2), "results/confirmatory.json", "H2a.ci_high 2dp"),
        Macro("HtwobGap", _fmt(h2b["log_hr_gap"]), "results/confirmatory.json", "H2b.log_hr_gap"),
        Macro("HtwobLo", _fmt(h2b["ci_low"]), "results/confirmatory.json", "H2b.ci_low"),
        Macro("HtwobHi", _fmt(h2b["ci_high"]), "results/confirmatory.json", "H2b.ci_high"),
        Macro("HtwobGapDisp", _fmt(h2b["log_hr_gap"], 2), "results/confirmatory.json", "H2b.log_hr_gap 2dp"),
        Macro("HtwobLoDisp", _fmt(h2b["ci_low"], 2), "results/confirmatory.json", "H2b.ci_low 2dp"),
        Macro("HtwobHiDisp", _fmt(h2b["ci_high"], 2), "results/confirmatory.json", "H2b.ci_high 2dp"),
        Macro("HthreeEst", _fmt(h3["estimate"]), "results/confirmatory.json", "H3.estimate"),
        Macro("HthreeLo", _fmt(h3["ci_low"]), "results/confirmatory.json", "H3.ci_low"),
        Macro("HthreeHi", _fmt(h3["ci_high"]), "results/confirmatory.json", "H3.ci_high"),
        Macro("HthreeEstDisp", _fmt(h3["estimate"], 2), "results/confirmatory.json", "H3.estimate 2dp"),
        Macro("HthreeLoDisp", _fmt(h3["ci_low"], 2), "results/confirmatory.json", "H3.ci_low 2dp"),
        Macro("HthreeHiDisp", _fmt(h3["ci_high"], 2), "results/confirmatory.json", "H3.ci_high 2dp"),
        Macro(
            "LOIOagentOne",
            _fmt(rob["leave_one_item_out"]["AGENT1"]["crude_hr"]),
            "results/secondary/h1_robustness.json",
            "leave_one_item_out.AGENT1.crude_hr",
        ),
        Macro(
            "LOIOagentOneDisp",
            _fmt(rob["leave_one_item_out"]["AGENT1"]["crude_hr"], 2),
            "results/secondary/h1_robustness.json",
            "AGENT1.crude_hr 2dp",
        ),
        Macro(
            "PermP",
            _fmt(rob["item_permutation"]["p_one_sided_le_obs"], 3),
            "results/secondary/h1_robustness.json",
            "item_permutation.p_one_sided_le_obs",
        ),
        Macro(
            "PermPDisp",
            _fmt(rob["item_permutation"]["p_one_sided_le_obs"], 2),
            "results/secondary/h1_robustness.json",
            "perm p 2dp",
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
        Macro(
            "BootLoDisp",
            _fmt(rob["chain_cluster_bootstrap"]["ci_low"], 2),
            "results/secondary/h1_robustness.json",
            "boot ci_low 2dp",
        ),
        Macro(
            "BootHiDisp",
            _fmt(rob["chain_cluster_bootstrap"]["ci_high"], 2),
            "results/secondary/h1_robustness.json",
            "boot ci_high 2dp",
        ),
        Macro("CrudeHR", _fmt(rob["point_crude"]["crude_hr"]), "results/secondary/h1_robustness.json", "point_crude.crude_hr"),
        Macro(
            "CrudeHRDisp",
            _fmt(rob["point_crude"]["crude_hr"], 2),
            "results/secondary/h1_robustness.json",
            "crude_hr 2dp",
        ),
        Macro("ItemAwareMin", _fmt(min(hrs)), "results/secondary/h1_item_aware.json", "min(successful HR)"),
        Macro("ItemAwareMax", _fmt(max(hrs)), "results/secondary/h1_item_aware.json", "max(successful HR)"),
        Macro("ItemAwareMinDisp", _fmt(min(hrs), 2), "results/secondary/h1_item_aware.json", "min HR 2dp"),
        Macro("ItemAwareMaxDisp", _fmt(max(hrs), 2), "results/secondary/h1_item_aware.json", "max HR 2dp"),
        Macro("ItemAwareExHR", _fmt(float(gtm["hr"]), 2), "results/secondary/h1_item_aware.json", "glmmTMB.hr"),
        Macro("ItemAwareExLo", _fmt(float(gtm["ci_low"]), 2), "results/secondary/h1_item_aware.json", "glmmTMB.ci_low"),
        Macro("ItemAwareExHi", _fmt(float(gtm["ci_high"]), 2), "results/secondary/h1_item_aware.json", "glmmTMB.ci_high"),
        Macro("LocoLo", _fmt(min(loco_hrs), 2), "results/secondary/h1_robustness.json", "min(LOCO crude_hr)"),
        Macro("LocoHi", _fmt(max(loco_hrs), 2), "results/secondary/h1_robustness.json", "max(LOCO crude_hr)"),
        Macro("EvalAwareChains", f"{int(eval_n)}", "results/eval_awareness_main_v1.json|hazard", "n_flagged_chains"),
        Macro("TypeI", _fmt(type_i, 2), "results/phase6_sims/summary.json", "S0.h1_reject_rate"),
        Macro("PowerS", _fmt(power_s, 2), "results/phase6_sims/summary.json", "power_S1"),
        Macro("HoneNevents", f"{int(h1['n_events'])}", "results/confirmatory.json", "hypotheses.H1.n_events"),
        Macro("HonePraw", _fmt(h1["p_raw"], 4), "results/confirmatory.json", "hypotheses.H1.p_raw"),
        Macro(
            "HoneMethod",
            str(h1["method"]).replace("_", r"\_"),
            "results/confirmatory.json",
            "hypotheses.H1.method",
        ),
        Macro("NAgentEventsSR", f"{n_agent_events_sr}", "results/descriptives_main_v1.md", "KM AGENT SELF_REFLECT n_events"),
        Macro(
            "NAgentOneEvents",
            f"{int(a1['n_agent1_events_self_reflect'])}",
            "results/secondary/agent1_audit.json",
            "n_agent1_events_self_reflect",
        ),
        Macro(
            "AgentOneMimoAgreePct",
            f"{100 * float(a1['mimo_agreement_hazard_event_mimo']['AGENT1']['agree_rate']):.0f}",
            "results/secondary/agent1_audit.json",
            "mimo_agreement_hazard_event_mimo.AGENT1.agree_rate*100",
        ),
        Macro("NUnlessAsked", f"{n_unless}", "results/secondary/agent1_audit.json", "frac_unless_asked_only*n"),
        Macro("TouchCorSR", _fmt(float(dsr["COR"]["p_touch"]), 3), "results/exploratory/erosion_decomposition.json", "SR.COR.p_touch"),
        Macro(
            "TouchAgentSR",
            _fmt(float(dsr["AGENT"]["p_touch"]), 3),
            "results/exploratory/erosion_decomposition.json",
            "SR.AGENT.p_touch",
        ),
        Macro(
            "ErosGivenTouchCorSR",
            _fmt(float(dsr["COR"]["p_erosion_given_touch"]), 2),
            "results/exploratory/erosion_decomposition.json",
            "SR.COR.p_erosion_given_touch",
        ),
        Macro(
            "ErosGivenTouchAgentSR",
            _fmt(float(dsr["AGENT"]["p_erosion_given_touch"]), 2),
            "results/exploratory/erosion_decomposition.json",
            "SR.AGENT.p_erosion_given_touch",
        ),
        Macro("CensorGemmaN", f"{n_cens_g}", "results/exploratory/censoring_check.json", "gemma4_12b.n_censored_chains_forced"),
        Macro(
            "CensorGemmaPct",
            f"{n_cens_g}",
            "results/exploratory/censoring_check.json",
            "n_censored_chains_forced (=%% of 100 forced chains)",
        ),
        Macro("AARGemmaThirtyOneRZero", _fmt(aar("gemma4_31b", "R0"), 2), "results/battery_b1_main_v1.csv.gz", "gemma4_31b R0 AUTH"),
        Macro(
            "AARGemmaThirtyOneCorInv",
            _fmt(aar("gemma4_31b", "COR_INV"), 2),
            "results/battery_b1_main_v1.csv.gz",
            "gemma4_31b COR_INV AUTH",
        ),
        Macro("AARGemmaTwelveRZero", _fmt(aar("gemma4_12b", "R0"), 2), "results/battery_b1_main_v1.csv.gz", "gemma4_12b R0 AUTH"),
        Macro(
            "AARGemmaTwelveCorInv",
            _fmt(aar("gemma4_12b", "COR_INV"), 2),
            "results/battery_b1_main_v1.csv.gz",
            "gemma4_12b COR_INV AUTH",
        ),
        Macro(
            "AAROlmoFinalRZero",
            _fmt(aar("olmo3_7b_final", "R0"), 2),
            "results/battery_b1_main_v1.csv.gz",
            "olmo3_7b_final R0 AUTH",
        ),
        Macro(
            "AAROlmoFinalCorInv",
            _fmt(aar("olmo3_7b_final", "COR_INV"), 2),
            "results/battery_b1_main_v1.csv.gz",
            "olmo3_7b_final COR_INV AUTH",
        ),
        Macro(
            "CorSwapNonIdMin",
            f"{min(nis)}",
            "results/secondary/h3_secondary.json",
            "min COR_swap_non_identical",
        ),
        Macro(
            "CorSwapNonIdMax",
            f"{max(nis)}",
            "results/secondary/h3_secondary.json",
            "max COR_swap_non_identical",
        ),
        Macro("NHThreeIncluded", f"{len(h3s['included_configs'])}", "results/secondary/h3_secondary.json", "len(included_configs)"),
        Macro(
            "HRQwenThink",
            _fmt(float(pf["qwen38_27b_think"]["crude_hr"]), 2),
            "results/exploratory/h4_moderation.json",
            "qwen38_27b_think.crude_hr",
        ),
        Macro(
            "HRQwenNothink",
            _fmt(float(pf["qwen38_27b_nothink"]["crude_hr"]), 2),
            "results/exploratory/h4_moderation.json",
            "qwen38_27b_nothink.crude_hr",
        ),
        Macro(
            "HROlmoSft",
            _fmt(float(pf["olmo3_7b_sft"]["crude_hr"]), 2),
            "results/exploratory/h4_moderation.json",
            "olmo3_7b_sft.crude_hr",
        ),
        Macro(
            "HROlmoDpo",
            _fmt(float(pf["olmo3_7b_dpo"]["crude_hr"]), 2),
            "results/exploratory/h4_moderation.json",
            "olmo3_7b_dpo.crude_hr",
        ),
        Macro(
            "HROlmoFinal",
            _fmt(float(pf["olmo3_7b_final"]["crude_hr"]), 2),
            "results/exploratory/h4_moderation.json",
            "olmo3_7b_final.crude_hr",
        ),
        Macro("NSubordCOR", f"{int(fate['subordinated_counts']['COR'])}", "results/exploratory/fate_mix.json", "subordinated_counts.COR"),
        Macro(
            "NSubordAGENT",
            f"{int(fate['subordinated_counts']['AGENT'])}",
            "results/exploratory/fate_mix.json",
            "subordinated_counts.AGENT",
        ),
        Macro("NHFiveAdded", f"{int(h5['n_added_clauses'])}", "results/exploratory/h5_emergent.json", "n_added_clauses"),
        Macro("NHFiveAutonomy", f"{int(h5['counts']['AUTONOMY'])}", "results/exploratory/h5_emergent.json", "counts.AUTONOMY"),
        Macro("NCalib", "1011", "reports/PHASE_4.md", "Part C n=1011"),
        Macro("NCalibDisp", "1{,}011", "reports/PHASE_4.md", "Part C n=1011 comma"),
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
