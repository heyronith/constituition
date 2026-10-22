"""Tests for exploratory AIE item-level analyses."""

from __future__ import annotations

import filecmp
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from rc.config import repo_root

ROOT = repo_root()
OUT = ROOT / "results" / "exploratory_aie"
CODING = ROOT / "runs" / "main_v1" / "coding"
SCRIPT = ROOT / "analysis" / "exploratory_aie" / "run_aie_exploratory.py"

pytestmark = pytest.mark.skipif(
    not CODING.exists(),
    reason="runs/main_v1/coding/ missing locally",
)


def _load_mod():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("run_aie_exploratory", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_aie_exploratory"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_validation_gate_matches_published_category_values() -> None:
    mod = _load_mod()
    h = mod.load_forced_hazard(ROOT)
    outcomes = mod.build_item_outcomes(h)
    gate = mod.validation_gate(outcomes)
    assert gate["passed"] is True
    for row in gate["rows"]:
        key = (row["condition"], row["category"])
        assert row["estimate_pct_1dp"] == mod.PUBLISHED_R20[key]


def test_outputs_carry_exploratory_label_and_are_deterministic(tmp_path: Path) -> None:
    mod = _load_mod()
    mod.run(ROOT)
    text_files = [
        p
        for p in OUT.rglob("*")
        if p.is_file() and p.suffix.lower() in {".json", ".csv", ".md", ".txt"}
    ]
    assert text_files, "expected text outputs"
    for p in text_files:
        body = p.read_text(encoding="utf-8")
        assert mod.LABEL in body, f"missing label in {p}"

    first = tmp_path / "first"
    first.mkdir()
    for p in text_files:
        rel = p.relative_to(OUT)
        dest = first / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)

    mod.run(ROOT)
    for p in text_files:
        rel = p.relative_to(OUT)
        assert filecmp.cmp(first / rel, p, shallow=False), f"non-deterministic: {rel}"
