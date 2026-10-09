"""Recompute each paper macro from its source and compare to paper/numbers.tex."""

from __future__ import annotations

import re
from pathlib import Path

import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "paper_numbers", ROOT / "scripts" / "paper_numbers.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["paper_numbers"] = _mod
_spec.loader.exec_module(_mod)
compute = _mod.compute


def _parse_tex(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_macros_match_recompute():
    tex_path = ROOT / "paper" / "numbers.tex"
    assert tex_path.exists(), "run scripts/paper_numbers.py first"
    got = _parse_tex(tex_path)
    expected = {m.name: m.value for m in compute()}
    assert set(got) == set(expected)
    for name, val in expected.items():
        assert got[name] == val, f"{name}: tex={got[name]!r} recompute={val!r}"


def test_required_macros_present():
    required = [
        "HoneHR",
        "HoneLo",
        "HoneHi",
        "HaltP",
        "Alpha",
        "AlphaLo",
        "AlphaHi",
        "Nevents",
        "Nitemrounds",
        "Nchains",
        "SelfErodedSR",
        "SelfErodedNE",
        "CorErodedSR",
        "AgentErodedSR",
        "HtwoaGap",
        "HtwobGap",
        "HthreeEst",
        "LOIOagentOne",
        "PermP",
        "BootLo",
        "BootHi",
        "ItemAwareMin",
        "ItemAwareMax",
        "EvalAwareChains",
        "TypeI",
        "PowerS",
        "LocoLo",
        "LocoHi",
        "ItemAwareExHR",
        "NAgentOneEvents",
        "TouchCorSR",
        "CensorGemmaPct",
        "HRQwenThink",
        "NSubordCOR",
        "NHFiveAdded",
        "NCalib",
        "NHThreeIncludedWord",
    ]
    names = {m.name for m in compute()}
    missing = [r for r in required if r not in names]
    assert not missing, missing

