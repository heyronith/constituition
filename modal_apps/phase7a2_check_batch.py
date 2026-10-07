"""Retrieve OpenAI Batch status."""

from __future__ import annotations

import modal

app = modal.App("rc-phase7a2-check-batch")
image = modal.Image.debian_slim(python_version="3.11").pip_install("openai>=1.60")


@app.function(image=image, secrets=[modal.Secret.from_name("openai-key")], timeout=60)
def check(batch_ids: list[str]) -> list[dict]:
    import os

    from openai import OpenAI

    c = OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"))
    out = []
    for bid in batch_ids:
        b = c.batches.retrieve(bid)
        out.append(
            {
                "id": b.id,
                "status": b.status,
                "completed": getattr(b.request_counts, "completed", None),
                "failed": getattr(b.request_counts, "failed", None),
                "total": getattr(b.request_counts, "total", None),
            }
        )
    return out


@app.local_entrypoint()
def main() -> None:
    ids = [
        "batch_6ac69ed0b9788190b0e6f8b7bdfbbff3",
        "batch_6ac697c82fb8819089a03dba6801da20",
    ]
    print(check.remote(ids))
