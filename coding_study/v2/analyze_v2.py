#!/usr/bin/env python3
"""Ingest and analyze human-coding returns (v2 instrument; EXPLORATORY).

Implements D81. Writes only under results/exploratory_aie/human_coding/.
Never prints or commits lastModifiedBy, coder names, or notes text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

SEED = 20261004
LABEL = "EXPLORATORY (not preregistered)"
N_BOOT = 1000

Q1V2 = frozenset({"Weaker", "Same", "Stronger"})
Q2V2 = frozenset({"Yes", "No"})
Q3V2 = frozenset({"Worse", "Neutral", "Better", "Unsure"})

V1_Q1_TO_V2 = {
    "A": "Weaker",
    "B": "Weaker",
    "C": "Weaker",
    "D": "Same",
    "E": "Stronger",
    "F": "Same",
}
V1_Q2_TO_V2 = {"B": "Yes", "A": "No", "C": "No"}  # only when Q1v2 == Weaker
V1_Q3_TO_V2 = {"W": "Worse", "N": "Neutral", "B": "Better", "U": "Unsure"}

FATE_TO_Q1V2 = {
    "INVERTED": "Weaker",
    "SUBORDINATED": "Weaker",
    "WEAKENED": "Weaker",
    "QUALIFIED_LEGITIMACY": "Same",
    "RETAINED": "Same",
    "MERGED_INTACT": "Same",
    "STRENGTHENED": "Stronger",
}


def study_root() -> Path:
    return Path(__file__).resolve().parent.parent


def v2_root() -> Path:
    return Path(__file__).resolve().parent


def results_dir() -> Path:
    from rc.config import repo_root

    return repo_root() / "results" / "exploratory_aie" / "human_coding"


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _norm_ws(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _blank(v: Any) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s == "" or s.lower() == "nan"


def _as_str(v: Any) -> str | None:
    if _blank(v):
        return None
    return str(v).strip()


def _as_upper(v: Any) -> str | None:
    s = _as_str(v)
    return s.upper() if s is not None else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Reliability helpers
# ---------------------------------------------------------------------------


def cohen_kappa(y1: list[Any], y2: list[Any]) -> float:
    if len(y1) != len(y2) or not y1:
        return float("nan")
    labels = sorted(set(y1) | set(y2), key=lambda x: str(x))
    idx = {lab: i for i, lab in enumerate(labels)}
    n = len(y1)
    k = len(labels)
    mat = np.zeros((k, k), dtype=float)
    for a, b in zip(y1, y2):
        mat[idx[a], idx[b]] += 1
    po = float(np.trace(mat) / n)
    pe = float(sum(mat.sum(0)[i] * mat.sum(1)[i] for i in range(k)) / (n * n))
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def krippendorff_alpha_nominal_two(c1: list[Any], c2: list[Any]) -> float:
    """Nominal α for two coders; skip units where either value is None."""
    pairs = [(a, b) for a, b in zip(c1, c2) if a is not None and b is not None]
    if not pairs:
        return float("nan")
    n = len(pairs)
    disagree = sum(1 for a, b in pairs if a != b)
    do = disagree / n
    vals = [a for a, _ in pairs] + [b for _, b in pairs]
    counts = Counter(vals)
    n_rat = 2 * n
    n_vals = np.array([counts[v] for v in counts], dtype=float)
    de = 1.0 - float(np.sum(n_vals * (n_vals - 1)) / (n_rat * (n_rat - 1))) if n_rat > 1 else 0.0
    if de == 0.0:
        return 1.0 if do == 0.0 else 0.0
    return 1.0 - (do / de)


def krippendorff_alpha_nominal_multi(rater_lists: list[list[Any]]) -> float:
    """Nominal α for ≥2 raters; missing (None) ignored per unit (skip units with <2 ratings)."""
    if not rater_lists or not rater_lists[0]:
        return float("nan")
    n_units = len(rater_lists[0])
    assert all(len(r) == n_units for r in rater_lists)
    coincidence: dict[tuple[Any, Any], float] = {}
    n_pairable = 0.0
    value_counts: Counter[Any] = Counter()
    for u in range(n_units):
        vals = [r[u] for r in rater_lists if r[u] is not None]
        m = len(vals)
        if m < 2:
            continue
        n_pairable += m * (m - 1)
        for v in vals:
            value_counts[v] += m - 1  # each value contributes (m-1) to marginal in coincidence form
        for i in range(m):
            for j in range(m):
                if i == j:
                    continue
                a, b = vals[i], vals[j]
                key = (a, b) if str(a) <= str(b) else (b, a)
                # accumulate unordered pairs once via i<j below
        for i in range(m):
            for j in range(i + 1, m):
                a, b = vals[i], vals[j]
                if a == b:
                    coincidence[(a, a)] = coincidence.get((a, a), 0.0) + 2.0
                else:
                    coincidence[(a, b)] = coincidence.get((a, b), 0.0) + 1.0
                    coincidence[(b, a)] = coincidence.get((b, a), 0.0) + 1.0
    if n_pairable <= 0:
        return float("nan")
    # Do = disagreement proportion from coincidence matrix
    do_num = 0.0
    for (a, b), o_ab in coincidence.items():
        if a != b:
            do_num += o_ab
    do = do_num / n_pairable
    # De from value marginals: n_c = number of pairable assignments of value c
    # Using standard: De = 1 - sum_c n_c(n_c-1) / (N(N-1)) with N = sum n_c from coincidence diagonals+off
    # Simpler two-step: N = n_pairable; n_c = sum over units of (m_u-1) for each rating of c
    n_c = Counter()
    for u in range(n_units):
        vals = [r[u] for r in rater_lists if r[u] is not None]
        m = len(vals)
        if m < 2:
            continue
        for v in vals:
            n_c[v] += m - 1
    N = sum(n_c.values())
    if N <= 1:
        return float("nan")
    de = 1.0 - sum(nc * (nc - 1) for nc in n_c.values()) / (N * (N - 1))
    if de == 0.0:
        return 1.0 if do == 0.0 else 0.0
    return 1.0 - (do / de)


def bootstrap_ci(
    values_fn, n: int, rng: np.random.Generator, n_boot: int = N_BOOT
) -> tuple[float, float, float]:
    point = values_fn(np.arange(n))
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots.append(values_fn(idx))
    arr = np.asarray(boots, dtype=float)
    lo, hi = np.nanquantile(arr, [0.025, 0.975])
    return float(point), float(lo), float(hi)


def confusion(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict[str, Any]:
    mat = {a: {b: 0 for b in labels} for a in labels}
    for t, p in zip(y_true, y_pred):
        if t not in mat:
            mat[t] = {b: 0 for b in labels}
        if p not in mat[t]:
            for row in mat.values():
                row.setdefault(p, 0)
            mat[t][p] = 0
        mat[t][p] = mat[t].get(p, 0) + 1
    agree = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return {
        "labels": labels,
        "matrix": mat,
        "n": len(y_true),
        "pct_agreement": (agree / len(y_true)) if y_true else None,
        "cohen_kappa": cohen_kappa(y_true, y_pred) if y_true else None,
    }


# ---------------------------------------------------------------------------
# Provenance (no lastModifiedBy)
# ---------------------------------------------------------------------------


def _xlsx_doc_props(data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "docProps/app.xml" in zf.namelist():
            app = zf.read("docProps/app.xml").decode("utf-8", errors="replace")
            m = re.search(r"<Application>([^<]*)</Application>", app)
            if m:
                out["Application"] = m.group(1)
            m = re.search(r"<AppVersion>([^<]*)</AppVersion>", app)
            if m:
                out["AppVersion"] = m.group(1)
        if "docProps/core.xml" in zf.namelist():
            core = zf.read("docProps/core.xml").decode("utf-8", errors="replace")
            m = re.search(r"<dcterms:created[^>]*>([^<]*)</dcterms:created>", core)
            if m:
                out["created"] = m.group(1)
            m = re.search(r"<dcterms:modified[^>]*>([^<]*)</dcterms:modified>", core)
            if m:
                out["modified"] = m.group(1)
    return out


def _timelog_tab(path: Path) -> list[dict[str, Any]] | None:
    if path.suffix.lower() != ".xlsx":
        return None
    wb = load_workbook(path, data_only=True)
    name = next((n for n in wb.sheetnames if "time" in n.lower()), None)
    if name is None:
        return None
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return None
    header = [str(h) if h is not None else f"c{i}" for i, h in enumerate(rows[0])]
    out = []
    for r in rows[1:]:
        if r is None or all(_blank(v) for v in r):
            continue
        out.append({header[i]: (None if _blank(r[i]) else r[i]) for i in range(len(header)) if i < len(r)})
    return out


def write_provenance(returned_dir: Path) -> dict[str, Any]:
    prov: dict[str, Any] = {}
    for path in sorted(returned_dir.iterdir()):
        if path.name.startswith(".") or path.name == "provenance.json":
            continue
        if not path.is_file():
            continue
        entry: dict[str, Any] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
        if path.suffix.lower() == ".xlsx":
            entry.update(_xlsx_doc_props(path.read_bytes()))
            tl = _timelog_tab(path)
            if tl is not None:
                entry["time_log"] = tl
        prov[path.name] = entry
    dump_json(returned_dir / "provenance.json", prov)
    return prov


# ---------------------------------------------------------------------------
# Readers + v1→v2 mapping
# ---------------------------------------------------------------------------


def map_v1_to_v2(q1: str | None, q3: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (Q1v2, Q2v2, Q3v2) from v1 letter codes."""
    q1v2 = V1_Q1_TO_V2.get(q1) if q1 else None
    q2v2 = V1_Q2_TO_V2.get(q1) if q1v2 == "Weaker" and q1 else None
    q3v2 = V1_Q3_TO_V2.get(q3) if q3 else None
    return q1v2, q2v2, q3v2


def read_v1_xlsx(path: Path) -> pd.DataFrame:
    wb = load_workbook(path, data_only=True)
    ws = wb["Coding"] if "Coding" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in rows[0]]
    data = []
    for r in rows[1:]:
        if r is None or all(_blank(v) for v in r):
            continue
        data.append({header[i]: (r[i] if i < len(r) else None) for i in range(len(header))})
    df = pd.DataFrame(data)
    df["row"] = df["row"].astype(int)
    df["Q1_change"] = df["Q1_change"].map(_as_upper)
    df["Q3_overall"] = df["Q3_overall"].map(_as_upper)
    return df


def read_v1_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.insert(0, "row", range(1, len(df) + 1))
    df["Q1_change"] = df["Q1_change"].map(_as_upper)
    df["Q3_overall"] = df["Q3_overall"].map(_as_upper)
    return df


def read_v2_sheet(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        if "row" not in df.columns:
            df.insert(0, "row", range(1, len(df) + 1))
    else:
        wb = load_workbook(path, data_only=True)
        ws = wb["Coding"] if "Coding" in wb.sheetnames else wb.active
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h) if h is not None else "" for h in rows[0]]
        data = []
        for r in rows[1:]:
            if r is None or all(_blank(v) for v in r):
                continue
            data.append({header[i]: (r[i] if i < len(r) else None) for i in range(len(header))})
        df = pd.DataFrame(data)
    df["row"] = df["row"].astype(int)
    # Normalise answer casing
    def _q1(v):
        s = _as_str(v)
        if s is None:
            return None
        t = s.strip().title()
        return t if t in Q1V2 else s

    def _q2(v):
        s = _as_str(v)
        if s is None:
            return None
        t = s.strip().title()
        if t in ("Y", "Yes"):
            return "Yes"
        if t in ("N", "No"):
            return "No"
        return t if t in Q2V2 else s

    def _q3(v):
        s = _as_str(v)
        if s is None:
            return None
        t = s.strip().title()
        return t if t in Q3V2 else s

    df["Q1_demand"] = df["Q1_demand"].map(_q1)
    df["Q2_decides_itself"] = df["Q2_decides_itself"].map(_q2)
    df["Q3_overall"] = df["Q3_overall"].map(_q3)
    return df


def normalize_returns(
    returned_dir: Path,
    *,
    key_path: Path,
    sheet_map_path: Path,
    mapping_v2_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = pd.read_csv(key_path)
    smap = pd.read_csv(sheet_map_path)
    smap["coder"] = smap["coder"].astype(str)
    key_by = key.set_index("key_id")
    map_a = smap[smap.coder == "A"].set_index("row")["key_id"].to_dict()
    map_b = smap[smap.coder == "B"].sort_values("row")
    mapping_v2 = pd.read_csv(mapping_v2_path) if mapping_v2_path.exists() else None

    report: dict[str, Any] = {
        "missing": [],
        "q2_flags": [],
        "text_mismatches": [],
        "coders_present": [],
    }
    rows_out: list[dict[str, Any]] = []

    def check_texts(coder: str, row: int, key_id: str, orig: Any, rev: Any) -> None:
        kr = key_by.loc[key_id]
        if _norm_ws(orig) != _norm_ws(kr["original"]) or _norm_ws(rev) != _norm_ws(kr["revised"]):
            report["text_mismatches"].append({"coder": coder, "row": row, "key_id": key_id})

    # --- A ---
    path_a = returned_dir / "coderA.xlsx"
    if path_a.exists():
        report["coders_present"].append("A")
        df = read_v1_xlsx(path_a)
        for _, r in df.iterrows():
            row = int(r["row"])
            key_id = map_a[row]
            check_texts("A", row, key_id, r["ORIGINAL"], r["REVISED"])
            q1 = r["Q1_change"] if not _blank(r["Q1_change"]) else None
            q3 = r["Q3_overall"] if not _blank(r["Q3_overall"]) else None
            if q1 is None:
                report["missing"].append({"coder": "A", "row": row, "field": "Q1v1"})
            if q3 is None:
                report["missing"].append({"coder": "A", "row": row, "field": "Q3v1"})
            q1v2, q2v2, q3v2 = map_v1_to_v2(q1, q3)
            rows_out.append(
                {
                    "coder": "A",
                    "instrument": "v1",
                    "row": row,
                    "key_id": key_id,
                    "Q1v2": q1v2,
                    "Q2v2": q2v2,
                    "Q3v2": q3v2,
                    "Q1v1": q1,
                }
            )

    # --- B (CSV, file order = sheet_map B order) ---
    path_b = returned_dir / "coderB.csv"
    if path_b.exists():
        report["coders_present"].append("B")
        df = read_v1_csv(path_b)
        merged = map_b.reset_index(drop=True).merge(key, on="key_id")
        if len(df) != len(merged):
            raise SystemExit(f"coder B: expected {len(merged)} rows, got {len(df)}")
        for i in range(len(df)):
            row = i + 1
            key_id = str(merged.iloc[i]["key_id"])
            check_texts("B", row, key_id, df.iloc[i]["ORIGINAL"], df.iloc[i]["REVISED"])
            q1 = df.iloc[i]["Q1_change"] if not _blank(df.iloc[i]["Q1_change"]) else None
            q3 = df.iloc[i]["Q3_overall"] if not _blank(df.iloc[i]["Q3_overall"]) else None
            if q1 is None:
                report["missing"].append({"coder": "B", "row": row, "field": "Q1v1"})
            if q3 is None:
                report["missing"].append({"coder": "B", "row": row, "field": "Q3v1"})
            q1v2, q2v2, q3v2 = map_v1_to_v2(q1, q3)
            rows_out.append(
                {
                    "coder": "B",
                    "instrument": "v1",
                    "row": row,
                    "key_id": key_id,
                    "Q1v2": q1v2,
                    "Q2v2": q2v2,
                    "Q3v2": q3v2,
                    "Q1v1": q1,
                }
            )

    # --- C / D ---
    if mapping_v2 is not None:
        for coder in ("C", "D"):
            candidates = list(returned_dir.glob(f"coder{coder}.*"))
            if not candidates:
                continue
            report["coders_present"].append(coder)
            path = candidates[0]
            df = read_v2_sheet(path)
            sub = mapping_v2[mapping_v2.coder == coder]
            for _, m in sub.iterrows():
                row = int(m["row"])
                a_row = int(m["coderA_row"])
                key_id = map_a[a_row]
                rr = df[df.row == row]
                if rr.empty:
                    report["missing"].append({"coder": coder, "row": row, "field": "row"})
                    continue
                r = rr.iloc[0]
                check_texts(coder, row, key_id, r["ORIGINAL"], r["REVISED"])
                q1 = r["Q1_demand"]
                q2 = r["Q2_decides_itself"]
                q3 = r["Q3_overall"]
                if q1 is None:
                    report["missing"].append({"coder": coder, "row": row, "field": "Q1v2"})
                if q3 is None:
                    report["missing"].append({"coder": coder, "row": row, "field": "Q3v2"})
                if q1 == "Weaker" and q2 is None:
                    report["q2_flags"].append({"coder": coder, "row": row, "flag": "Q2_missing_when_Weaker"})
                if q1 is not None and q1 != "Weaker" and q2 is not None:
                    report["q2_flags"].append({"coder": coder, "row": row, "flag": "Q2_present_when_not_Weaker"})
                rows_out.append(
                    {
                        "coder": coder,
                        "instrument": "v2",
                        "row": row,
                        "key_id": key_id,
                        "Q1v2": q1 if q1 in Q1V2 else q1,
                        "Q2v2": q2 if q1 == "Weaker" else (q2 if q2 is not None else None),
                        "Q3v2": q3,
                        "Q1v1": None,
                    }
                )

    if report["text_mismatches"]:
        raise SystemExit(f"TEXT MISMATCH: {report['text_mismatches'][:5]}")

    table = pd.DataFrame(rows_out)
    return table, report


def score_practice(returned_dir: Path, practice_json: Path, out_path: Path) -> dict[str, Any]:
    items = json.loads(practice_json.read_text(encoding="utf-8"))
    weaker_ns = {int(p["n"]) for p in items if p["q1"] == "Weaker"}
    key_q1 = {int(p["n"]): p["q1"] for p in items}
    key_q2 = {int(p["n"]): (p["q2"] or None) for p in items}
    scores: dict[str, Any] = {}
    for coder in ("C", "D"):
        cands = list(returned_dir.glob(f"practice_{coder}.*"))
        if not cands:
            scores[coder] = {"present": False}
            continue
        df = read_v2_sheet(cands[0])
        # practice sheets may use n as row
        q1_ok = 0
        q2_ok = 0
        q2_n = 0
        for _, r in df.iterrows():
            n = int(r["row"])
            if r.get("Q1_demand") == key_q1.get(n):
                q1_ok += 1
            if n in weaker_ns:
                q2_n += 1
                if r.get("Q2_decides_itself") == key_q2.get(n):
                    q2_ok += 1
        scores[coder] = {
            "present": True,
            "q1_exact": q1_ok,
            "q1_out_of": 10,
            "q2_exact": q2_ok,
            "q2_out_of": q2_n,
        }
    dump_json(out_path, scores)
    return scores


# ---------------------------------------------------------------------------
# Analysis (D81)
# ---------------------------------------------------------------------------


def _alpha_boot(c1: list[Any], c2: list[Any], rng: np.random.Generator) -> dict[str, Any]:
    # Restrict to units where both non-missing for indexing bootstrap
    pairs = [(a, b) for a, b in zip(c1, c2) if a is not None and b is not None]
    n = len(pairs)
    if n == 0:
        return {"alpha": None, "ci95": [None, None], "n": 0}
    a1 = [p[0] for p in pairs]
    a2 = [p[1] for p in pairs]

    def fn(idx):
        return krippendorff_alpha_nominal_two([a1[i] for i in idx], [a2[i] for i in idx])

    alpha, lo, hi = bootstrap_ci(fn, n, rng)
    return {"alpha": alpha, "ci95": [lo, hi], "n": n}


def _vs_judge(human: list[str | None], judge: list[str | None], labels: list[str]) -> dict[str, Any]:
    pairs = [(h, j) for h, j in zip(human, judge) if h is not None and j is not None]
    if not pairs:
        return {"n": 0}
    h_list = [p[0] for p in pairs]
    j_list = [p[1] for p in pairs]
    return confusion(j_list, h_list, labels)


def analyze_table(
    table: pd.DataFrame,
    key: pd.DataFrame,
    out_dir: Path,
    *,
    primary_coders: tuple[str, str] = ("C", "D"),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    key_by = key.set_index("key_id")
    key_ids = sorted(key["key_id"].tolist())

    def series(coder: str, col: str) -> list[Any]:
        sub = table[table.coder == coder].set_index("key_id")
        return [sub.loc[k, col] if k in sub.index else None for k in key_ids]

    present = set(table.coder.unique())
    labels3 = ["Weaker", "Same", "Stronger"]

    # --- Anonymised codes ---
    anon_rows = []
    for _, r in table.iterrows():
        anon_rows.append(
            {
                "label": LABEL,
                "coder": r["coder"],
                "instrument": r["instrument"],
                "key_id": r["key_id"],
                "Q1v2": r["Q1v2"],
                "Q2v2": r["Q2v2"],
                "Q3v2": r["Q3v2"],
                "Q1v1": r["Q1v1"],
                "stratum": key_by.loc[r["key_id"], "stratum"] if r["key_id"] in key_by.index else None,
                "fate_gpt54": key_by.loc[r["key_id"], "fate_gpt54"] if r["key_id"] in key_by.index else None,
                "fate_mimo": key_by.loc[r["key_id"], "fate_mimo"] if r["key_id"] in key_by.index else None,
            }
        )
    pd.DataFrame(anon_rows).to_csv(out_dir / "codes_anonymised.csv", index=False)

    judge_gpt = [
        FATE_TO_Q1V2.get(str(key_by.loc[k, "fate_gpt54"])) if k in key_by.index else None for k in key_ids
    ]
    judge_mimo = []
    for k in key_ids:
        f = key_by.loc[k, "fate_mimo"] if k in key_by.index else None
        if _blank(f):
            judge_mimo.append(None)
        else:
            judge_mimo.append(FATE_TO_Q1V2.get(str(f)))

    c_pri, d_pri = primary_coders
    have_primary = c_pri in present and d_pri in present

    reliability: dict[str, Any] = {"label": LABEL, "primary_coders": list(primary_coders), "have_primary": have_primary}
    hvj: dict[str, Any] = {"label": LABEL, "gpt54": {}, "mimo": {}}
    q2_vs: dict[str, Any] = {"label": LABEL}
    secondary: dict[str, Any] = {"label": LABEL, "note": "A and B used v1 mapped to v2"}

    if have_primary:
        q1_c = series(c_pri, "Q1v2")
        q1_d = series(d_pri, "Q1v2")
        er_c = [None if x is None else (x == "Weaker") for x in q1_c]
        er_d = [None if x is None else (x == "Weaker") for x in q1_d]
        reliability["q1_three_way"] = _alpha_boot(q1_c, q1_d, rng)
        reliability["binary_erosion"] = _alpha_boot(er_c, er_d, rng)

        # Q2 on rows both Weaker
        q2_c = series(c_pri, "Q2v2")
        q2_d = series(d_pri, "Q2v2")
        both_weak = [
            i
            for i, (a, b) in enumerate(zip(q1_c, q1_d))
            if a == "Weaker" and b == "Weaker"
        ]
        q2a = [q2_c[i] for i in both_weak]
        q2b = [q2_d[i] for i in both_weak]
        reliability["q2_both_weaker"] = _alpha_boot(q2a, q2b, rng)

        # Q3 excl Unsure
        q3_c = series(c_pri, "Q3v2")
        q3_d = series(d_pri, "Q3v2")
        q3_pairs_idx = [
            i
            for i, (a, b) in enumerate(zip(q3_c, q3_d))
            if a is not None and b is not None and a != "Unsure" and b != "Unsure"
        ]
        reliability["q3_excl_unsure"] = _alpha_boot(
            [q3_c[i] for i in q3_pairs_idx], [q3_d[i] for i in q3_pairs_idx], rng
        )

        # Human vs judge
        for name, human in [(c_pri, q1_c), (d_pri, q1_d)]:
            hvj["gpt54"][f"coder_{name}"] = _vs_judge(human, judge_gpt, labels3)
            hvj["mimo"][f"coder_{name}"] = _vs_judge(human, judge_mimo, labels3)
        consensus = [a if a == b else None for a, b in zip(q1_c, q1_d)]
        hvj["gpt54"]["consensus"] = _vs_judge(consensus, judge_gpt, labels3)
        hvj["mimo"]["consensus"] = _vs_judge(consensus, judge_mimo, labels3)

        # Q2 vs SUBORDINATED
        fate = [str(key_by.loc[k, "fate_gpt54"]) if k in key_by.index else None for k in key_ids]
        sub_rows = []
        for i in both_weak:
            sub_rows.append(
                {
                    "key_id": key_ids[i],
                    "coder_C_Q2": q2_c[i],
                    "coder_D_Q2": q2_d[i],
                    "fate_gpt54": fate[i],
                    "judge_subordinated": fate[i] == "SUBORDINATED",
                }
            )
        q2_vs["n_both_weaker"] = len(both_weak)
        q2_vs["rows"] = sub_rows
        if sub_rows:
            # agreement of Yes with SUBORDINATED for each coder
            for lab, q2s in [("C", q2_c), ("D", q2_d)]:
                y = [1 if q2s[i] == "Yes" else 0 for i in both_weak]
                j = [1 if fate[i] == "SUBORDINATED" else 0 for i in both_weak]
                q2_vs[f"coder_{lab}_vs_subordinated"] = {
                    "pct_agreement": sum(a == b for a, b in zip(y, j)) / len(y) if y else None,
                    "cohen_kappa": cohen_kappa(y, j) if y else None,
                    "n": len(y),
                    "n_yes": sum(y),
                    "n_subordinated": sum(j),
                }
    else:
        reliability["note"] = f"Primary coders {primary_coders} not both present; primary metrics deferred."

    # Q3 by stratum (all present coders)
    q3_rows = []
    for coder in sorted(present):
        sub = table[table.coder == coder]
        for _, r in sub.iterrows():
            stratum = key_by.loc[r["key_id"], "stratum"] if r["key_id"] in key_by.index else None
            q3_rows.append({"label": LABEL, "coder": coder, "stratum": stratum, "Q3v2": r["Q3v2"]})
    q3_df = pd.DataFrame(q3_rows)
    if len(q3_df):
        counts = (
            q3_df.groupby(["stratum", "coder", "Q3v2"], dropna=False)
            .size()
            .reset_index(name="n")
        )
        totals = counts.groupby(["stratum", "coder"])["n"].transform("sum")
        counts["pct"] = counts["n"] / totals
        counts.insert(0, "label", LABEL)
        counts.to_csv(out_dir / "q3_by_stratum.csv", index=False)
    else:
        pd.DataFrame(columns=["label", "stratum", "coder", "Q3v2", "n", "pct"]).to_csv(
            out_dir / "q3_by_stratum.csv", index=False
        )

    # Secondary A/B
    if "A" in present and "B" in present:
        q1_a = series("A", "Q1v2")
        q1_b = series("B", "Q1v2")
        er_a = [None if x is None else (x == "Weaker") for x in q1_a]
        er_b = [None if x is None else (x == "Weaker") for x in q1_b]
        secondary["ab_q1_three_way"] = _alpha_boot(q1_a, q1_b, rng)
        secondary["ab_binary_erosion"] = _alpha_boot(er_a, er_b, rng)
        q3_a = series("A", "Q3v2")
        q3_b = series("B", "Q3v2")
        q3_idx = [
            i
            for i, (a, b) in enumerate(zip(q3_a, q3_b))
            if a is not None and b is not None and a != "Unsure" and b != "Unsure"
        ]
        secondary["ab_q3_excl_unsure"] = _alpha_boot(
            [q3_a[i] for i in q3_idx], [q3_b[i] for i in q3_idx], rng
        )
        # pairwise among available of A,B,C,D
        coders_for_four = [c for c in ("A", "B", "C", "D") if c in present]
        secondary["coders_in_multi"] = coders_for_four
        secondary["note_instruments"] = (
            "A and B used v1 (mapped to v2); C and D used v2 when present."
        )
        pairwise = {}
        for i, c1 in enumerate(coders_for_four):
            for c2 in coders_for_four[i + 1 :]:
                pairwise[f"{c1}_{c2}"] = _alpha_boot(series(c1, "Q1v2"), series(c2, "Q1v2"), rng)
        secondary["pairwise_q1_alpha"] = pairwise
        if len(coders_for_four) >= 2:
            rater_lists = [series(c, "Q1v2") for c in coders_for_four]

            def multi_fn(idx):
                lists = [[lst[i] for i in idx] for lst in rater_lists]
                return krippendorff_alpha_nominal_multi(lists)

            alpha, lo, hi = bootstrap_ci(multi_fn, len(key_ids), rng)
            secondary["four_coder_q1_alpha"] = {
                "alpha": alpha,
                "ci95": [lo, hi],
                "n_units": len(key_ids),
                "coders": coders_for_four,
            }

        # also report mapped A/B vs judge for transparency (secondary)
        secondary["gpt54_vs_A"] = _vs_judge(q1_a, judge_gpt, labels3)
        secondary["gpt54_vs_B"] = _vs_judge(q1_b, judge_gpt, labels3)
        consensus_ab = [a if a == b else None for a, b in zip(q1_a, q1_b)]
        secondary["gpt54_vs_AB_consensus"] = _vs_judge(consensus_ab, judge_gpt, labels3)
        # raw erosion agreement count (context from D81 narrative)
        both = [(a == "Weaker", b == "Weaker") for a, b in zip(q1_a, q1_b) if a is not None and b is not None]
        agree_er = sum(1 for a, b in both if a == b)
        secondary["ab_binary_erosion_agree_count"] = {"agree": agree_er, "n": len(both)}

    dump_json(out_dir / "reliability_v2.json", reliability)
    dump_json(out_dir / "human_vs_judge_v2.json", hvj)
    dump_json(out_dir / "q2_vs_subordinated.json", q2_vs)
    dump_json(out_dir / "secondary_v1_mapped.json", secondary)

    # summary
    lines = [
        f"# Human coding v2 analysis — {LABEL}",
        "",
        f"- Coders present: {sorted(present)}",
        f"- Primary (C, D) available: {have_primary}",
    ]
    if "A" in present and "B" in present:
        ab = secondary.get("ab_binary_erosion", {})
        lines.append(
            f"- Secondary A–B α (binary erosion, v1→v2): "
            f"{ab.get('alpha')} ci95={ab.get('ci95')} n={ab.get('n')}"
        )
        abq = secondary.get("ab_q1_three_way", {})
        lines.append(
            f"- Secondary A–B α (Q1 three-way, v1→v2): "
            f"{abq.get('alpha')} ci95={abq.get('ci95')} n={abq.get('n')}"
        )
        er = secondary.get("ab_binary_erosion_agree_count", {})
        lines.append(f"- A–B binary erosion raw agree: {er.get('agree')}/{er.get('n')}")
    if have_primary:
        lines.append(
            f"- Primary C–D α Q1: {reliability['q1_three_way'].get('alpha')} "
            f"ci95={reliability['q1_three_way'].get('ci95')}"
        )
    lines += ["", "Themes T1–T7 are not analysed (D81).", ""]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "label": LABEL,
        "present": sorted(present),
        "have_primary": have_primary,
        "reliability": reliability,
        "secondary": secondary,
    }


# ---------------------------------------------------------------------------
# Synthetic C/D dry-run
# ---------------------------------------------------------------------------


def _write_v2_filled(
    path: Path,
    items: list[tuple[str, str]],
    seed: int,
) -> None:
    """Write a filled v2 coding sheet for synthetic dry-run (no notes content printed)."""
    rng = np.random.default_rng(seed)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Coding"
    ws.append(["row", "ORIGINAL", "REVISED", "Q1_demand", "Q2_decides_itself", "Q3_overall", "notes"])
    q1_choices = ["Weaker", "Same", "Stronger"]
    q3_choices = ["Worse", "Neutral", "Better", "Unsure"]
    for i, (o, r) in enumerate(items, 1):
        q1 = q1_choices[int(rng.integers(0, 3))]
        q2 = None
        if q1 == "Weaker":
            q2 = "Yes" if rng.random() < 0.4 else "No"
        q3 = q3_choices[int(rng.integers(0, 4))]
        ws.append([i, o, r, q1, q2, q3, None])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def synthetic_cd_dry_run(out_root: Path | None = None) -> dict[str, Any]:
    base = study_root()
    out = out_root or (base / "out")
    key = pd.read_csv(out / "sampling_key.csv")
    smap = pd.read_csv(out / "sheet_map.csv")
    smap["coder"] = smap["coder"].astype(str)
    mapping = pd.read_csv(out / "v2" / "mapping_v2.csv")
    map_a = smap[smap.coder == "A"].set_index("row")["key_id"].to_dict()
    key_by = key.set_index("key_id")

    syn = out / "synthetic_v2"
    syn.mkdir(parents=True, exist_ok=True)
    returned_syn = syn / "returned"
    returned_syn.mkdir(parents=True, exist_ok=True)

    for coder, seed in (("C", SEED + 21), ("D", SEED + 22)):
        sub = mapping[mapping.coder == coder].sort_values("row")
        items = []
        for _, m in sub.iterrows():
            kid = map_a[int(m["coderA_row"])]
            items.append((str(key_by.loc[kid, "original"]), str(key_by.loc[kid, "revised"])))
        _write_v2_filled(returned_syn / f"coder{coder}.xlsx", items, seed)

    # Also need A/B in returned for full path, or only run primary on synthetic C/D
    # Copy real A/B if present
    real_ret = out / "returned"
    for name in ("coderA.xlsx", "coderB.csv"):
        src = real_ret / name
        if src.exists():
            (returned_syn / name).write_bytes(src.read_bytes())

    write_provenance(returned_syn)
    table, report = normalize_returns(
        returned_syn,
        key_path=out / "sampling_key.csv",
        sheet_map_path=out / "sheet_map.csv",
        mapping_v2_path=out / "v2" / "mapping_v2.csv",
    )
    dump_json(syn / "normalize_report.json", report)
    table.to_csv(syn / "normalized_codes.csv", index=False)
    info = analyze_table(table, key, syn / "results", primary_coders=("C", "D"))
    return {"n_rows": len(table), "report": report, "analysis": info, "out": str(syn)}


def run_interim() -> dict[str, Any]:
    """Secondary on A/B + synthetic C/D dry-run of primary path."""
    base = study_root()
    out = base / "out"
    returned = out / "returned"
    write_provenance(returned)
    table, report = normalize_returns(
        returned,
        key_path=out / "sampling_key.csv",
        sheet_map_path=out / "sheet_map.csv",
        mapping_v2_path=out / "v2" / "mapping_v2.csv",
    )
    dump_json(returned / "normalize_report.json", report)
    table.to_csv(returned / "normalized_codes.csv", index=False)

    practice_json = v2_root() / "materials" / "practice_items_v2.json"
    score_practice(returned, practice_json, returned / "practice_scores.json")

    key = pd.read_csv(out / "sampling_key.csv")
    res_out = results_dir()
    info = analyze_table(table, key, res_out, primary_coders=("C", "D"))
    dry = synthetic_cd_dry_run(out)
    return {"normalize_report": report, "analysis": info, "synthetic": dry}


def verify_stimuli(
    coder_a_sheet: Path,
    mapping_provided: Path,
    rebuild_dir: Path,
) -> dict[str, Any]:
    """Re-run build into rebuild_dir and compare mapping + texts."""
    import os
    import subprocess
    import sys

    rebuild_dir.mkdir(parents=True, exist_ok=True)
    env = dict(**os.environ)
    env["SKIP_PDF"] = "1"
    subprocess.run(
        [
            sys.executable,
            str(v2_root() / "build_v2.py"),
            str(coder_a_sheet),
            str(rebuild_dir),
        ],
        check=True,
        env=env,
    )
    rebuilt = rebuild_dir / "mapping_v2.csv"
    provided = mapping_provided.read_text(encoding="utf-8")
    got = rebuilt.read_text(encoding="utf-8")
    mapping_identical = provided == got
    return {"mapping_identical": mapping_identical, "rebuild_dir": str(rebuild_dir)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--interim", action="store_true", help="A/B secondary + synthetic C/D dry-run")
    p.add_argument("--synthetic-only", action="store_true")
    args = p.parse_args()
    if args.synthetic_only:
        info = synthetic_cd_dry_run()
        print(json.dumps({"synthetic": True, "n_rows": info["n_rows"]}, indent=2, sort_keys=True))
        return
    if args.interim:
        info = run_interim()
        print(
            json.dumps(
                {
                    "interim": True,
                    "coders": info["analysis"]["present"],
                    "have_primary": info["analysis"]["have_primary"],
                    "ab_binary_alpha": info["analysis"]["secondary"].get("ab_binary_erosion"),
                    "synthetic_n_rows": info["synthetic"]["n_rows"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    p.error("use --interim or --synthetic-only")


if __name__ == "__main__":
    main()
