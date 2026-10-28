"""Tests for coding study v2 instrument, mapping, ingestion and analysis."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from rc.config import repo_root

ROOT = repo_root()
CODING = ROOT / "runs" / "main_v1" / "coding"
STUDY = ROOT / "coding_study"
OUT = STUDY / "out"
V2 = STUDY / "v2"
ANALYZE = V2 / "analyze_v2.py"
BUILD = V2 / "build_v2.py"

pytestmark = pytest.mark.skipif(
    not CODING.exists() or not (OUT / "sampling_key.csv").exists(),
    reason="runs/main_v1/coding/ or coding_study/out/ missing",
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def av2():
    return _load(ANALYZE, "coding_analyze_v2")


def test_stimulus_match_rebuild(tmp_path: Path, av2) -> None:
    import zipfile

    src = OUT / "coderA" / "coding_sheet_coderA.xlsx"
    provided = OUT / "v2" / "mapping_v2.csv"
    assert src.exists() and provided.exists()
    rebuild = tmp_path / "rebuild"
    info = av2.verify_stimuli(src, provided, rebuild)
    assert info["mapping_identical"] is True
    # texts via mapping
    key = pd.read_csv(OUT / "sampling_key.csv")
    smap = pd.read_csv(OUT / "sheet_map.csv")
    smap["coder"] = smap["coder"].astype(str)
    map_a = smap[smap.coder == "A"].set_index("row")["key_id"].to_dict()
    mapping = pd.read_csv(provided)
    from openpyxl import load_workbook

    for coder in ("C", "D"):
        wb = load_workbook(rebuild / f"coder{coder}" / f"coding_sheet_coder{coder}.xlsx", data_only=True)
        ws = wb["Coding"]
        texts = {int(r[0]): (str(r[1]), str(r[2])) for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
        sub = mapping[mapping.coder == coder]
        for _, m in sub.iterrows():
            kid = map_a[int(m["coderA_row"])]
            kr = key.set_index("key_id").loc[kid]
            o, r = texts[int(m["row"])]
            assert o.strip() == str(kr["original"]).strip()
            assert r.strip() == str(kr["revised"]).strip()

    # D82: one zip per coder (guide + practice + answers + main sheet); no STEP1/STEP2
    zips = sorted(rebuild.glob("package_*.zip"))
    assert [z.name for z in zips] == ["package_coderC.zip", "package_coderD.zip"]
    assert not list(rebuild.glob("package_*_STEP*.zip"))
    expected = {
        "Start_Here.pdf",
        "Coding_Guide.pdf",
        "practice_sheet.xlsx",
        "Practice_Answers.pdf",
    }
    for coder, zpath in zip(("C", "D"), zips):
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
        assert expected <= names
        assert f"coding_sheet_coder{coder}.xlsx" in names


def test_v1_to_v2_mapping(av2) -> None:
    assert av2.map_v1_to_v2("A", "W") == ("Weaker", "No", "Worse")
    assert av2.map_v1_to_v2("B", "N") == ("Weaker", "Yes", "Neutral")
    assert av2.map_v1_to_v2("C", "B") == ("Weaker", "No", "Better")
    assert av2.map_v1_to_v2("D", "U") == ("Same", None, "Unsure")
    assert av2.map_v1_to_v2("E", "W") == ("Stronger", None, "Worse")
    assert av2.map_v1_to_v2("F", "N") == ("Same", None, "Neutral")
    assert av2.FATE_TO_Q1V2["WEAKENED"] == "Weaker"
    assert av2.FATE_TO_Q1V2["STRENGTHENED"] == "Stronger"
    assert av2.FATE_TO_Q1V2["RETAINED"] == "Same"


def test_csv_path_and_missing_handling(tmp_path: Path, av2) -> None:
    # Minimal B-style CSV + A xlsx from real returned if present; else skip ingest of real
    returned = tmp_path / "returned"
    returned.mkdir()
    # Build tiny synthetic using real key texts for first 2 B rows
    key = pd.read_csv(OUT / "sampling_key.csv")
    smap = pd.read_csv(OUT / "sheet_map.csv")
    smap["coder"] = smap["coder"].astype(str)
    bmap = smap[smap.coder == "B"].sort_values("row").head(2).merge(key, on="key_id")
    # For this unit test of CSV reader + missing: write 2-row csv matching map order for full 120 is heavy;
    # instead unit-test read_v1_csv + map + blank detection on a fixture file.
    rows = []
    for _, r in bmap.iterrows():
        rows.append(
            {
                "ORIGINAL": r["original"],
                "REVISED": r["revised"],
                "Q1_change": "C",
                "T1": "",
                "T2": "",
                "T3": "",
                "T4": "",
                "T5": "",
                "T6": "",
                "T7": "",
                "Q3_overall": "",  # missing Q3
            }
        )
    csv_path = returned / "tiny_b.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    df = av2.read_v1_csv(csv_path)
    assert list(df["row"]) == [1, 2]
    assert df.iloc[0]["Q1_change"] == "C"
    assert df.iloc[0]["Q3_overall"] is None
    q1, q2, q3 = av2.map_v1_to_v2("C", None)
    assert q1 == "Weaker" and q2 == "No" and q3 is None


def test_full_analysis_on_synthetic(tmp_path: Path, av2, monkeypatch) -> None:
    # Point study out to real OUT for key/map/mapping; write synthetic under tmp via monkeypatch of results
    info = av2.synthetic_cd_dry_run(OUT)
    assert info["n_rows"] >= 240  # A+B+C+D if A/B copied
    syn_res = Path(info["out"]) / "results"
    for name in [
        "reliability_v2.json",
        "human_vs_judge_v2.json",
        "q2_vs_subordinated.json",
        "q3_by_stratum.csv",
        "secondary_v1_mapped.json",
        "codes_anonymised.csv",
        "summary.md",
    ]:
        assert (syn_res / name).exists(), name
    rel = json.loads((syn_res / "reliability_v2.json").read_text(encoding="utf-8"))
    assert rel["have_primary"] is True
    assert "q1_three_way" in rel
    body = (syn_res / "summary.md").read_text(encoding="utf-8")
    assert "EXPLORATORY (not preregistered)" in body
    # anonymised has no notes column
    anon = pd.read_csv(syn_res / "codes_anonymised.csv")
    assert "notes" not in anon.columns
