"""CPU-only Modal smoke. No GPU, no weight download."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import modal

from rc.budget import gpu_price, preflight, record_actual
from rc.guards import assert_modal_workspace

app = modal.App("rc-phase0-smoke-cpu")


@app.function(timeout=60)
def ping() -> dict[str, str]:
    import sys

    return {
        "python": sys.version.split()[0],
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.local_entrypoint()
def main() -> None:
    assert_modal_workspace(expected="heyronith")
    max_seconds = preflight(
        gpu="cpu",
        max_seconds=60,
        phase=0,
        job_id="phase0-smoke-cpu",
        platform="modal",
    )
    estimate = gpu_price("cpu") * max_seconds
    started = time.perf_counter()
    result = ping.remote()
    elapsed = time.perf_counter() - started
    actual_usd = gpu_price("cpu") * elapsed
    record_actual(
        job_id="phase0-smoke-cpu",
        phase=0,
        platform="modal",
        gpu="cpu",
        max_seconds=max_seconds,
        actual_seconds=elapsed,
        est_usd=estimate,
        actual_usd=actual_usd,
        note="CPU-only smoke; remote python {python} at {timestamp_utc}".format(**result),
    )
    print(f"smoke_ok python={result['python']} ts={result['timestamp_utc']} seconds={elapsed:.2f}")
