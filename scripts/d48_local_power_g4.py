"""D48 local unblock: power + G4 + eval A2 (Modal map was preempted)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from rc.budget import spent_api_usd, spent_modal_usd
from rc.config import repo_root
from rc.cost_projection import project_main_run
from rc.d48_design import build_primary_coded, draw_reliability_subsample
from rc.power_analysis import estimate_pilot_hazard, run_power_table


def main() -> None:
    root = repo_root()
    coding = root / "runs" / "pilot_v1_coding_v3" / "coding_v3"
    out = root / "runs" / "phase4_coding"
    out.mkdir(parents=True, exist_ok=True)
    phase4 = root / "runs" / "phase4"
    phase4.mkdir(parents=True, exist_ok=True)

    status = {
        "stage": "d48_power_g4",
        "state": "running",
        "decision": "D48",
        "primary": "gpt54",
        "note": "local power after Modal preemption thrash; smoke already passed",
        "spend_usd": spent_modal_usd(root),
        "api_spend_usd": spent_api_usd(root),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n")
    (phase4 / "STATUS_4f.json").write_text(json.dumps(status, indent=2) + "\n")
    print("STATUS reset", status["stage"])

    sub = draw_reliability_subsample(root=root)
    (out / "d48_reliability_subsample.json").write_text(
        json.dumps(sub, indent=2, sort_keys=True) + "\n"
    )
    print(f"subsample n={sub['n_selected']}/{sub['n_population']} (pilot reliability check)")

    coded = build_primary_coded(coding_dir=coding, root=root)
    coded_path = out / "pilot_v1_coding_d48_primary.jsonl"
    with coded_path.open("w", encoding="utf-8") as fh:
        for row in coded:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    print(f"primary coded n={len(coded)}")

    hazard = estimate_pilot_hazard(coded, run_tag="pilot_v1")
    (out / "hazard_estimates_d48.json").write_text(json.dumps(hazard, indent=2) + "\n")
    print(
        "hazard",
        {
            k: hazard[k]
            for k in ("agent_baseline_hazard", "icc", "cor_events", "agent_events")
        },
    )

    t0 = time.time()
    print("power start workers=8 n_sims=1000 …")
    power = run_power_table(hazard, n_sims=1000, master_seed=20261004, workers=8)
    power = {"decision": "D48", "event_mode": "primary_gpt54", **power}
    (out / "power_table_d48.json").write_text(json.dumps(power, indent=2) + "\n")
    print(
        f"power done in {time.time() - t0:.1f}s "
        f"recommended_n={power.get('recommended_n_hr15')}"
    )
    for row in power["table"]:
        print(
            f"  N={row['n_chains']} HR={row['hr']} "
            f"H1={row['power_h1']:.3f} H2a={row['power_h2a']:.3f}"
        )

    coding_api = 0.0
    coding_modal = 0.0
    for ledger in (
        root / "runs" / "phase4" / "ledger_pending_4f.jsonl",
        root / "runs" / "phase4_coding" / "ledger_pending_4f.jsonl",
        root / "runs" / "pilot_v1_coding_v3" / "ledger_pending.jsonl",
    ):
        if not ledger.exists():
            continue
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            jid = str(r.get("job_id", ""))
            if "coding" not in jid and "calib" not in jid and "gpt54" not in jid:
                continue
            usd = float(r.get("actual_usd") or r.get("est_usd") or 0)
            if r.get("platform") in {"openai", "openrouter"}:
                coding_api += usd
            elif r.get("platform") == "modal":
                coding_modal += usd

    meta = coding / "gpt54_meta.json"
    if coding_api == 0 and meta.exists():
        m = json.loads(meta.read_text())
        coding_api = float(m.get("usd") or m.get("actual_usd") or m.get("cost_usd") or 0)

    n_llm = max(1, sum(1 for r in coded if not r.get("structural")))
    judging_usd = (
        (coding_modal + coding_api) / n_llm if (coding_modal + coding_api) > 0 else None
    )
    print(f"judging cost modal={coding_modal:.4f} api={coding_api:.4f} per_t={judging_usd}")

    g4 = project_main_run(judging_usd_per_transition=judging_usd)
    g4["judging_modal_usd_pilot"] = coding_modal
    g4["judging_api_usd_pilot"] = coding_api
    g4["decision"] = "D48"
    (out / "g4_projection_d48.json").write_text(json.dumps(g4, indent=2) + "\n")
    print("G4 projections:")
    for p in g4["projections"]:
        print(
            f"  N={p['n_chains']} total=${p['total_usd']:.2f} fits={p['fits_remaining_budget']}"
        )

    levels: dict = {}
    for path in (root / "runs" / "pilot_v1").glob("*/eval_awareness/calls.jsonl"):
        config_id = path.parts[-3]
        scores = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("level") is not None:
                scores.append(int(row["level"]))
        if scores:
            levels[config_id] = {
                "n": len(scores),
                "mean": sum(scores) / len(scores),
                "gte2_rate": sum(1 for s in scores if s >= 2) / len(scores),
            }
    keywords = ("evaluat", "benchmark", "test suite", "grader", "rubric")
    hits: list = []
    notes_n = 0
    for path in (root / "runs" / "pilot_v1").rglob("rounds.jsonl"):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            note = str(row.get("note") or "")
            if not note:
                continue
            notes_n += 1
            low = note.lower()
            for kw in keywords:
                if kw in low:
                    hits.append(
                        {
                            "config_id": path.parts[-3],
                            "keyword": kw,
                            "note": note[:120],
                        }
                    )
                    break
            if len(hits) >= 10:
                break
        if len(hits) >= 10:
            break
    eval_a2 = {
        "levels": levels,
        "keyword_audit": {
            "n_notes_scanned": notes_n,
            "n_hits": len(hits),
            "examples": hits[:10],
        },
    }
    (out / "eval_awareness_a2_d48.json").write_text(json.dumps(eval_a2, indent=2) + "\n")
    (phase4 / "eval_awareness_a2_v3.json").write_text(json.dumps(eval_a2, indent=2) + "\n")
    print("eval A2 levels", {k: v.get("gte2_rate") for k, v in levels.items()})

    done = {
        "stage": "d48_power_g4",
        "state": "done",
        "decision": "D48",
        "primary": "gpt54",
        "recommended_n": power.get("recommended_n_hr15"),
        "subsample_n": sub.get("n_selected"),
        "eval_awareness": eval_a2,
        "spend_usd": spent_modal_usd(root),
        "api_spend_usd": spent_api_usd(root),
        "note": "power+G4 local; MiMo background pending",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "STATUS.json").write_text(json.dumps(done, indent=2) + "\n")
    (phase4 / "STATUS_4f.json").write_text(json.dumps(done, indent=2) + "\n")
    print("DONE power+G4+eval")


if __name__ == "__main__":
    main()
