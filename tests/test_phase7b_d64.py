"""D64: measured PERMISSIVE budget estimate (not 90s×unit-rounds sequential)."""

from __future__ import annotations

import pytest

from rc.phase7b import estimate_permissive_usd


def test_estimate_permissive_usd_formula() -> None:
    est = estimate_permissive_usd(
        forced_modal_usd=2.0,
        forced_unit_rounds=2000,
        permissive_unit_rounds=200,
    )
    assert est == pytest.approx(2.0 / 2000 * 200 * 1.65 * 1.5)


def test_estimate_permissive_clears_false_hold() -> None:
    """Session-1 false hold: ~$1.57 FORCED clears stage cap under D64."""
    forced_usd = 1.5716592
    est = estimate_permissive_usd(
        forced_modal_usd=forced_usd,
        forced_unit_rounds=2000,
        permissive_unit_rounds=200,
    )
    assert forced_usd + est < 12.991


def test_estimate_rejects_zero_forced_rounds() -> None:
    with pytest.raises(ValueError):
        estimate_permissive_usd(
            forced_modal_usd=1.0, forced_unit_rounds=0, permissive_unit_rounds=10
        )
