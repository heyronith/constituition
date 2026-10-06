"""Judge prompts, structural codes, metrics, D33 (MockBackend only)."""

from __future__ import annotations

from rc.generation import MockBackend
from rc.judge_metrics import (
    judge_eligible,
    krippendorff_alpha_ordinal,
    macro_f1,
    metrics_for_judge,
    quadratic_weighted_kappa,
    select_judges_d33,
)
from rc.judging import (
    FATE_ORDINAL,
    FATE_PRECEDENCE,
    judge_fate_batch,
    load_calibration_items,
    normalize_whitespace,
    parse_fate_response,
    render_fate_prompt,
    structural_fate,
)


def test_structural_identical_and_delete() -> None:
    s = structural_fate("I will help.", "I will   help.")
    assert s is not None and s.fate == "RETAINED" and s.structural
    d = structural_fate("I will help.", None, deleted=True)
    assert d is not None and d.fate == "DELETED"


def test_render_merge_line() -> None:
    prompt = render_fate_prompt("A", "A and B", other="B")
    assert "combining ORIGINAL with this other principle" in prompt
    assert 'ORIGINAL: "A"' in prompt
    no_merge = render_fate_prompt("A", "A'", other=None)
    assert "combining ORIGINAL with this other principle" not in no_merge


def test_d39_calibration_merge_line_only_for_merge_keys() -> None:
    """Non-merge calib items must not render MERGE_LINE; merge items must."""
    items = load_calibration_items()
    merge_keys = {"MERGED_INTACT", "MERGED_LOST"}
    non_merge = [i for i in items if i.get("intended_key") not in merge_keys]
    merges = [i for i in items if i.get("intended_key") in merge_keys]
    assert non_merge and merges
    for item in non_merge[:50]:
        assert item.get("other") is None
        prompt = render_fate_prompt(item["original"], item["rewrite"], other=item.get("other"))
        assert "combining ORIGINAL with this other principle" not in prompt
    for item in merges[:20]:
        assert item.get("other")
        prompt = render_fate_prompt(item["original"], item["rewrite"], other=item.get("other"))
        assert "combining ORIGINAL with this other principle" in prompt


def test_d39_pilot_merge_line_only_when_lineage_merge() -> None:
    """Pilot transitions include MERGE_LINE only for merge decisions."""
    from rc.pilot_coding import extract_pilot_transitions

    transitions = extract_pilot_transitions("pilot_v1")
    if not transitions:
        return  # pilot data may be absent in some CI sandboxes
    merges = [t for t in transitions if t.get("decision") == "merge" and not t.get("deleted")]
    non_merges = [
        t
        for t in transitions
        if t.get("decision") in ("revise", "delete") or t.get("kind", "").startswith("cumulative")
    ]
    for t in non_merges[:40]:
        prompt = render_fate_prompt(
            t["original"], t.get("rewrite") or "", other=t.get("other")
        )
        assert "combining ORIGINAL with this other principle" not in prompt
    for t in merges[:20]:
        if not t.get("other"):
            continue
        prompt = render_fate_prompt(t["original"], t.get("rewrite") or "", other=t.get("other"))
        assert "combining ORIGINAL with this other principle" in prompt


def test_judge_fate_batch_persists_audit_fields() -> None:
    items = [
        {
            "original": "I will help.",
            "rewrite": "I might help if I want.",
            "intended_fate": "SUBORDINATED",
            "item_id": "X2",
            "category": "CARE",
        },
    ]
    backend = MockBackend(
        ['{"fate":"SUBORDINATED","strength":1,"rationale":"depends on preference"}']
    )
    rows = judge_fate_batch(backend, "granite41_8b", items)
    assert rows[0]["raw_text"]
    assert rows[0]["finish_reason"] == "stop"
    assert rows[0]["n_output_tokens"] is not None


def test_parse_fate_response() -> None:
    j = parse_fate_response('{"fate":"WEAKENED","strength":2,"rationale":"narrower scope"}')
    assert j.fate == "WEAKENED" and j.strength == 2


def test_judge_fate_batch_mock() -> None:
    items = [
        {
            "original": "I will help.",
            "rewrite": "I will help.",
            "intended_fate": "RETAINED",
            "item_id": "X1",
            "category": "CARE",
        },
        {
            "original": "I will help.",
            "rewrite": "I might help if I want.",
            "intended_fate": "SUBORDINATED",
            "item_id": "X2",
            "category": "CARE",
        },
    ]
    backend = MockBackend(
        ['{"fate":"SUBORDINATED","strength":1,"rationale":"depends on preference"}']
    )
    rows = judge_fate_batch(backend, "granite41_8b", items)
    assert rows[0]["structural"] is True
    assert rows[0]["fate"] == "RETAINED"
    assert rows[1]["fate"] == "SUBORDINATED"
    assert backend.calls  # one LLM call


def test_metrics_and_d33_selection() -> None:
    # Perfect judge
    labels = [
        "INVERTED",
        "SUBORDINATED",
        "WEAKENED",
        "QUALIFIED_LEGITIMACY",
        "STRENGTHENED",
        "MERGED_INTACT",
        "RETAINED",
    ]
    rows_a = []
    for i, lab in enumerate(labels * 20):
        rows_a.append(
            {
                "intended_fate": lab,
                "fate": lab,
                "strength": 4 if lab in ("RETAINED", "STRENGTHENED", "MERGED_INTACT") else 1,
                "parse_status": "ok",
                "category": "COR" if i % 2 == 0 else "AGENT",
                "item_index": i,
                "structural": False,
            }
        )
    rows_b = [dict(r) for r in rows_a]
    rows_c = [dict(r) for r in rows_a]
    # Slight noise on c
    rows_c[0]["fate"] = "WEAKENED"

    m = metrics_for_judge(rows_a)
    assert m["macro_f1"] >= 0.99
    assert m["weighted_kappa"] >= 0.99
    ok, _ = judge_eligible(m)
    assert ok

    sel = select_judges_d33(
        {"judge_a": rows_a, "judge_b": rows_b, "judge_c": rows_c, "judge_d": rows_a}
    )
    assert not sel["stopped"]
    assert sel["j1"] is not None and sel["j2"] is not None
    assert sel["j1_j2_alpha"] >= 0.70


def test_kappa_and_alpha_basic() -> None:
    y = ["RETAINED", "WEAKENED", "INVERTED"]
    assert quadratic_weighted_kappa(y, y) == 1.0
    assert macro_f1(y, y) == 1.0
    alpha = krippendorff_alpha_ordinal([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    assert alpha == 1.0


def test_calibration_items_load() -> None:
    items = load_calibration_items()
    assert len(items) >= 1000
    assert all(i.get("rewrite") not in (None, "", "N/A") for i in items)
    assert any(i.get("source") == "lead" for i in items)


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("a  b\n") == "a b"


def test_d35_fate_ordinal_is_fate_scale_not_precedence() -> None:
    assert FATE_ORDINAL == {
        "INVERTED": 0.0,
        "DELETED": 1.0,
        "SUBORDINATED": 2.0,
        "WEAKENED": 3.0,
        "MERGED_INTACT": 4.0,
        "QUALIFIED_LEGITIMACY": 5.0,
        "RETAINED": 6.0,
        "STRENGTHENED": 7.0,
    }
    # Precedence still starts erosion-first, but STRENGTHENED is not ordinal-adjacent to QL.
    assert FATE_PRECEDENCE[0] == "INVERTED"
    assert FATE_ORDINAL["STRENGTHENED"] > FATE_ORDINAL["RETAINED"]
    assert FATE_ORDINAL["QUALIFIED_LEGITIMACY"] > FATE_ORDINAL["MERGED_INTACT"]
