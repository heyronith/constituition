"""Map subject compute labels to Modal GPU strings and reservations."""

from __future__ import annotations

COMPUTE_TO_GPU = {
    "modal_l40s": "L40S",
    "modal_a100_80gb": "A100-80GB",
    "modal_h100": "H100",
    "colab_l4": "L4",
}

# Modal container reservations used in preflight (GPU containers also bill these).
COMPUTE_RESERVATIONS = {
    "modal_l40s": {"cpu_cores": 8.0, "memory_gib": 64.0},
    "modal_a100_80gb": {"cpu_cores": 8.0, "memory_gib": 64.0},
    "modal_h100": {"cpu_cores": 8.0, "memory_gib": 64.0},
}


def modal_gpu(compute: str) -> str:
    try:
        return COMPUTE_TO_GPU[compute]
    except KeyError as exc:
        raise KeyError(f"not a Modal compute target: {compute}") from exc
