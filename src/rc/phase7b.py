"""Phase 7B helpers: per-config isolation, API guard, Batch stagger, canary protection (D62/D63)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal

from rc.config import load_models, repo_root
from rc.io_utils import sha256_file

MAIN_RUN_TAG = "main_v1"
CANARY_CONFIG = "olmo3_7b_final"
SMOKE_ID = "qwen35_08b_smoke"
REMAINING_CONFIGS = (
    "qwen38_27b_nothink",
    "qwen38_27b_think",
    "gemma4_31b",
    "gemma4_12b",
    "olmo3_7b_sft",
    "olmo3_7b_dpo",
)

# D62 caps (human-approved 2026-10-07).
API_CAP_USD = 52.0
OPENAI_CAP_USD = 49.0
OPENROUTER_CAP_USD = 3.0
MODAL_CAP_USD = 130.0

# D70: OpenAI spend floor for the project-cap guard.
# Session-1 dashboard GT ($12.77) + unique 7B Volume OpenAI jobs ($27.30007125).
# Prompt Session 4 left dashboard blank; reconstructed GT used until human overrides
# via materials/main_run/refs/openai_dashboard_usd.json.
OPENAI_DASHBOARD_USD = 40.07

COMPUTE_GPU = {
    "modal_a100_80gb": "A100-80GB",
    "modal_l40s": "L40S",
    "modal_l4": "L4",
}

BatchErrorKind = Literal["rate_limit", "billing", "other"]
CodingHoldState = Literal["api_budget_hold", "api_billing_wait", "api_wait", "failed"]

# D67: provider billing recovery (not project-cap holds).
PROVIDER_BILLING_PROBE_INTERVAL_S = 1800.0
PROVIDER_BILLING_MAX_WAIT_S = 86400.0


@dataclass
class Caps:
    api: float = API_CAP_USD
    openai: float = OPENAI_CAP_USD
    openrouter: float = OPENROUTER_CAP_USD
    modal: float = MODAL_CAP_USD


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_filename(config_id: str) -> str:
    return f"STATUS_{config_id}.json"


def status_path(run_tag: str, config_id: str, *, root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "runs" / run_tag / status_filename(config_id)


def ledger_path(run_tag: str, config_id: str, *, root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "budget" / f"ledger_{run_tag}_{config_id}.jsonl"


def batch_lock_path(*, root: Path | None = None) -> Path:
    root = root or repo_root()
    return root / "runs" / MAIN_RUN_TAG / "_locks" / "openai_batch_submit.lock"


# D68: orphaned submit locks are stealable after TTL.
BATCH_LOCK_TTL_S = 3600.0
CODING_STATUS_HEARTBEAT_S = 900.0


def gpu_for_config(config_id: str, *, root: Path | None = None) -> str:
    root = root or repo_root()
    subject = load_models(root).by_id(config_id)
    return COMPUTE_GPU.get(subject.compute, "A100-80GB")


def assert_not_canary_write(path: Path, *, root: Path | None = None) -> None:
    """D63: refuse writes under the canary config directory."""
    root = root or repo_root()
    canary = (root / "runs" / MAIN_RUN_TAG / CANARY_CONFIG).resolve()
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path.absolute()
    if canary == resolved or canary in resolved.parents:
        raise PermissionError(f"D63 canary read-only: refusing write to {path}")


def snapshot_canary_tree(*, root: Path | None = None) -> dict[str, str]:
    root = root or repo_root()
    base = root / "runs" / MAIN_RUN_TAG / CANARY_CONFIG
    if not base.exists():
        raise FileNotFoundError(f"missing canary tree {base}")
    out: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(base))
            out[rel] = sha256_file(path)
    return out


def verify_canary_snapshot(
    snapshot: dict[str, str], *, root: Path | None = None
) -> dict[str, Any]:
    root = root or repo_root()
    current = snapshot_canary_tree(root=root)
    missing = sorted(set(snapshot) - set(current))
    added = sorted(set(current) - set(snapshot))
    changed = sorted(k for k in snapshot if k in current and snapshot[k] != current[k])
    return {
        "ok": not missing and not added and not changed,
        "n_snapshot": len(snapshot),
        "n_current": len(current),
        "missing": missing[:20],
        "added": added[:20],
        "changed": changed[:20],
    }


def classify_openai_batch_error(exc_or_text: Any) -> BatchErrorKind:
    """Classify OpenAI Batch/create failures for D63/D67 resume.

    OpenAI returns HTTP 429 for ``insufficient_quota``; that must be **billing**
    (D67: ``api_billing_wait``), never a rate-limit retry loop. Project-cap
    denials from ``api_submission_allowed`` are a separate hard ``api_budget_hold``.
    """
    text = str(exc_or_text).lower()
    billing_markers = (
        "billing",
        "spending limit",
        "billing_hard_limit",
        "hard limit has been reached",
        "insufficient_quota",
        "payment",
        "exceeded your current quota",
        "exceeded your quota",
    )
    if any(s in text for s in billing_markers):
        return "billing"
    # 429 + quota/billing wording → billing (OpenAI quota exhaustion).
    if "429" in text and any(
        s in text for s in ("quota", "billing", "payment", "hard limit")
    ):
        return "billing"
    if any(
        s in text
        for s in (
            "rate limit",
            "rate_limit",
            "enqueued",
            "token limit",
            "tokens_enqueued",
            "too many requests",
            "capacity",
        )
    ):
        return "rate_limit"
    # Bare 429 without quota markers → rate limit / capacity.
    if "429" in text:
        return "rate_limit"
    return "other"


def disposition_for_coding_failure(
    *,
    kind: BatchErrorKind | None = None,
    project_cap_blocked: bool = False,
) -> CodingHoldState:
    """Map a coding failure to STATUS state (D62/D63/D67).

    Project-cap guard → hard ``api_budget_hold`` (never auto-retried).
    Provider billing → ``api_billing_wait`` (D67 probe/resume).
    """
    if project_cap_blocked:
        return "api_budget_hold"
    if kind is None:
        raise ValueError("kind required when project_cap_blocked is False")
    if kind == "billing":
        return "api_billing_wait"
    if kind == "rate_limit":
        return "api_wait"
    return "failed"


def probe_openai_billing_ok() -> bool:
    """One cheap OpenAI request; False only while provider billing still blocks."""
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=key)
    try:
        # models.list is near-zero cost and fails under billing hard limits.
        client.models.list()
        return True
    except Exception as exc:  # noqa: BLE001
        return classify_openai_batch_error(exc) != "billing"


def wait_for_provider_billing(
    *,
    probe_fn: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_status: Callable[[dict[str, Any]], None] | None = None,
    interval_s: float = PROVIDER_BILLING_PROBE_INTERVAL_S,
    max_wait_s: float = PROVIDER_BILLING_MAX_WAIT_S,
    error: str = "",
    clock: Callable[[], float] | None = None,
) -> bool:
    """D67: STATUS=api_billing_wait; re-probe every interval_s up to max_wait_s.

    Returns True if a probe succeeds (billing recovered). Never used for
    project-cap ``api_budget_hold``.
    """
    probe = probe_fn or probe_openai_billing_ok
    now = clock or time.time
    started = now()
    probe_n = 0
    while True:
        if on_status is not None:
            on_status(
                {
                    "state": "api_billing_wait",
                    "error": str(error)[:500],
                    "billing_probe": probe_n,
                    "billing_wait_s": now() - started,
                }
            )
        remaining = max_wait_s - (now() - started)
        if remaining <= 0:
            if on_status is not None:
                on_status(
                    {
                        "state": "api_billing_wait",
                        "error": f"provider_billing_exhausted_24h: {error}"[:500],
                        "billing_probe": probe_n,
                        "billing_wait_s": now() - started,
                    }
                )
            return False
        sleep_fn(min(interval_s, remaining))
        probe_n += 1
        if probe():
            return True
        if now() - started >= max_wait_s:
            if on_status is not None:
                on_status(
                    {
                        "state": "api_billing_wait",
                        "error": f"provider_billing_exhausted_24h: {error}"[:500],
                        "billing_probe": probe_n,
                        "billing_wait_s": now() - started,
                    }
                )
            return False


def load_openai_dashboard_usd(root: Path | None = None) -> float:
    """D70 human OpenAI Usage dashboard GT (override file), else OPENAI_DASHBOARD_USD."""
    root = root or repo_root()
    path = root / "materials" / "main_run" / "refs" / "openai_dashboard_usd.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return float(payload["openai_dashboard_usd"])
    return float(OPENAI_DASHBOARD_USD)


def sum_ledgers_api(
    run_tag: str = MAIN_RUN_TAG, *, root: Path | None = None
) -> dict[str, float]:
    """Sum OpenAI/OpenRouter from all per-config ledgers + repo ledger.

    D70: dedupe ledger *paths* by ``resolve()`` so a ``budget/`` symlink to
    Volume ``runs/<tag>/budget`` is never double-counted (this produced the
    false ``openai 60.76`` guard figure: 2×$27.30 + Batch estimate).
    """
    root = root or repo_root()
    totals = {"openai": 0.0, "openrouter": 0.0, "modal": 0.0}
    candidates = [root / "budget" / "ledger.jsonl"]
    candidates.extend(sorted((root / "budget").glob(f"ledger_{run_tag}_*.jsonl")))
    vol_budget = root / "runs" / run_tag / "budget"
    if vol_budget.exists():
        candidates.extend(sorted(vol_budget.glob(f"ledger_{run_tag}_*.jsonl")))
    seen_paths: set[Path] = set()
    for path in candidates:
        if not path.exists():
            continue
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen_paths:
            continue
        seen_paths.add(key)
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            plat = row.get("platform")
            if plat not in totals:
                continue
            totals[plat] += float(row.get("actual_usd") or row.get("est_usd") or 0.0)
    return totals


def api_submission_allowed(
    estimate_usd: float,
    *,
    platform: str = "openai",
    caps: Caps | None = None,
    root: Path | None = None,
    openai_spent_floor: float | None = None,
) -> tuple[bool, str]:
    """Global API guard before Batch submit (D62/D63/D70)."""
    caps = caps or Caps()
    spent = sum_ledgers_api(root=root)
    # D70: floor = reconciled OpenAI dashboard GT (not the stale $12.77 alone).
    if openai_spent_floor is None:
        openai_spent_floor = load_openai_dashboard_usd(root)
    oa = max(spent["openai"], float(openai_spent_floor))
    or_ = spent["openrouter"]
    if platform == "openai":
        if oa + estimate_usd > caps.openai:
            return False, f"openai {oa + estimate_usd:.4f} > cap {caps.openai}"
        if oa + or_ + estimate_usd > caps.api:
            return False, f"api total {oa + or_ + estimate_usd:.4f} > cap {caps.api}"
    elif platform == "openrouter":
        if or_ + estimate_usd > caps.openrouter:
            return False, f"openrouter {or_ + estimate_usd:.4f} > cap {caps.openrouter}"
        if oa + or_ + estimate_usd > caps.api:
            return False, f"api total {oa + or_ + estimate_usd:.4f} > cap {caps.api}"
    return True, "ok"


def acquire_batch_submit_lock(
    config_id: str,
    *,
    root: Path | None = None,
    min_gap_s: float = 600.0,
    poll_s: float = 15.0,
    max_wait_s: float = 7200.0,
    ttl_s: float = BATCH_LOCK_TTL_S,
) -> None:
    """Stagger OpenAI Batch submissions ≥ min_gap_s between configs (Volume lock).

    D68: locks older than ``ttl_s`` are treated as orphaned and may be stolen.
    Callers must ``release_batch_submit_lock`` in a ``finally`` block.
    """
    root = root or repo_root()
    path = batch_lock_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    while True:
        now = time.time()
        if now - started > max_wait_s:
            raise TimeoutError(f"batch submit lock wait exceeded for {config_id}")
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = {}
        last_ts = float(payload.get("unix") or 0.0)
        last_cfg = payload.get("config_id")
        age = now - last_ts
        orphaned = bool(last_ts) and age > ttl_s
        gap_ok = age >= min_gap_s or not last_ts
        # Same config, stagger gap elapsed, or D68 orphaned TTL → acquire.
        if last_cfg == config_id or orphaned or gap_ok:
            path.write_text(
                json.dumps(
                    {
                        "config_id": config_id,
                        "unix": now,
                        "utc": utc_now(),
                        "pid": os.getpid(),
                        "held": True,
                        "orphaned_steal": orphaned and last_cfg != config_id,
                        "prior_config_id": last_cfg if orphaned else None,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            return
        time.sleep(poll_s)


def release_batch_submit_lock(
    config_id: str,
    *,
    root: Path | None = None,
) -> bool:
    """D68: release lock if we hold it; keep unix for submit stagger."""
    root = root or repo_root()
    path = batch_lock_path(root=root)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if payload.get("config_id") != config_id:
        return False
    if not payload.get("held", True):
        return False
    payload["held"] = False
    payload["released_utc"] = utc_now()
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return True


def lock_is_orphaned(
    payload: dict[str, Any],
    *,
    now: float | None = None,
    ttl_s: float = BATCH_LOCK_TTL_S,
) -> bool:
    """True if a lock payload is past TTL (D68)."""
    now = time.time() if now is None else now
    last_ts = float(payload.get("unix") or 0.0)
    if not last_ts:
        return True
    return (now - last_ts) > ttl_s


class CodingStatusHeartbeat:
    """Write STATUS at least every ``interval_s`` during coding sub-stages."""

    def __init__(
        self,
        write_fn: Callable[..., None],
        *,
        interval_s: float = CODING_STATUS_HEARTBEAT_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._write = write_fn
        self.interval_s = interval_s
        self._clock = clock or time.time
        self._last: float | None = None
        self.substage = "coding"

    def pulse(self, substage: str | None = None, *, force: bool = False, **extra: Any) -> bool:
        if substage is not None:
            self.substage = substage
        now = self._clock()
        if (
            not force
            and self._last is not None
            and (now - self._last) < self.interval_s
        ):
            return False
        self._write(
            stage="coding",
            state="running",
            coding_substage=self.substage,
            **extra,
        )
        self._last = now
        return True


def append_config_ledger(
    *,
    run_tag: str,
    config_id: str,
    platform: str,
    actual_usd: float,
    job_id: str,
    note: str,
    root: Path | None = None,
    gpu: str = "none",
) -> None:
    root = root or repo_root()
    # Prefer Volume-visible path under runs/ for cross-app reads.
    path = root / "runs" / run_tag / "budget" / f"ledger_{run_tag}_{config_id}.jsonl"
    assert_not_canary_write(path, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_utc": utc_now(),
        "job_id": job_id,
        "phase": "7b",
        "platform": platform,
        "gpu": gpu,
        "actual_usd": actual_usd,
        "config_id": config_id,
        "note": note,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


# Task-rule / model-behaviour parse errors (not harness).
_TASK_RULE_MARKERS = (
    "revise text identical",
    "duplicate id",
    "unknown id",
    "missing id",
    "two changes",
    "keep requires",
    "revise requires",
    "merge requires",
    "merge with itself",
    "merge chains",
    "empty paraphrase",
    "paraphrase requires",
    "added principle",
    "requires text=null",
    "requires non-empty text",
    "merge_with unknown",
    "merge target",
    "decision must be keep/revise",
)
_HARNESS_MARKERS = (
    "no json",
    "unterminated",
    "trailing prose",
    "leading prose",
    "invalid structured",
    "invalid forced output",
    "invalid forced paraphrase",
    "template",
    "render",
)


def classify_parse_failure(
    finish_reason: Any, parse_error: Any
) -> Literal["harness", "model_behaviour", "unknown"]:
    """Operational failure class (D63/D65). No clause-category labels."""
    fr = str(finish_reason or "").lower()
    pe = str(parse_error or "").lower()
    if fr == "length":
        return "harness"
    if any(m in pe for m in _TASK_RULE_MARKERS):
        return "model_behaviour"
    if any(m in pe for m in _HARNESS_MARKERS):
        return "harness"
    if "json" in pe or "schema" in pe:
        return "harness"
    if pe or fr:
        return "unknown"
    return "unknown"


def parse_tripwire_stats(
    run_tag: str,
    config_id: str,
    *,
    root: Path | None = None,
    after_round: int = 3,
    mode: str = "legacy",
) -> dict[str, Any]:
    """After FORCED round ``after_round``, decide parse_hold.

    ``mode=legacy`` (D63): trip if parse_rate < 0.90 or censor_frac > 0.10.
    ``mode=harness_frac`` (D65 gemma4_12b): trip only if any round ≤ after_round
    has ≥10% of its failed attempts classified as harness-type.
    """
    root = root or repo_root()
    base = root / "runs" / run_tag / config_id / "FORCED"
    n_chains = n_censored = n_ok = n_fail = 0
    failed_samples: list[dict[str, Any]] = []
    by_round_fail: dict[int, dict[str, int]] = {}
    if not base.exists():
        return {"ok": True, "n_chains": 0, "mode": mode}
    for chain_dir in sorted(p for p in base.rglob("chain_*") if p.is_dir()):
        n_chains += 1
        meta_path = chain_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        cens = meta.get("censored_at_round")
        if cens is not None and int(cens) <= after_round:
            n_censored += 1
        rp = chain_dir / "rounds.jsonl"
        if not rp.exists():
            continue
        for line in rp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rnd = int(row.get("round", -1))
            if rnd > after_round:
                continue
            if row.get("parse_status") == "ok":
                n_ok += 1
            else:
                n_fail += 1
                kind = classify_parse_failure(row.get("finish_reason"), row.get("parse_error"))
                slot = by_round_fail.setdefault(
                    rnd, {"fail": 0, "harness": 0, "model_behaviour": 0, "unknown": 0}
                )
                slot["fail"] += 1
                slot[kind] += 1
                if len(failed_samples) < 10:
                    failed_samples.append(
                        {
                            "chain": chain_dir.name,
                            "round": row.get("round"),
                            "finish_reason": row.get("finish_reason"),
                            "parse_error": row.get("parse_error"),
                            "failure_class": kind,
                            "text_final": (row.get("text_final") or "")[:2000],
                        }
                    )
    parse_rate = n_ok / max(n_ok + n_fail, 1)
    censor_frac = n_censored / max(n_chains, 1)
    harness_rounds: list[dict[str, Any]] = []
    if mode == "harness_frac":
        trip = False
        for rnd, s in sorted(by_round_fail.items()):
            if s["fail"] <= 0:
                continue
            frac = s["harness"] / s["fail"]
            harness_rounds.append({"round": rnd, "harness_frac": frac, **s})
            if frac >= 0.10:
                trip = True
    else:
        trip = parse_rate < 0.90 or censor_frac > 0.10
    return {
        "ok": not trip,
        "trip": trip,
        "mode": mode,
        "parse_rate": parse_rate,
        "censor_frac": censor_frac,
        "n_chains": n_chains,
        "n_censored": n_censored,
        "harness_by_round": harness_rounds,
        "failed_samples": failed_samples,
    }


# Canary PERMISSIVE/FORCED per-unit-round wall-time ratio (D64).
CANARY_PERM_FORCED_RATIO = 1.65
PERM_EST_SAFETY = 1.5


def estimate_permissive_usd(
    *,
    forced_modal_usd: float,
    forced_unit_rounds: int,
    permissive_unit_rounds: int,
    canary_ratio: float = CANARY_PERM_FORCED_RATIO,
    safety: float = PERM_EST_SAFETY,
) -> float:
    """D64: measured FORCED $/unit-round × PERMISSIVE unit-rounds × 1.65 × 1.5."""
    if forced_unit_rounds <= 0:
        raise ValueError("forced_unit_rounds must be positive")
    if forced_modal_usd < 0:
        raise ValueError("forced_modal_usd must be non-negative")
    return (
        (forced_modal_usd / forced_unit_rounds)
        * permissive_unit_rounds
        * canary_ratio
        * safety
    )


def count_protocol_unit_rounds(
    run_tag: str,
    config_id: str,
    protocol: str,
    *,
    root: Path | None = None,
) -> int:
    """Count completed generation rows (ok or failed) under a protocol."""
    root = root or repo_root()
    base = root / "runs" / run_tag / config_id / protocol
    n = 0
    if not base.exists():
        return 0
    for rp in base.rglob("rounds.jsonl"):
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                n += 1
    return n


def forced_protocol_complete(
    run_tag: str,
    config_id: str,
    *,
    forced_chains: list[int],
    conditions: list[str],
    forced_rounds: int,
    root: Path | None = None,
) -> bool:
    """True iff every FORCED chain has ``forced_rounds`` rows or was censored earlier."""
    root = root or repo_root()
    for cond in conditions:
        for ch in forced_chains:
            cdir = (
                root
                / "runs"
                / run_tag
                / config_id
                / "FORCED"
                / cond
                / "STRUCTURED"
                / f"chain_{ch}"
            )
            meta_path = cdir / "meta.json"
            rp = cdir / "rounds.jsonl"
            if not rp.exists():
                return False
            rows = [json.loads(l) for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            cens = meta.get("censored_at_round")
            if cens is not None:
                continue
            if len(rows) < forced_rounds:
                return False
    return True


def is_stale_status(
    payload: dict[str, Any], *, now: datetime | None = None, stale_hours: float = 2.0
) -> bool:
    """D63: STALE if no update >2h and not in a known waiting state."""
    state = str(payload.get("state") or "")
    waiting = {
        "api_wait",
        "api_billing_wait",
        "mimo_wait",
        "api_budget_hold",
        "budget_hold",
        "parse_hold",
        "running",
    }
    # Batch in_progress within D60 window is not stale.
    batch_state = str((payload.get("batch_state") or payload.get("batch_status") or ""))
    if batch_state in {"in_progress", "validating", "finalizing", "cancelling"}:
        return False
    if state in {"done", "failed", "canary_fail", "budget_stop"}:
        return False
    if state in waiting and state != "running":
        return False
    last = payload.get("last_update_utc")
    if not last:
        return True
    try:
        ts = datetime.strptime(str(last), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() > stale_hours * 3600
