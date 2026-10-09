"""Phase 7E-A: GPT-5.4 Batch eval-awareness coding (CPU + OpenAI secret)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import modal

APP_NAME = "rc-phase7e-eval-aware"
RUNS_VOLUME = "rc-runs"
REMOTE_RUNS = "/rc-runs"
REMOTE_REPO = "/rc"

app = modal.App(APP_NAME)
runs_vol = modal.Volume.from_name(RUNS_VOLUME, create_if_missing=False)

cpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "pydantic>=2",
        "pyyaml",
        "python-dotenv",
        "openai>=1.60",
        "httpx",
    )
    .add_local_dir("src", remote_path=f"{REMOTE_REPO}/src")
    .add_local_dir("configs", remote_path=f"{REMOTE_REPO}/configs")
    .add_local_dir("materials", remote_path=f"{REMOTE_REPO}/materials")
)


def _link_runs() -> Path:
    runs_link = Path(REMOTE_REPO) / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE_RUNS)
    # Budget ledger for record_actual
    budget_link = Path(REMOTE_REPO) / "budget"
    vol_budget = Path(REMOTE_RUNS) / "main_v1" / "budget"
    vol_budget.mkdir(parents=True, exist_ok=True)
    ledger = vol_budget / "ledger.jsonl"
    if not ledger.exists():
        ledger.write_text("", encoding="utf-8")
    if budget_link.is_symlink() or budget_link.is_file():
        budget_link.unlink()
    elif budget_link.exists():
        shutil.rmtree(budget_link)
    budget_link.symlink_to(vol_budget)
    return Path(REMOTE_REPO)


@app.function(
    image=cpu_image,
    volumes={REMOTE_RUNS: runs_vol},
    secrets=[modal.Secret.from_name("openai-key")],
    timeout=8 * 3600,
    cpu=2,
    memory=8192,
)
def run_eval_aware(
    run_tag: str = "main_v1",
    forecast_only: bool = False,
    post_dashboard_usd: float = 2.5569875,
) -> dict:
    import os
    import sys

    sys.path.insert(0, f"{REMOTE_REPO}/src")
    os.chdir(REMOTE_REPO)
    root = _link_runs()

    from rc.eval_awareness_main import run_eval_awareness

    # OpenAI spend gated inside run_eval_awareness (dashboard + forecast ≤ $55).
    # Workspace guard runs in local_entrypoint (modal CLI not in container).

    # Ensure StrongREJECT post-dashboard figure is visible if local pull path missing.
    pull_ledger = root / "results" / "phase7d_pull" / "budget_ledger.jsonl"
    if not pull_ledger.exists():
        alt = Path(REMOTE_RUNS) / "main_v1_7d" / "budget_ledger.jsonl"
        if alt.exists():
            pull_ledger.parent.mkdir(parents=True, exist_ok=True)
            pull_ledger.write_text(alt.read_text(encoding="utf-8"), encoding="utf-8")

    summary = run_eval_awareness(
        run_tag=run_tag,
        root=root,
        forecast_only=forecast_only,
        post_dashboard_usd=post_dashboard_usd,
    )
    runs_vol.commit()
    # Totals only for return
    out = {
        "n_units": summary.get("n_units"),
        "n_flagged_rounds": summary.get("n_flagged_rounds"),
        "n_flagged_chains": summary.get("n_flagged_chains"),
        "api_usd": (summary.get("meta") or {}).get("api_usd"),
        "prompt_hash_ok": (summary.get("meta") or {}).get("prompt_hash_ok"),
        "stopped": summary.get("stopped"),
        "reason": summary.get("reason"),
        "budget_ok": (summary.get("budget_gate") or summary).get("ok"),
        "projected_usd": (summary.get("budget_gate") or summary).get("projected_usd"),
        "forecast_usd": (summary.get("budget_gate") or summary).get("forecast_usd"),
        "to_date_usd": (summary.get("budget_gate") or summary).get("to_date_usd"),
    }
    return out


@app.local_entrypoint()
def main(
    run_tag: str = "main_v1",
    forecast_only: bool = False,
    post_dashboard_usd: float = 2.5569875,
) -> None:
    import sys

    sys.path.insert(0, "src")
    from rc.guards import assert_modal_workspace

    assert_modal_workspace(expected="heyronith")
    result = run_eval_aware.remote(
        run_tag=run_tag,
        forecast_only=forecast_only,
        post_dashboard_usd=post_dashboard_usd,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
