"""Ensure Volume coding dir records the D60 batch id for resume."""

from __future__ import annotations

import json
import time
from pathlib import Path

import modal

APP_NAME = "rc-phase7a2-seed-batch"
RUNS_VOLUME = "rc-runs"
REMOTE_RUNS = "/rc-runs"
BATCH_ID = "batch_6ac6b190dcdc819087c85c218e21bf8c"
JOB_ID = "phase7a-canary-gpt54-olmo3_7b_final"
RUN_TAG = "main_v1"

app = modal.App(APP_NAME)
runs_vol = modal.Volume.from_name(RUNS_VOLUME, create_if_missing=False)


@app.function(volumes={REMOTE_RUNS: runs_vol}, timeout=120)
def seed() -> dict:
    work = Path(REMOTE_RUNS) / RUN_TAG / "coding" / "gpt54_batch"
    work.mkdir(parents=True, exist_ok=True)
    meta_path = work / f"{JOB_ID}_batch.json"
    prev: dict = {}
    if meta_path.exists():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, ValueError):
            prev = {}
    payload = {
        **prev,
        "batch_id": prev.get("batch_id") or BATCH_ID,
        "n_requests": prev.get("n_requests") or 3148,
        "status": prev.get("status") or "cancelling",
        "d60_seeded": True,
        "seeded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    meta_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    status_path = Path(REMOTE_RUNS) / RUN_TAG / "STATUS.json"
    status: dict = {}
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, ValueError):
            status = {}
    status.update(
        {
            "run_tag": RUN_TAG,
            "stage": "coding",
            "state": "running",
            "config_id": "olmo3_7b_final",
            "batch_ids": {"gpt54": payload["batch_id"]},
            "last_update_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "d60_resume_seed",
        }
    )
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    runs_vol.commit()
    return {"meta": payload, "status_batch_ids": status.get("batch_ids"), "work_dir": str(work)}


@app.local_entrypoint()
def main() -> None:
    print(seed.remote())
