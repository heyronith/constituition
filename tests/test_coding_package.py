"""Tests for the blind human-coding package."""

from __future__ import annotations

import filecmp
import importlib.util
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from rc.config import repo_root

ROOT = repo_root()
CODING = ROOT / "runs" / "main_v1" / "coding"
STUDY = ROOT / "coding_study"
BUILD = STUDY / "build_package.py"
ANALYZE = STUDY / "analyze_coding.py"

pytestmark = pytest.mark.skipif(not CODING.exists(), reason="runs/main_v1/coding/ missing")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built_package(tmp_path_factory):
    """Build into an isolated temp out/ so production coding_study/out/ is untouched."""
    build = _load(BUILD, "coding_build_package")
    tmp_study = tmp_path_factory.mktemp("coding_study")
    real_out = build.out_dir

    def _out_dir(root: Path | None = None) -> Path:
        del root
        d = tmp_study / "out"
        d.mkdir(parents=True, exist_ok=True)
        return d

    build.out_dir = _out_dir  # type: ignore[method-assign]
    summary = build.build(ROOT)
    assert summary["n_sampled"] == 120
    assert summary["shortfalls"] == []
    out = _out_dir()
    yield build, summary, out
    build.out_dir = real_out  # type: ignore[method-assign]


def test_strata_sizes_and_no_unit_duplicates(built_package) -> None:
    _build, _summary, out = built_package
    key = pd.read_csv(out / "sampling_key.csv")
    assert len(key) == 120
    expected = {
        "COR2": 20,
        "SELF1": 20,
        "HON4": 15,
        "CARE2": 15,
        "AGENT1": 15,
        "OTHER_COR": 15,
        "NONERODE_COR2": 4,
        "NONERODE_SELF1": 4,
        "NONERODE_HON4": 4,
        "NONERODE_CARE2": 4,
        "NONERODE_AGENT1": 4,
    }
    counts = key["stratum"].value_counts().to_dict()
    for k, n in expected.items():
        assert counts.get(k, 0) == n, (k, counts)
    # Unique (config, chain, item) via transition_id: config|...|chain_k|...|item|revise
    units = []
    for tid, item in zip(key["transition_id"], key["item_id"]):
        parts = str(tid).split("|")
        units.append((parts[0], parts[3], str(item)))
    assert len(units) == len(set(units))


def _xlsx_cell_fingerprint(path: Path) -> str:
    from openpyxl import load_workbook
    import hashlib

    wb = load_workbook(path, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            rows.append(tuple("" if v is None else str(v) for v in row))
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def test_determinism_of_key_and_sheets(built_package, tmp_path: Path) -> None:
    build, _, out = built_package
    snap = tmp_path / "snap"
    snap.mkdir()
    for name in ["sampling_key.csv", "sheet_map.csv"]:
        shutil.copy2(out / name, snap / name)
    fp_a = _xlsx_cell_fingerprint(out / "coderA/coding_sheet_coderA.xlsx")
    fp_b = _xlsx_cell_fingerprint(out / "coderB/coding_sheet_coderB.xlsx")
    sha_a = (out / "coderA/coding_sheet_coderA.xlsx").read_bytes()
    sha_b = (out / "coderB/coding_sheet_coderB.xlsx").read_bytes()
    sha_p = (out / "common/practice_sheet.xlsx").read_bytes()

    build.build(ROOT)
    assert filecmp.cmp(snap / "sampling_key.csv", out / "sampling_key.csv", shallow=False)
    assert filecmp.cmp(snap / "sheet_map.csv", out / "sheet_map.csv", shallow=False)
    assert fp_a == _xlsx_cell_fingerprint(out / "coderA/coding_sheet_coderA.xlsx")
    assert fp_b == _xlsx_cell_fingerprint(out / "coderB/coding_sheet_coderB.xlsx")
    # Zip-stabilized xlsx must be byte-identical across rebuilds.
    assert sha_a == (out / "coderA/coding_sheet_coderA.xlsx").read_bytes()
    assert sha_b == (out / "coderB/coding_sheet_coderB.xlsx").read_bytes()
    assert sha_p == (out / "common/practice_sheet.xlsx").read_bytes()


def test_blinding_check_passes(built_package) -> None:
    build, summary, out = built_package
    assert summary["blinding"]["package_coderA.zip"] is True
    assert summary["blinding"]["package_coderB.zip"] is True
    for zname in ("package_coderA.zip", "package_coderB.zip"):
        result = build.blinding_check_zip(out / zname)
        assert result["passed"], result["hits"]
        with zipfile.ZipFile(out / zname) as zf:
            names = set(zf.namelist())
            assert "Coding_Guide.pdf" in names
            assert "practice_sheet.xlsx" in names
            assert "Practice_Answers.pdf" in names


def test_analysis_runs_on_synthetic_sheets(built_package) -> None:
    _build, _summary, out = built_package
    analyze = _load(ANALYZE, "coding_analyze")
    info = analyze.synthetic_dry_run(out)
    assert info["n"] == 120
    syn = out / "synthetic_results"
    for name in [
        "reliability.json",
        "human_vs_judge.json",
        "themes_by_stratum.csv",
        "q3_by_stratum.csv",
        "disagreements.csv",
        "codes_anonymised.csv",
        "summary.md",
    ]:
        assert (syn / name).exists(), name
    body = (syn / "summary.md").read_text(encoding="utf-8")
    assert "EXPLORATORY (not preregistered)" in body
