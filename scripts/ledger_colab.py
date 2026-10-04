#!/usr/bin/env python3
"""Record Colab CU usage and update colab_l4_cu_per_hour in budget.yaml."""

from __future__ import annotations

import argparse

import yaml

from rc.budget import record_actual
from rc.config import repo_root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cu-before", type=float, required=True)
    parser.add_argument("--cu-after", type=float, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--phase", default=2)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    root = repo_root()
    used = args.cu_before - args.cu_after
    if used < 0:
        raise SystemExit("cu-after > cu-before; check the balances")
    rate = used / (args.seconds / 3600.0) if args.seconds > 0 else None

    record_actual(
        job_id=args.job_id,
        phase=args.phase,
        platform="colab",
        gpu="L4",
        max_seconds=int(args.seconds) + 1,
        actual_seconds=args.seconds,
        est_cu=None,
        actual_cu=used,
        note=args.note or f"cu_before={args.cu_before} cu_after={args.cu_after} rate={rate}",
        root=root,
    )

    if rate is not None:
        path = root / "configs" / "budget.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["colab_l4_cu_per_hour"] = float(rate)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        print(f"updated colab_l4_cu_per_hour={rate:.4f}")
    print(f"recorded actual_cu={used:.4f}")


if __name__ == "__main__":
    main()
