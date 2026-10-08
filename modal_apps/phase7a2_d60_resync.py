"""D60: sync-recode GPT-5.4 keys that only have error-file stubs (local finalize)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import modal

APP = "rc-phase7a2-d60-resync"
RUNS = "rc-runs"
REMOTE = "/rc-runs"
JOB = "phase7a-canary-gpt54-olmo3_7b_final"
VALID = "batch_6ac6b190dcdc819087c85c218e21bf8c"

app = modal.App(APP)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("openai>=1.60", "pydantic>=2", "pyyaml", "python-dotenv")
    .add_local_dir("src", remote_path="/rc/src")
    .add_local_dir("configs", remote_path="/rc/configs")
    .add_local_dir("materials", remote_path="/rc/materials")
    .add_local_file("pyproject.toml", remote_path="/rc/pyproject.toml")
)
vol = modal.Volume.from_name(RUNS, create_if_missing=False)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("openai-key")],
    volumes={REMOTE: vol},
    timeout=1800,
)
def resync() -> dict:
    import os
    import sys

    sys.path.insert(0, "/rc/src")
    os.chdir("/rc")
    # Point runs at Volume
    runs_link = Path("/rc/runs")
    if runs_link.exists() or runs_link.is_symlink():
        if runs_link.is_symlink() or runs_link.is_file():
            runs_link.unlink()
        else:
            import shutil

            shutil.rmtree(runs_link)
    runs_link.symlink_to(REMOTE)

    from openai import OpenAI

    from rc.budget import record_actual
    from rc.judging import parse_fate_response
    from rc.openai_batch import _usage_usd, request_body_sha256

    coding = Path(REMOTE) / "main_v1" / "coding"
    bd = coding / "gpt54_batch"

    def load_jsonl(p: Path) -> list[dict]:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    out = {r["custom_id"]: r for r in load_jsonl(bd / f"{JOB}_output.jsonl")}
    inp = load_jsonl(bd / f"{JOB}_input.jsonl")
    inp_by = {r["custom_id"]: r for r in inp}
    missing = sorted(set(inp_by) - set(out))
    rows = load_jsonl(coding / "gpt54.jsonl")
    llm_idx = [i for i, r in enumerate(rows) if not r.get("structural")]
    if len(llm_idx) != 3148:
        raise RuntimeError(f"expected 3148 llm rows, got {len(llm_idx)}")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    sync_usd = 0.0
    sync_records = []
    details = []
    for cid in missing:
        i = int(cid.split("-")[1])
        body = inp_by[cid]["body"]
        body_sha = request_body_sha256(body)
        last_err = None
        delay = 1.0
        resp_body = None
        for _attempt in range(5):
            try:
                resp = client.chat.completions.create(**body)
                resp_body = resp.model_dump()
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        if resp_body is None:
            raise RuntimeError(f"sync failed {cid}: {last_err}")
        usage = resp_body.get("usage") or {}
        inp_t, _cached, out_t, usd = _usage_usd(usage, sync=True)
        sync_usd += usd
        content = ((resp_body.get("choices") or [{}])[0].get("message") or {}).get(
            "content"
        ) or ""
        parsed = parse_fate_response(content)
        row_i = llm_idx[i]
        old = rows[row_i]
        rows[row_i] = {
            **old,
            "fate": parsed.fate,
            "strength": parsed.strength,
            "rationale": parsed.rationale,
            "situation": parsed.situation,
            "parse_status": parsed.parse_status,
            "raw_text": content,
            "finish_reason": ((resp_body.get("choices") or [{}])[0].get("finish_reason")),
            "n_prompt_tokens": inp_t,
            "n_output_tokens": out_t,
            "submit_mode": "sync",
            "request_body_sha256": body_sha,
            "source_batch_id": VALID,
            "source_file": "sync_straggler_d60",
            "source_custom_id": cid,
            "provenance_note": "error_file_http500_recode_sync",
        }
        sync_records.append(
            {
                "custom_id": cid,
                "response": {"status_code": 200, "body": resp_body},
                "error": None,
                "_submit_mode": "sync",
                "_sync": True,
            }
        )
        details.append(
            {
                "custom_id": cid,
                "judgment_key": old.get("judgment_key") or old.get("transition_id"),
                "fate": parsed.fate,
                "parse_status": parsed.parse_status,
                "usd": usd,
            }
        )

    with (coding / "gpt54.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")

    merged_path = bd / f"{JOB}_merged_output.jsonl"
    merged = {r["custom_id"]: r for r in load_jsonl(merged_path)}
    for rec in sync_records:
        merged[rec["custom_id"]] = rec
    # Mark successful batch rows
    for cid, row in out.items():
        row = dict(row)
        row["_submit_mode"] = "batch"
        merged[cid] = row
    with merged_path.open("w", encoding="utf-8") as fh:
        for i in range(len(inp)):
            fh.write(json.dumps(merged[f"req-{i}"], sort_keys=True) + "\n")

    meta = json.loads((coding / "gpt54_meta.json").read_text(encoding="utf-8"))
    batch_usd = float(meta.get("batch_usd") or meta.get("api_usd") or 0.0)
    meta.update(
        {
            "n_batch": 3138,
            "n_sync": 10,
            "sync_usd": sync_usd,
            "batch_usd": batch_usd,
            "api_usd": batch_usd + sync_usd,
            "d60_resync": True,
            "resync_custom_ids": missing,
            "batch_id": VALID,
        }
    )
    (coding / "gpt54_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    cost = json.loads((bd / f"{JOB}_cost.json").read_text(encoding="utf-8"))
    cost.update(
        {
            "n_sync": 10,
            "sync_usd": sync_usd,
            "usd": float(cost.get("batch_usd") or 0) + sync_usd,
            "d60_resync": True,
        }
    )
    (bd / f"{JOB}_cost.json").write_text(
        json.dumps(cost, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Ledger on Volume is not the repo ledger; return payload for local record_actual.
    vol.commit()
    return {"sync_usd": sync_usd, "n": len(missing), "details": details, "meta": meta}


@app.local_entrypoint()
def main() -> None:
    print(json.dumps(resync.remote(), indent=2, sort_keys=True))
