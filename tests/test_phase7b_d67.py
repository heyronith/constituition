"""D67: provider billing → api_billing_wait; project-cap → hard api_budget_hold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rc.phase7b import (
    classify_openai_batch_error,
    disposition_for_coding_failure,
    is_stale_status,
    wait_for_provider_billing,
)


def test_provider_billing_disposition_is_billing_wait_not_hard_hold() -> None:
    for msg in (
        "Error code: 429 - {'error': {'code': 'insufficient_quota'}}",
        "Error code: 400 - {'error': {'code': 'billing_hard_limit_reached'}}",
        "Billing hard limit has been reached",
    ):
        kind = classify_openai_batch_error(msg)
        assert kind == "billing"
        assert disposition_for_coding_failure(kind=kind) == "api_billing_wait"
        assert disposition_for_coding_failure(kind=kind) != "api_budget_hold"


def test_project_cap_guard_remains_hard_hold_never_auto_retry() -> None:
    """D62/D63 api_submission_allowed denial must stay api_budget_hold."""
    assert (
        disposition_for_coding_failure(project_cap_blocked=True)
        == "api_budget_hold"
    )
    # Cap-hold path ignores provider error kind entirely.
    assert (
        disposition_for_coding_failure(
            kind="billing", project_cap_blocked=True
        )
        == "api_budget_hold"
    )


def test_wait_for_provider_billing_recovers_after_probes() -> None:
    sleeps: list[float] = []
    statuses: list[dict] = []
    probes = {"n": 0}

    def probe() -> bool:
        probes["n"] += 1
        return probes["n"] >= 2

    t = {"now": 0.0}

    def clock() -> float:
        return t["now"]

    def sleep_fn(s: float) -> None:
        sleeps.append(s)
        t["now"] += s

    ok = wait_for_provider_billing(
        probe_fn=probe,
        sleep_fn=sleep_fn,
        on_status=statuses.append,
        interval_s=30.0,
        max_wait_s=120.0,
        error="billing_hard_limit_reached",
        clock=clock,
    )
    assert ok is True
    assert probes["n"] == 2
    assert sleeps == [30.0, 30.0]
    assert all(s["state"] == "api_billing_wait" for s in statuses)
    assert statuses[0]["billing_probe"] == 0


def test_wait_for_provider_billing_exhausts_without_recovery() -> None:
    t = {"now": 0.0}

    def clock() -> float:
        return t["now"]

    def sleep_fn(s: float) -> None:
        t["now"] += s

    statuses: list[dict] = []
    ok = wait_for_provider_billing(
        probe_fn=lambda: False,
        sleep_fn=sleep_fn,
        on_status=statuses.append,
        interval_s=40.0,
        max_wait_s=100.0,
        error="insufficient_quota",
        clock=clock,
    )
    assert ok is False
    assert any("exhausted" in str(s.get("error", "")) for s in statuses)


def test_api_billing_wait_not_stale() -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert (
        is_stale_status({"state": "api_billing_wait", "last_update_utc": old})
        is False
    )
