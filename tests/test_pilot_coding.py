"""Pilot transition extraction and disagreement resolution (no GPU)."""

from __future__ import annotations

from rc.pilot_coding import resolve_disagreement


def test_resolve_agree() -> None:
    r = resolve_disagreement(
        {"fate": "WEAKENED", "strength": 2},
        {"fate": "WEAKENED", "strength": 3},
        None,
    )
    assert r["fate"] == "WEAKENED"
    assert r["unresolved"] is False


def test_resolve_j3_match() -> None:
    r = resolve_disagreement(
        {"fate": "WEAKENED", "strength": 2},
        {"fate": "SUBORDINATED", "strength": 1},
        {"fate": "WEAKENED", "strength": 2},
    )
    assert r["fate"] == "WEAKENED"
    assert r["resolver"] == "j3_match"


def test_resolve_median_unresolved() -> None:
    r = resolve_disagreement(
        {"fate": "INVERTED", "strength": 0},
        {"fate": "RETAINED", "strength": 4},
        {"fate": "STRENGTHENED", "strength": 4},
    )
    assert r["unresolved"] is True
    assert r["fate"] in {"INVERTED", "RETAINED", "STRENGTHENED"}
