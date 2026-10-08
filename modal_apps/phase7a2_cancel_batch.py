"""Cancel an OpenAI Batch and wait for a terminal state (D59/D60)."""

from __future__ import annotations

import modal

app = modal.App("rc-phase7a2-cancel")
image = modal.Image.debian_slim(python_version="3.11").pip_install("openai>=1.60")
DEFAULT_BATCH = "batch_6ac6b190dcdc819087c85c218e21bf8c"


@app.function(image=image, secrets=[modal.Secret.from_name("openai-key")], timeout=1800)
def cancel_batch(batch_id: str = DEFAULT_BATCH) -> dict:
    import os
    import time

    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    client = OpenAI(api_key=key)
    try:
        b = client.batches.cancel(batch_id)
    except Exception as exc:
        b = client.batches.retrieve(batch_id)
        err = str(exc)[:300]
    else:
        err = None
    for _ in range(180):
        b = client.batches.retrieve(batch_id)
        if b.status in {"cancelled", "completed", "failed", "expired"}:
            if b.status != "cancelled" or b.output_file_id:
                break
        time.sleep(5)
    return {
        "id": b.id,
        "status": b.status,
        "cancel_error": err,
        "counts": {
            "completed": getattr(b.request_counts, "completed", None),
            "failed": getattr(b.request_counts, "failed", None),
            "total": getattr(b.request_counts, "total", None),
        },
        "output_file_id": b.output_file_id,
        "error_file_id": getattr(b, "error_file_id", None),
    }


@app.local_entrypoint()
def main(batch_id: str = DEFAULT_BATCH) -> None:
    print(cancel_batch.remote(batch_id))
