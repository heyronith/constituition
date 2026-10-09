#!/usr/bin/env python3
"""Generate paper tables, figures, and data-driven appendices (Phase 8)."""

from __future__ import annotations

import hashlib
import json
import random
import re
import textwrap
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "paper" / "tables"
FIG = ROOT / "paper" / "figs"
APP = ROOT / "paper" / "appendix"
SEED = 20261004

# Wong colour-blind-safe palette
COLS = {"COR": "#E69F00", "AGENT": "#56B4E9", "SELF": "#009E73", "other": "#0072B2"}


_UNICODE_ASCII = {
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "−": "-",
    "–": "-",
    "—": "-",
    "×": "x",
    "α": "alpha",
    "β": "beta",
    "Δ": "Delta",
    "→": "->",
    "←": "<-",
    "≈": "~=",
    "±": "+/-",
    "…": "...",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "\u00a0": " ",
}


def clip(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    return s[: n - 3].rstrip() + "..."


def redact_identifiers(s: str) -> str:
    """Strip review-copy identifiers from generated paper text."""
    out = str(s)
    reps = [
        (r"(?i)heyronith", "[REDACTED]"),
        (r"(?i)ronith\.sharmila@swosu\.edu", "[REDACTED]"),
        (r"(?i)agrawalr1@nku\.edu", "[REDACTED]"),
        (r"(?i)ronith\s+sharmila", "[REDACTED]"),
        (r"(?i)rupesh\s+agrawal", "[REDACTED]"),
        (r"(?i)https?://osf\.io/\S+", "[OSF-REDACTED]"),
        (r"(?i)osf\.io/\S+", "[OSF-REDACTED]"),
        (r"(?i)https?://(?:www\.)?github\.com/\S+", "[REPO-REDACTED]"),
        (r"(?i)github\.com/\S+", "[REPO-REDACTED]"),
        (r"(?i)[\w.-]+\.modal\.com\S*", "[MODAL-REDACTED]"),
        (r"(?i)modal\.com/\S*", "[MODAL-REDACTED]"),
        (r"(?i)constituition", "[REPO-REDACTED]"),
    ]
    for pat, repl in reps:
        out = re.sub(pat, repl, out)
    return out


def esc(s: str) -> str:
    # Redact before escaping so review PDF stays anonymous.
    out = redact_identifiers(s).replace("\n", " ").replace("\r", " ")
    for u, a in _UNICODE_ASCII.items():
        out = out.replace(u, a)
    # Drop remaining non-ASCII that pdflatex cannot handle.
    out = "".join(ch if ord(ch) < 128 else "?" for ch in out)
    # Order matters: backslash first.
    out = out.replace("\\", "\\textbackslash{}")
    out = out.replace("&", "\\&")
    out = out.replace("%", "\\%")
    out = out.replace("#", "\\#")
    out = out.replace("$", "\\$")
    out = out.replace("_", "\\_")
    out = out.replace("{", "\\{")
    out = out.replace("}", "\\}")
    out = out.replace("~", "\\textasciitilde{}")
    out = out.replace("^", "\\textasciicircum{}")
    out = out.replace("`", "'")
    return out


def write_table_items_examples() -> None:
    items = yaml.safe_load((ROOT / "materials/constitution_items.yaml").read_text())["items"]
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], it)
    order = ["COR", "AGENT", "SELF", "HON", "HARM", "CARE", "PROC"]
    rows = []
    for cat in order:
        it = by_cat[cat]
        rows.append(
            f"{esc(cat)} & {esc(it['item_id'])} & {esc(it['commitment'])} & "
            f"{esc(it['form_A'][:110])}{'...' if len(it['form_A'])>110 else ''} \\\\"
        )
    tex = r"""% Auto-generated
\begin{table}[t]
\centering
\caption{Example clause per category (form A, truncated).}
\label{tab:items_examples}
\begin{tabular}{llll}
\toprule
Category & ID & Commitment & Example (form A) \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (TAB / "items_examples.tex").write_text(tex)


def write_table_models() -> None:
    models = [
        ("qwen38_27b_nothink", "Qwen3.8-27B", "thinking off", "family A"),
        ("qwen38_27b_think", "Qwen3.8-27B", "thinking on", "reasoning"),
        ("gemma4_31b", "Gemma-4-31B-it", "---", "family B, large"),
        ("gemma4_12b", "Gemma-4-12B-it", "---", "scale"),
        ("olmo3_7b_sft", "OLMo-3-7B", "SFT", "post-training"),
        ("olmo3_7b_dpo", "OLMo-3-7B", "DPO", "post-training"),
        ("olmo3_7b_final", "OLMo-3-7B", "final (RLVR)", "post-training"),
    ]
    rows = "\n".join(
        f"{esc(a)} & {esc(b)} & {esc(c)} & {esc(d)} \\\\" for a, b, c, d in models
    )
    tex = rf"""% Auto-generated
\begin{{table}}[t]
\centering
\caption{{Subject configurations (pinned HF SHAs in repository lockfile).}}
\label{{tab:models}}
\begin{{tabular}}{{llll}}
\toprule
Config ID & Model & Manipulation & Role \\
\midrule
{rows}
\bottomrule
\end{{tabular}}
\end{{table}}
"""
    (TAB / "models.tex").write_text(tex)


def write_table_h1_robustness() -> None:
    rob = json.loads((ROOT / "results/secondary/h1_robustness.json").read_text())
    ia = json.loads((ROOT / "results/secondary/h1_item_aware.json").read_text())
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    rows = [
        ("Confirmatory GLMM", f"{conf['hypotheses']['H1']['hr']:.3f}",
         f"[{conf['hypotheses']['H1']['ci_low']:.3f}, {conf['hypotheses']['H1']['ci_high']:.3f}]",
         conf["hypotheses"]["H1"]["method"]),
        ("Crude HR", f"{rob['point_crude']['crude_hr']:.3f}", "---", "events/at-risk"),
        ("Chain bootstrap", f"{rob['chain_cluster_bootstrap']['crude_hr_point']:.3f}",
         f"[{rob['chain_cluster_bootstrap']['ci_low']:.3f}, {rob['chain_cluster_bootstrap']['ci_high']:.3f}]",
         "2000 reps"),
        ("LOIO drop AGENT1", f"{rob['leave_one_item_out']['AGENT1']['crude_hr']:.3f}", "---", "crude"),
        ("Item permutation $p$", f"{rob['item_permutation']['p_one_sided_le_obs']:.3f}", "---", "252 relabelings"),
    ]
    for name, key in [
        ("glmmTMB full RE", "glmmTMB"),
        ("sandwich item cluster", "gee_item"),
        ("brms", "brms"),
    ]:
        r = ia.get(key) or {}
        if r.get("ok"):
            rows.append(
                (name, f"{r['hr']:.3f}", f"[{r.get('ci_low', float('nan')):.3f}, {r.get('ci_high', float('nan')):.3f}]", r.get("method", ""))
            )
    body = "\n".join(f"{esc(a)} & {b} & {c} & {esc(d)} \\\\" for a, b, c, d in rows)
    tex = rf"""% Auto-generated --- SECONDARY robustness
\begin{{table}}[t]
\centering
\caption{{H1 robustness summary (SECONDARY). Confirmatory row is frozen.}}
\label{{tab:h1_robustness}}
\begin{{tabular}}{{llll}}
\toprule
Estimate & HR / $p$ & 95\% CI & Method \\
\midrule
{body}
\bottomrule
\end{{tabular}}
\end{{table}}
"""
    (TAB / "h1_robustness.tex").write_text(tex)


def write_table_fates() -> None:
    desc = (ROOT / "results/descriptives_main_v1.md").read_text()
    # parse counts table
    lines = []
    in_counts = False
    for line in desc.splitlines():
        if line.startswith("| category | INVERTED"):
            in_counts = True
            continue
        if in_counts:
            if not line.startswith("|"):
                break
            if line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 9:
                lines.append(
                    " & ".join(esc(p) if i == 0 else p for i, p in enumerate(parts[:9])) + " \\\\"
                )
    tex = r"""% Auto-generated
\begin{table}[t]
\centering
\caption{Seven-way fate counts by category (all FORCED touches; DELETED separate).}
\label{tab:fates}
\resizebox{\textwidth}{!}{%
\begin{tabular}{lrrrrrrrr}
\toprule
Category & INV & SUB & WEAK & QL & STR & MER & RET & DEL \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}}
\end{table}
"""
    (TAB / "fates.tex").write_text(tex)


def write_table_h3() -> None:
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    h3 = conf["hypotheses"]["H3"]
    rows = []
    for cfg, r in h3["inclusion"]["per_config"].items():
        rows.append(
            f"{esc(cfg)} & {r['AAR_R0']:.3f} & {r['AAR_COR_INV']:.3f} & {r['delta']:.3f} & "
            f"{'yes' if r['included'] else 'no'} \\\\"
        )
    body = "\n".join(rows)
    tex = rf"""% Auto-generated
\begin{{table}}[t]
\centering
\caption{{H3 positive-control inclusion and confirmatory contrast.}}
\label{{tab:h3}}
\begin{{tabular}}{{lrrrl}}
\toprule
Config & AAR(R0) & AAR(COR\_INV) & $\Delta$ & Included \\
\midrule
{body}
\midrule
\multicolumn{{5}}{{l}}{{Pooled $\Delta\beta=\HthreeEst$ [{{\HthreeLo}}, {{\HthreeHi}}]; method {esc(h3['method'])}.}} \\
\bottomrule
\end{{tabular}}
\end{{table}}
"""
    (TAB / "h3.tex").write_text(tex)


def write_table_confirmatory() -> None:
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    h1 = conf["hypotheses"]["H1"]
    h2a = conf["hypotheses"]["H2"]["H2a"]
    h2b = conf["hypotheses"]["H2"]["H2b"]
    h3 = conf["hypotheses"]["H3"]
    rows = [
        f"H1 & HR={h1['hr']:.3f} & [{h1['ci_low']:.3f}, {h1['ci_high']:.3f}] & {h1['p_raw']:.4g} & {h1['p_holm']} & {esc(h1['method'])} \\\\",
        f"H2a & gap={h2a['log_hr_gap']:.3f} & [{h2a['ci_low']:.3f}, {h2a['ci_high']:.3f}] & {h2a['p_raw']:.4g} & {h2a['p_holm']} & {esc(h2a['method'])} \\\\",
        f"H2b & gap={h2b['log_hr_gap']:.3f} & [{h2b['ci_low']:.3f}, {h2b['ci_high']:.3f}] & {h2b['p_raw']:.4g} & {h2b['p_holm']} & {esc(h2b['method'])} \\\\",
        f"H3 & $\\Delta\\beta$={h3['estimate']:.3f} & [{h3['ci_low']:.3f}, {h3['ci_high']:.3f}] & {h3['p_raw']:.4g} & {h3['p_holm']} & {esc(h3['method'])} \\\\",
    ]
    tex = r"""% Auto-generated from results/confirmatory.json
\begin{table}[t]
\centering
\caption{Full confirmatory summary (frozen single run).}
\label{tab:confirmatory}
\begin{tabular}{llllll}
\toprule
Hypothesis & Estimate & 95\% CI & raw $p$ & Holm $p$ & method \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (TAB / "confirmatory.tex").write_text(tex)


def write_table_deviations() -> None:
    dec = (ROOT / "docs/DECISIONS.md").read_text()
    rows = []
    for line in dec.splitlines():
        m = re.match(r"^(D\d+)\s*\|\s*([^|]+)\|\s*(.+)", line)
        if not m:
            continue
        did, date, rest = m.group(1), m.group(2).strip(), m.group(3).strip()
        # take first clause of decision text
        text = clip(rest.split("|")[0].strip(), 90)
        rows.append(f"{esc(did)} & {esc(date)} & {esc(text)} \\\\")
        if len(rows) >= 40:
            break
    tex = r"""% Auto-generated from docs/DECISIONS.md
\begin{table}[t]
\centering
\caption{Selected design/analysis deviations (D-log; see Appendix~A for fuller list).}
\label{tab:deviations}
\begin{tabular}{llp{9cm}}
\toprule
ID & Date & Summary \\
\midrule
""" + "\n".join(rows[:25]) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    (TAB / "deviations.tex").write_text(tex)


def write_figs() -> None:
    # Reuse CSVs from 7E-C; regenerate PDFs with R (colour-blind-safe)
    r_script = r'''
cols <- c(COR="#E69F00", AGENT="#56B4E9", SELF="#009E73")
# KM
km <- read.csv("results/figs/km_cor_agent_self.csv", stringsAsFactors=FALSE)
conds <- c("SELF_REFLECT","OTHER_REFLECT","PARAPHRASE","NEUTRAL_EDIT")
pdf("paper/figs/km_curves.pdf", width=8, height=6.5)
par(mfrow=c(2,2), mar=c(4,4,3,1))
ymax <- max(km$cum_prop, na.rm=TRUE)*1.05
for (cond in conds) {
  plot(NA, xlim=c(1,20), ylim=c(0,ymax), xlab="Round t", ylab="P(eroded by t)",
       main=gsub("_"," ",cond), las=1)
  for (cat in c("COR","AGENT","SELF")) {
    sub <- km[km$condition==cond & km$category==cat,]; sub <- sub[order(sub$round),]
    lines(c(sub$round[1], sub$round), c(0, sub$cum_prop), type="s", col=cols[[cat]], lwd=2)
  }
  legend("topleft", legend=c("COR","AGENT","SELF"), col=cols[c("COR","AGENT","SELF")], lwd=2, bty="n", cex=0.8)
}
dev.off()

# LOIO
lo <- read.csv("results/figs/loio_hr.csv", stringsAsFactors=FALSE)
pdf("paper/figs/loio.pdf", width=8, height=4.5)
par(mar=c(7,4,3,1))
barplot(lo$crude_hr, names.arg=lo$item, las=2, col=ifelse(lo$item=="AGENT1","#D55E00","#0072B2"),
        ylab="Crude HR (COR/AGENT)", main="SECONDARY: leave-one-item-out")
abline(h=1, lty=3); abline(h=0.495, lty=2, col="#CC79A7")
dev.off()

# Decomposition
dec <- read.csv("results/figs/decomposition.csv", stringsAsFactors=FALSE)
pdf("paper/figs/decomposition.pdf", width=8, height=6.5)
par(mfrow=c(2,2), mar=c(4,4,3,1))
for (cond in unique(dec$condition)) {
  sub <- dec[dec$condition==cond & dec$category %in% c("COR","AGENT","SELF"),]
  plot(sub$p_touch, sub$p_erosion_given_touch, pch=16, col=cols[sub$category],
       xlab="P(touch)", ylab="P(erosion|touch)", main=gsub("_"," ",cond),
       xlim=c(0,max(dec$p_touch,na.rm=TRUE)*1.1), ylim=c(0,max(dec$p_erosion_given_touch,na.rm=TRUE)*1.1))
  text(sub$p_touch, sub$p_erosion_given_touch, sub$category, pos=4, cex=0.8)
}
dev.off()

# Forest EXPLORATORY
fo <- read.csv("results/figs/forest_h4.csv", stringsAsFactors=FALSE)
pdf("paper/figs/forest_h4.pdf", width=7, height=5)
par(mar=c(4,10,3,1))
ord <- order(fo$hr); fo <- fo[ord,]
y <- seq_len(nrow(fo))
plot(fo$hr, y, pch=16, xlim=range(c(fo$ci_low, fo$ci_high, 1), na.rm=TRUE),
     ylim=c(0.5,nrow(fo)+0.5), xlab="Crude HR (EXPLORATORY)", ylab="", yaxt="n",
     main="EXPLORATORY: per-config HR")
axis(2, at=y, labels=fo$config, las=1, cex.axis=0.8)
segments(fo$ci_low, y, fo$ci_high, y, lwd=2, col="#0072B2")
abline(v=1, lty=3)
dev.off()

# Positive controls vs swaps (from battery)
# Written by Python companion CSV if present
if (file.exists("paper/figs/pos_controls.csv")) {
  pc <- read.csv("paper/figs/pos_controls.csv", stringsAsFactors=FALSE)
  pdf("paper/figs/pos_controls.pdf", width=8, height=5)
  configs <- unique(pc$config)
  x <- seq_along(configs)
  plot(NA, xlim=c(0.5,length(configs)+0.5), ylim=c(0,1), xaxt="n",
       ylab="AAR", xlab="", main="Positive controls vs swaps (AUTH)")
  axis(1, at=x, labels=configs, las=2, cex.axis=0.7)
  for (i in x) {
    sub <- pc[pc$config==configs[i],]
    points(rep(i-0.15, sum(sub$constitution=="R0")), sub$AAR[sub$constitution=="R0"], pch=16, col="#009E73")
    points(rep(i, sum(sub$constitution=="COR_INV")), sub$AAR[sub$constitution=="COR_INV"], pch=17, col="#D55E00")
    points(rep(i+0.15, sum(sub$constitution=="COR_swap")), sub$AAR[sub$constitution=="COR_swap"], pch=15, col="#56B4E9")
  }
  legend("bottomleft", legend=c("R0","COR_INV","COR_swap"), pch=c(16,17,15),
         col=c("#009E73","#D55E00","#56B4E9"), bty="n")
  dev.off()
}

# Paradigm schematic — two panels (Wong CB-safe), single-column width
W <- list(blue="#0072B2", orange="#E69F00", green="#009E73",
          sky="#56B4E9", verm="#D55E00", purple="#CC79A7", black="#000000")
box <- function(x0,y0,x1,y1, col, fill=NA, lwd=1.6) {
  rect(x0,y0,x1,y1, border=col, col=fill, lwd=lwd)
}
arr <- function(x0,y0,x1,y1, col=W$black) {
  arrows(x0,y0,x1,y1, length=0.08, lwd=1.4, col=col)
}

pdf("paper/figs/paradigm.pdf", width=6.5, height=6.8)
par(mfrow=c(2,1), mar=c(0.6,0.6,1.6,0.6))

## (a) Chain loop
plot(NA, xlim=c(0,10), ylim=c(0,6.2), axes=FALSE, xlab="", ylab="",
     main="(a) Chain loop (stateless; t = 1...20)")
box(0.2, 3.6, 2.4, 5.4, W$blue, "#E8F4FA")
text(1.3, 4.7, expression(C[t]), cex=1.15, font=2, col=W$blue)
text(1.3, 4.15, "35 principles\nopaque IDs", cex=0.72)
box(3.0, 3.4, 6.2, 5.6, W$orange, "#FFF6E5")
text(4.6, 5.15, "Model (stateless)", cex=0.85, font=2, col=W$orange)
text(4.6, 4.55, "sees only C_t +\ncondition instruction", cex=0.7)
text(4.6, 3.7, "SELF / OTHER \"Pellam\"\nPARAPHRASE / NEUTRAL", cex=0.62)
arr(2.45, 4.5, 2.95, 4.5, W$blue)
box(6.7, 3.8, 9.0, 5.2, W$green, "#E8F7F1")
text(7.85, 4.7, "Exactly one\nchange", cex=0.8, font=2, col=W$green)
text(7.85, 4.1, "revise / merge / delete", cex=0.65)
arr(6.25, 4.5, 6.65, 4.5, W$orange)
box(7.0, 1.6, 9.3, 3.1, W$blue, "#E8F4FA")
text(8.15, 2.55, expression(C[t+1]), cex=1.1, font=2, col=W$blue)
text(8.15, 2.0, "next round input", cex=0.68)
arr(7.85, 3.75, 8.15, 3.15, W$green)
arr(7.0, 2.35, 1.3, 2.35, W$sky)
arr(1.3, 2.35, 1.3, 3.55, W$sky)
text(4.0, 2.7, "repeat (Markov)", cex=0.7, col=W$sky)
box(0.3, 0.15, 6.0, 1.45, W$verm, "#FDEEE8")
text(3.15, 1.15, "Side branch (each change)", cex=0.75, font=2, col=W$verm)
text(3.15, 0.55, "GPT-5.4 fate (+25% MiMo)  ->  erosion event\n-> discrete-time survival: COR vs AGENT vs SELF", cex=0.65)
arr(7.3, 3.9, 5.5, 1.5, W$verm)

## (b) Behaviour test
plot(NA, xlim=c(0,10), ylim=c(0,5.5), axes=FALSE, xlab="", ylab="",
     main="(b) Behaviour test (chains 0-4)")
box(0.2, 3.2, 2.6, 5.0, W$blue, "#E8F4FA")
text(1.4, 4.4, "Build installs", cex=0.8, font=2, col=W$blue)
text(1.4, 3.7, "R0, R20,\nCOR-swap, AGENT-swap\n(+ COR_INV / AGENT_INV)", cex=0.62)
arr(2.65, 4.1, 3.15, 4.1)
box(3.2, 3.2, 5.8, 5.0, W$orange, "#FFF6E5")
text(4.5, 4.4, "System prompt", cex=0.8, font=2, col=W$orange)
text(4.5, 3.7, "install constitution\nas system message", cex=0.68)
arr(5.85, 4.1, 6.35, 4.1)
box(6.4, 3.0, 9.7, 5.2, W$green, "#E8F7F1")
text(8.05, 4.55, "B1 oversight scenarios", cex=0.8, font=2, col=W$green)
text(8.05, 3.7, "authorized: accept?\nunauthorized: refuse?", cex=0.68)
arr(8.05, 2.95, 8.05, 2.35)
box(6.2, 0.6, 9.7, 2.3, W$purple, "#F7EAF3")
text(7.95, 1.7, "Outcomes", cex=0.8, font=2, col=W$purple)
text(7.95, 1.1, "AAR  /  URR", cex=0.9)
text(3.2, 1.5, "none = no installed constitution\n(positive-control path uses INV)", cex=0.65, col=W$black)

dev.off()
cat("figs ok\n")
'''


    # pos controls CSV
    b1 = pd.read_csv(ROOT / "results/battery_b1_main_v1.csv.gz")
    b1 = b1[~((b1.constitution == "R0") & (b1.condition == "OTHER_REFLECT"))]
    rows = []
    for cfg in sorted(b1.config.unique()):
        for cons in ("R0", "COR_INV", "COR_swap", "AGENT_swap"):
            sub = b1[(b1.config == cfg) & (b1.constitution == cons) & (b1.legitimacy == "AUTH")]
            if len(sub):
                rows.append({"config": cfg, "constitution": cons, "AAR": float(sub.accept.mean())})
    pd.DataFrame(rows).to_csv(FIG / "pos_controls.csv", index=False)
    (FIG / "_make_figs.R").write_text(r_script)
    import subprocess

    subprocess.check_call(
        ["Rscript", str(FIG / "_make_figs.R")],
        cwd=str(ROOT),
    )


def write_appendices() -> None:
    # A deviations
    dec = (ROOT / "docs/DECISIONS.md").read_text()
    lines = ["\\section{Deviations from the original plan}\\label{app:deviations}",
             "Factual summary of selected D-log entries. Full log: repository \\texttt{docs/DECISIONS.md}.",
             "",
             "\\begin{itemize}\\setlength{\\itemsep}{2pt}"]
    for line in dec.splitlines():
        m = re.match(r"^(D\d+)\s*\|\s*([^|]+)\|\s*(.+)", line)
        if not m:
            continue
        did, date, rest = m.group(1), m.group(2).strip(), m.group(3).split("|")[0].strip()
        rest = clip(rest, 220)
        lines.append(f"\\item \\textbf{{{esc(did)}}} ({esc(date)}). {esc(rest)}")
    lines.append("\\end{itemize}")
    (APP / "A_deviations.tex").write_text("\n".join(lines) + "\n")

    # B items + prompts
    items = yaml.safe_load((ROOT / "materials/constitution_items.yaml").read_text())["items"]
    lines = [
        "\\section{Items and prompts}\\label{app:items}",
        "All 70 clauses (forms A and B) from \\texttt{materials/constitution\\_items.yaml}, verbatim.",
        "",
    ]
    for it in items:
        lines.append(
            "\\paragraph{"
            + esc(it["item_id"])
            + " ("
            + esc(it["category"])
            + ").} "
            + esc(it["commitment"])
        )
        lines.append("\\\\Form A: ``" + esc(it["form_A"]) + "''")
        lines.append("\\\\Form B: ``" + esc(it["form_B"]) + "''")
        lines.append("")
    # prompts list filenames only + include short forced prompt header if yaml
    prompt_dir = ROOT / "materials/prompts"
    lines.append("\\subsection{Prompt files}")
    lines.append("Subject-facing prompts are frozen under \\texttt{materials/prompts/}:")
    lines.append("\\begin{itemize}")
    if prompt_dir.exists():
        for p in sorted(prompt_dir.glob("*.yaml")):
            lines.append(f"\\item \\texttt{{{esc(p.name)}}}")
    lines.append("\\end{itemize}")
    (APP / "B_items_prompts.tex").write_text("\n".join(lines) + "\n")

    # C rubric reliability
    conf = json.loads((ROOT / "results/confirmatory.json").read_text())
    rel = conf["reliability"]
    lines = [
        "\\section{Judge rubric, calibration, and reliability}\\label{app:rubric}",
        "Primary fate scale (erosion-first precedence): INVERTED, SUBORDINATED, WEAKENED,",
        "QUALIFIED\\_LEGITIMACY, STRENGTHENED, MERGED\\_INTACT, RETAINED; structural DELETED.",
        "Primary erosion set: WEAKENED, SUBORDINATED, INVERTED, DELETED.",
        f"Krippendorff $\\alpha$ (GPT-5.4 vs MiMo, binary erosion): $\\Alpha={rel['alpha']:.3f}$",
        f"bootstrap CI [{rel['ci_low']:.3f}, {rel['ci_high']:.3f}], $n={rel['n']}$; branch \\texttt{{{esc(rel['branch'])}}}.",
        "Calibration metrics and Phase-4 gates are documented in repository Phase~4/5 reports.",
    ]
    (APP / "C_rubric_reliability.tex").write_text("\n".join(lines) + "\n")

    # D confirmatory full
    lines = [
        "\\section{Full confirmatory output and sensitivities}\\label{app:confirmatory}",
        "Frozen single run (\\texttt{results/confirmatory.json}).",
        "See Table~\\ref{tab:confirmatory} in the main text for the summary estimates.",
        "",
        "\\subsection{Sensitivities}",
        "\\begin{itemize}",
    ]
    for name, block in conf["sensitivities"].items():
        if name == "per_config_h1":
            continue
        if "H1" in block:
            h = block["H1"]
            lines.append(
                f"\\item \\textbf{{{esc(name)}}}: H1 HR={h.get('hr', 'NA')}, "
                f"method={esc(h.get('method','?'))}, $p_{{\\mathrm{{raw}}}}={h.get('p_raw','?')}$."
            )
    lines.append("\\end{itemize}")
    lines.append("COR-vs-SELF collinearity diagnosis: see \\texttt{results/secondary/diagnose\\_sensitivities.json}.")
    (APP / "D_confirmatory.tex").write_text("\n".join(lines) + "\n")

    # E battery
    b1 = pd.read_csv(ROOT / "results/battery_b1_main_v1.csv.gz")
    b1 = b1[~((b1.constitution == "R0") & (b1.condition == "OTHER_REFLECT"))]
    lines = [
        "\\section{Battery results per configuration}\\label{app:battery}",
        "B1 AAR/URR by config $\\times$ constitution (AUTH/UNAUTH).",
        "\\begin{small}\\begin{tabular}{llrr}",
        "\\toprule Config & Constitution & AAR & URR \\\\",
        "\\midrule",
    ]
    for cfg in sorted(b1.config.unique()):
        for cons in ["R0", "COR_swap", "AGENT_swap", "R20", "NONE", "COR_INV", "AGENT_INV"]:
            sub = b1[(b1.config == cfg) & (b1.constitution == cons)]
            if sub.empty:
                continue
            aar = sub.loc[sub.legitimacy == "AUTH", "accept"].mean()
            urr = sub.loc[sub.legitimacy == "UNAUTH", "refuse"].mean()
            lines.append(f"{esc(cfg)} & {esc(cons)} & {aar:.3f} & {urr:.3f} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}\\end{small}"]
    (APP / "E_battery.tex").write_text("\n".join(lines) + "\n")

    # F study1
    s1 = json.loads((ROOT / "results/secondary/study1_permissive.json").read_text())
    lines = [
        "\\section{Study 1 (PERMISSIVE)}\\label{app:study1}",
        f"Extracted transitions: {s1['n_permissive_transitions_extracted']};",
        f"cumulative-r10 coded: {s1['n_cumulative_r10']}.",
        "Deletions/merges by category (per-round decisions):",
        "\\begin{tabular}{lrr}",
        "\\toprule Category & delete & merge \\\\",
        "\\midrule",
    ]
    for cat, d in s1["deletions_merges_by_category"].items():
        lines.append(f"{esc(cat)} & {d['delete']} & {d['merge']} \\\\")
    lines += [
        "\\bottomrule",
        "\\end{tabular}",
        "",
        f"Lineage add decisions: {sum(s1['emergent_clauses']['n_lineage_adds_by_config_condition'].values())}.",
    ]
    (APP / "F_study1.tex").write_text("\n".join(lines) + "\n")

    # G fate examples
    from rc.config import repo_root
    from rc.pilot_coding import extract_pilot_transitions
    from rc.hazard_table import load_config_judgments
    from rc.judging import normalize_fate

    root = repo_root()
    ts = extract_pilot_transitions(
        "main_v1", root=root, forced_cumulative_rounds=(10, 20), permissive_cumulative_rounds=(10,)
    )
    gpt = {
        cfg: load_config_judgments(cfg, run_tag="main_v1", root=root, judge="gpt54")[0]
        for cfg in ["qwen38_27b_nothink", "gemma4_12b", "olmo3_7b_final", "qwen38_27b_think"]
    }
    by_fate: dict[str, list] = defaultdict(list)
    for t in ts:
        if t.get("protocol") != "FORCED" or t.get("kind") not in ("per_round", "per_round_absorbed"):
            continue
        tid = str(t["transition_id"])
        cfg = str(t["config_id"])
        j = gpt.get(cfg, {}).get(tid)
        if not j:
            continue
        fate = normalize_fate(j.get("fate"))
        if fate and fate != "NONE":
            by_fate[fate].append(t)
    rng = random.Random(SEED)
    lines = [
        "\\section{Fate examples}\\label{app:fate_examples}",
        f"2--3 random examples per fate (seed {SEED}), quoted verbatim.",
        "",
    ]
    for fate in sorted(by_fate):
        pool = by_fate[fate]
        rng.shuffle(pool)
        picks = pool[:3]
        lines.append(f"\\subsection{{{esc(fate)}}}")
        for t in picks:
            o = (t.get("original") or "")[:280]
            r = (t.get("rewrite") or "")[:280]
            lines.append(
                "\\paragraph{"
                + esc(t["config_id"])
                + " / "
                + esc(t["condition"])
                + " / "
                + esc(t["item_id"])
                + f" / r{t['round']}"
                + ".}"
            )
            lines.append(f"Original: ``{esc(o)}''\\\\")
            lines.append(f"Revised: ``{esc(r)}''")
            lines.append("")
    (APP / "G_fate_examples.tex").write_text("\n".join(lines) + "\n")


def main() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    APP.mkdir(parents=True, exist_ok=True)
    write_table_items_examples()
    write_table_models()
    write_table_h1_robustness()
    write_table_fates()
    write_table_h3()
    write_table_confirmatory()
    write_table_deviations()
    print("tables ok")
    write_figs()
    print("figs ok")
    write_appendices()
    print("appendices ok")


if __name__ == "__main__":
    main()
