"""D65: C1 non-gating; gemma harness-frac tripwire."""

from __future__ import annotations

import json
from pathlib import Path

from rc.phase7b import classify_parse_failure, parse_tripwire_stats


def test_classify_revise_identical_is_model() -> None:
    assert classify_parse_failure("stop", "revise text identical") == "model_behaviour"


def test_classify_length_is_harness() -> None:
    assert classify_parse_failure("length", "revise text identical") == "harness"
    assert classify_parse_failure("length", None) == "harness"


def test_classify_json_schema_is_harness() -> None:
    assert classify_parse_failure("stop", "no JSON object found") == "harness"
    assert classify_parse_failure("stop", "invalid structured output: x") == "harness"


def test_harness_frac_tripwire_ignores_model_behaviour(tmp_path: Path) -> None:
    base = (
        tmp_path
        / "runs/main_v1/gemma4_12b/FORCED/NEUTRAL_EDIT/STRUCTURED/chain_0"
    )
    base.mkdir(parents=True)
    (base / "meta.json").write_text(json.dumps({"protocol": "FORCED"}), encoding="utf-8")
    rows = []
    for r in range(4):
        rows.append(
            {
                "round": r,
                "parse_status": "error",
                "finish_reason": "stop",
                "parse_error": "revise text identical",
                "text_final": "{}",
            }
        )
    (base / "rounds.jsonl").write_text(
        "\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8"
    )
    legacy = parse_tripwire_stats(
        "main_v1", "gemma4_12b", root=tmp_path, after_round=3, mode="legacy"
    )
    assert legacy["trip"] is True
    narrow = parse_tripwire_stats(
        "main_v1", "gemma4_12b", root=tmp_path, after_round=3, mode="harness_frac"
    )
    assert narrow["trip"] is False


def test_harness_frac_trips_on_length(tmp_path: Path) -> None:
    base = (
        tmp_path
        / "runs/main_v1/gemma4_12b/FORCED/SELF_REFLECT/STRUCTURED/chain_0"
    )
    base.mkdir(parents=True)
    (base / "meta.json").write_text(json.dumps({"protocol": "FORCED"}), encoding="utf-8")
    # 10 fails: 1 length + 9 revise-identical → harness_frac=0.10 → trip
    rows = [
        {
            "round": 0,
            "parse_status": "error",
            "finish_reason": "length",
            "parse_error": "unterminated JSON object",
        }
    ]
    for _ in range(9):
        rows.append(
            {
                "round": 0,
                "parse_status": "error",
                "finish_reason": "stop",
                "parse_error": "revise text identical",
            }
        )
    (base / "rounds.jsonl").write_text(
        "\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8"
    )
    stats = parse_tripwire_stats(
        "main_v1", "gemma4_12b", root=tmp_path, after_round=3, mode="harness_frac"
    )
    assert stats["trip"] is True
