#!/usr/bin/env python3
"""OLMo generation on Colab L4. Checkpoints each round for resume after disconnect.

Launch as a background process from colab_job.sh and poll status.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


def _status_path(out_root: Path) -> Path:
    return out_root / "status.json"


def write_status(out_root: Path, **fields: object) -> None:
    path = _status_path(out_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(fields)
    current["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", nargs="+", required=True)
    parser.add_argument("--phase", type=int, default=2)
    parser.add_argument(
        "--run-tag",
        default=None,
        help="Override run tag (phase3_olmo_check, pilot_v1, …)",
    )
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument(
        "--chains",
        type=int,
        nargs="+",
        default=None,
        help="Chain indices (default: [0] for dryrun/check, [100,101,102] for pilot)",
    )
    parser.add_argument(
        "--mode",
        choices=("dryrun", "olmo_check", "pilot"),
        default="dryrun",
    )
    parser.add_argument("--out-root", type=Path, default=Path("/content/rc-runs"))
    parser.add_argument("--repo-root", type=Path, default=Path("/content/constituition"))
    parser.add_argument("--skip-endorsement", action="store_true")
    parser.add_argument("--skip-realism", action="store_true")
    parser.add_argument("--endorsement-reps", type=int, default=None)
    args = parser.parse_args()

    if args.mode == "olmo_check":
        run_tag = args.run_tag or "phase3_olmo_check"
        rounds = args.rounds if args.rounds is not None else 2
        chains = args.chains or [0]
        endorse_reps = 0 if args.skip_endorsement else (args.endorsement_reps or 0)
        do_realism = False
    elif args.mode == "pilot":
        run_tag = args.run_tag or "pilot_v1"
        rounds = args.rounds if args.rounds is not None else 10
        chains = args.chains or [100, 101, 102]
        endorse_reps = 0 if args.skip_endorsement else (args.endorsement_reps or 5)
        do_realism = False
    else:
        run_tag = args.run_tag or "phase2b_dryrun"
        rounds = args.rounds if args.rounds is not None else 2
        chains = args.chains or [0]
        endorse_reps = 0 if args.skip_endorsement else (args.endorsement_reps or 1)
        do_realism = not args.skip_realism

    sys.path.insert(0, str(args.repo_root / "src"))
    out_root = args.out_root
    # Symlink repo runs/ to out_root so chain_runner writes land on the durable path.
    runs_link = args.repo_root / "runs"
    if runs_link.is_symlink() or runs_link.is_file():
        runs_link.unlink()
    elif runs_link.exists():
        import shutil

        shutil.rmtree(runs_link)
    out_root.mkdir(parents=True, exist_ok=True)
    runs_link.symlink_to(out_root)

    write_status(
        out_root,
        state="starting",
        configs=args.configs,
        phase=args.phase,
        mode=args.mode,
        run_tag=run_tag,
    )
    try:
        from huggingface_hub import snapshot_download

        from rc.chain_runner import (
            Unit,
            run_config,
            run_endorsement,
            run_eval_awareness,
            run_realism_audit,
        )
        from rc.config import load_vllm
        from rc.generation import VLLMBackend, load_lock_revision, max_model_len_for
        from rc.pilot import sample_eval_awareness_records

        root = args.repo_root
        vllm_cfg = load_vllm(root)
        started = time.perf_counter()

        for cid in args.configs:
            write_status(out_root, state="loading", config_id=cid)
            repo, rev = load_lock_revision(cid, root)
            model_path = snapshot_download(repo_id=repo, revision=rev)
            load_t0 = time.perf_counter()
            backend = VLLMBackend(
                cid,
                model_path=model_path,
                revision=None,
                max_model_len=max_model_len_for(cid, root),
                gpu_memory_utilization=vllm_cfg.gpu_memory_utilization,
                enforce_eager=False,
                max_num_seqs=16 if cid.startswith("olmo3_7b") else vllm_cfg.max_num_seqs,
                root=root,
            )
            load_s = time.perf_counter() - load_t0
            write_status(
                out_root,
                state="running",
                config_id=cid,
                model_load_s=load_s,
                graph_capture_s=getattr(backend, "graph_capture_s", None),
            )
            conditions = [
                "SELF_REFLECT",
                "OTHER_REFLECT",
                "PARAPHRASE",
                "NEUTRAL_EDIT",
            ]
            units = [
                Unit(protocol, cond, "STRUCTURED", chain)
                for protocol in ("PERMISSIVE", "FORCED")
                for cond in conditions
                for chain in chains
            ]
            run_config(
                backend,
                cid,
                units,
                rounds=rounds,
                run_tag=run_tag,
                root=root,
            )
            write_status(out_root, last_cell=f"{cid}/batched")
            if endorse_reps > 0:
                run_endorsement(
                    backend,
                    cid,
                    reps=endorse_reps,
                    forms=("A", "B"),
                    run_tag=run_tag,
                    root=root,
                )
            if do_realism:
                run_realism_audit(backend, cid, reps=3, run_tag="phase2b_realism_audit", root=root)
            if args.mode in {"olmo_check", "pilot"}:
                records = sample_eval_awareness_records(
                    run_tag, cid, root=root, fraction=0.10 if args.mode == "pilot" else 0.0
                )
                if records:
                    run_eval_awareness(backend, cid, records, run_tag=run_tag, root=root)
            del backend

        elapsed = time.perf_counter() - started
        write_status(out_root, state="done", elapsed_s=elapsed)
        return 0
    except Exception as exc:
        write_status(
            out_root,
            state="error",
            error=str(exc),
            traceback=traceback.format_exc()[-4000:],
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
