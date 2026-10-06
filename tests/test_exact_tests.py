"""Unit tests for confirmatory exact/TOST/Holm helpers (no R)."""

from __future__ import annotations

from rc.exact_tests import exact_conditional_h1, holm_adjust, tost_log_hr
from rc.krippendorff_alpha import krippendorff_alpha_binary, krippendorff_alpha_chain_bootstrap


def test_exact_conditional_nullish() -> None:
    # At share 0.5, 5/10 is not greater → high p
    r = exact_conditional_h1(5, 10, 0.5)
    assert r.p_value_one_sided > 0.4
    # 9/10 at share 0.5 → small p
    r2 = exact_conditional_h1(9, 10, 0.5)
    assert r2.p_value_one_sided < 0.05


def test_exact_zero_events() -> None:
    r = exact_conditional_h1(0, 0, 0.5)
    assert r.p_value_one_sided == 1.0


def test_tost_inside_sesoi() -> None:
    # HR≈1, tiny SE → equivalence
    out = tost_log_hr(0.0, 0.01)
    assert bool(out["equivalent"]) is True
    assert "absent" in str(out["label"])


def test_tost_halt() -> None:
    import math

    # HR clearly < 1
    out = tost_log_hr(math.log(0.5), 0.05)
    assert bool(out["equivalent"]) is False
    assert out["label"] == "evidence for H-alt"


def test_holm() -> None:
    adj = holm_adjust([0.01, 0.04, 0.03])
    assert adj[0] <= adj[2] <= adj[1] or adj[0] < 0.05
    assert all(0 <= a <= 1 for a in adj)


def test_krippendorff_perfect() -> None:
    a = [0, 1, 1, 0, 1]
    assert krippendorff_alpha_binary(a, a) == 1.0


def test_krippendorff_bootstrap() -> None:
    c1 = [0, 1, 1, 0, 1, 0, 1, 1]
    c2 = [0, 1, 0, 0, 1, 0, 1, 1]
    chains = ["a", "a", "b", "b", "c", "c", "d", "d"]
    boot = krippendorff_alpha_chain_bootstrap(c1, c2, chains, n_bootstrap=200, seed=1)
    assert -1 <= boot.alpha <= 1
    assert boot.n_items == 8
