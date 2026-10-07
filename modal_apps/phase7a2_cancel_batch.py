"""One-shot: cancel the stale canary OpenAI Batch (D59 §0)."""

from __future__ import annotations

import modal

app = modal.App("rc-phase7a2-cancel")
image = modal.Image.debian_slim(python_version="3.11").pip_install("openai>=1.60")
BATCH_ID = "batch_6ac697c82fb8819089a03dba6801da20"


@app.function(image=image, secrets=[modal.Secret.from_name("openai-key")], timeout=120)
def cancel_batch() -> dict:
    import os

    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    client = OpenAI(api_key=key)
    try:
        b = client.batches.cancel(BATCH_ID)
    except Exception as exc:  # already cancelled / terminal
        b = client.batches.retrieve(BATCH_ID)
        return {
            "id": b.id,
            "status": b.status,
            "cancel_error": str(exc)[:300],
            "counts": {
                "completed": getattr(b.request_counts, "completed", None),
                "failed": getattr(b.request_counts, "failed", None),
                "total": getattr(b.request_counts, "total", None),
            },
        }
    return {
        "id": b.id,
        "status": b.status,
        "counts": {
            "completed": getattr(b.request_counts, "completed", None),
            "failed": getattr(b.request_counts, "failed", None),
            "total": getattr(b.request_counts, "total", None),
        },
    }


@app.local_entrypoint()
def main() -> None:
    print(cancel_batch.remote())
