#!/usr/bin/env python3
"""Generate paper_jair/appendix/J_computing.tex from repository configs (no hand typing)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper_jair" / "appendix" / "J_computing.tex"


def main() -> None:
    models = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text())
    lock = yaml.safe_load((ROOT / "configs" / "model_revisions.lock.yaml").read_text())
    vllm = yaml.safe_load((ROOT / "configs" / "vllm.yaml").read_text())
    judges = yaml.safe_load((ROOT / "configs" / "judges.yaml").read_text())

    sha: dict[str, str] = {}
    for s in lock.get("subjects", []):
        sha[s["exact_repo_id"]] = s["sha"]

    rows = []
    for s in models["subjects"]:
        repo = s["hf_repo"]
        samp = s.get("sampling", {})
        ctk = s.get("chat_template_kwargs") or {}
        think = ctk.get("enable_thinking")
        if think is True:
            think_s = "on"
            max_tok = vllm["think_max_tokens"]
        elif think is False:
            think_s = "off"
            max_tok = vllm["default_max_tokens"]
        else:
            think_s = "n/a (not set)"
            max_tok = vllm["default_max_tokens"]
        top_k = samp.get("top_k")
        top_k_s = str(top_k) if top_k is not None else "not set"
        rows.append(
            {
                "config_id": s["config_id"],
                "repo": repo,
                "sha": sha.get(repo, "MISSING"),
                "think": think_s,
                "temp": samp.get("temperature"),
                "top_p": samp.get("top_p"),
                "top_k": top_k_s,
                "max_tok": max_tok,
                "dtype": str(s.get("dtype", "bf16")).upper(),
            }
        )

    gpt = next(j for j in judges["judges"] if j["judge_id"] == "gpt54")
    mimo = next(j for j in judges["judges"] if j["judge_id"] == "mimo_v26_pro")
    batt = models["battery_sampling"]

    def esc(s: str) -> str:
        return s.replace("_", r"\_")

    lines: list[str] = []
    lines.append(r"\section{Computing environment and generation settings}\label{app:computing}")
    lines.append("")
    lines.append(
        r"This appendix was generated from repository configuration files "
        r"(\texttt{configs/models.yaml}, \texttt{configs/vllm.yaml}, "
        r"\texttt{configs/judges.yaml}, \texttt{configs/model\_revisions.lock.yaml}), "
        r"Modal app definitions under \texttt{modal\_apps/}, and analysis environment "
        r"records. Values marked ``not recorded'' are absent from those sources."
    )
    lines.append("")
    lines.append(r"\subsection{Generation settings by configuration}")
    lines.append(
        r"Decoding settings followed each model card and were fixed in the "
        r"preregistration; no hyperparameters were tuned."
    )
    lines.append(r"{\small")
    lines.append(r"\resizebox{\textwidth}{!}{%")
    lines.append(r"\begin{tabular}{llcccccll}")
    lines.append(r"\toprule")
    lines.append(
        r"Configuration & Model (pinned SHA) & Thinking & Temp. & Top-$p$ & "
        r"Top-$k$ & Max new tokens & Prec. & vLLM \\"
    )
    lines.append(r"\midrule")
    for r in rows:
        model = f"{esc(r['repo'])} ({r['sha'][:12]})"
        lines.append(
            f"{esc(r['config_id'])} & {model} & {r['think']} & {r['temp']} & "
            f"{r['top_p']} & {r['top_k']} & {r['max_tok']} & {r['dtype']} & "
            f"{vllm['version']} \\\\"
        )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}%")
    lines.append(r"}")
    lines.append(r"}")
    lines.append("")
    lines.append(r"\subsection{Judge settings}")
    lines.append(r"{\small")
    lines.append(r"\resizebox{\textwidth}{!}{%")
    lines.append(r"\begin{tabular}{llrrr}")
    lines.append(r"\toprule")
    lines.append(r"Role & Model identifier & Temp. & Top-$p$ & Max tokens \\")
    lines.append(r"\midrule")
    lines.append(
        f"Primary judge & {esc(gpt['api_model'])} & "
        f"{gpt['sampling']['temperature']} & {gpt['sampling']['top_p']} & "
        f"{gpt['max_tokens']} \\\\"
    )
    lines.append(
        f"Second judge & {esc(mimo['api_model'])} "
        f"(HF {esc(mimo['hf_repo'])}, SHA {mimo['revision'][:12]}) & "
        f"{mimo['sampling']['temperature']} & {mimo['sampling']['top_p']} & "
        f"{mimo['max_tokens']} \\\\"
    )
    lines.append(
        f"Behavioural battery (greedy) & subject model under test & "
        f"{batt['temperature']} & {batt['top_p']} & "
        r"same as generation defaults \\"
    )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}%")
    lines.append(r"}")
    lines.append(r"}")
    lines.append("")
    lines.append(r"\subsection{Hardware and software}")
    lines.append(r"\begin{itemize}")
    lines.append(
        r"\item \textbf{GPUs (one GPU per generation job).} "
        r"Qwen3.8-27B (both thinking settings) and Gemma-4-31B: NVIDIA A100 80\,GB "
        r"(Modal \texttt{A100-80GB}), with 8 CPU cores and 64\,GiB RAM reserved. "
        r"Gemma-4-12B: NVIDIA L40S (Modal \texttt{L40S}), 8 CPU cores and 64\,GiB RAM. "
        r"OLMo-3-7B (SFT, DPO, Instruct): NVIDIA L4 (Modal \texttt{L4}), 4 CPU cores "
        r"and 16\,GiB RAM. Judge coding and battery API scoring ran on CPU containers "
        r"(2 CPU / 8\,GiB for coding; battery scoring as configured in "
        r"\texttt{modal\_apps/phase5\_battery.py})."
    )
    lines.append(
        r"\item \textbf{OS image.} GPU jobs: \texttt{nvidia/cuda:12.8.1-devel-ubuntu22.04} "
        r"with Python 3.11 added by Modal. CPU jobs: Modal \texttt{debian\_slim} with "
        r"Python 3.11."
    )
    lines.append(
        r"\item \textbf{Python.} 3.11 "
        r"(requires-python $\geq 3.11,<3.12$ in \texttt{pyproject.toml})."
    )
    lines.append(
        r"\item \textbf{Libraries.} vLLM 0.30.0 (pinned in \texttt{configs/vllm.yaml} "
        r"and Modal images). torch: not recorded (transitive dependency of vLLM 0.30.0). "
        r"transformers: not recorded for the main-run GPU image (Phase~4 "
        r"judge-calibration images pinned \texttt{transformers==5.16.1}; the main-run "
        r"image pins only vLLM)."
    )
    lines.append(
        r"\item \textbf{R analysis environment} (\texttt{results/analysis\_env.json}). "
        r"R 4.6.1 (2026-06-24); lme4 2.0.6; geepack 1.3.13; jsonlite 2.0.0. "
        r"glmmTMB: not recorded in \texttt{results/analysis\_env.json} "
        r"(used only in secondary scripts under \texttt{analysis/secondary/})."
    )
    lines.append(r"\end{itemize}")
    lines.append("")
    lines.append(r"\subsection{Randomness}")
    lines.append(r"\begin{itemize}")
    lines.append(
        r"\item Master seed \textbf{20261004} (\texttt{configs/experiment.yaml})."
    )
    lines.append(
        r"\item Per-unit chain seeds: "
        r"\path{sha256(master_seed|config_id|condition|chain_idx)} "
        r"(\path{src/rc/io_utils.py})."
    )
    lines.append(
        r"\item Starting-constitution order depends only on the chain index "
        r"(blocked design, D17); materials seed recorded per chain."
    )
    lines.append(
        r"\item Per-call sampling seeds derived as\linebreak "
        r"\path{sha256(master|config|protocol|condition|chain|round|attempt)}, "
        r"then masked to signed 32-bit for vLLM \texttt{SamplingParams.seed} "
        r"(\path{src/rc/chain_runner.py}, \path{src/rc/generation.py}). "
        r"Per-call seeds \textbf{were} fixed and passed to the sampler."
    )
    lines.append(
        r"\item Second-judge subsample: stratified random 25\% of confirmatory "
        r"transitions, seed 20261004 (D56), drawn before main-run coding."
    )
    lines.append(
        r"\item Reliability / confirmatory bootstrap seed: 20261004 "
        r"(\texttt{analysis/confirmatory/reliability.R})."
    )
    lines.append(r"\end{itemize}")
    lines.append("")
    lines.append(r"\subsection{Hyperparameter search}")
    lines.append(
        r"No hyperparameters were tuned. Decoding settings followed each model card "
        r"and were fixed in the preregistration (preregistration sampling section / "
        r"D10--D11: sampling parameters follow each model card and are held constant "
        r"within each manipulated family)."
    )
    lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
