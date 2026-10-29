#!/usr/bin/env python3
"""Ingest and analyze human-coding returns (v2 instrument; EXPLORATORY).

Implements D81 (amended by D82/D83). Writes only under
results/exploratory_aie/human_coding/. Never prints or commits lastModifiedBy,
coder names, or notes text.
"""

from __future__ import annotations

import argparse
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
from scipy.stats import fisher_exact

SEED = 20261004
LABEL = "EXPLORATORY (not preregistered)"
N_BOOT = 1000
N_PERM_ALIGN = 10_000

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
V1_Q2_TO_V2 = {"B": "Yes", "A": "No", "C": "No"}
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

STRATUM_ORDER = [
    "COR2",
    "SELF1",
    "HON4",
    "CARE2",
    "AGENT1",
    "OTHER_COR",
    "NONERODE_COR2",
    "NONERODE_SELF1",
    "NONERODE_HON4",
    "NONERODE_CARE2",
    "NONERODE_AGENT1",
]
OVERSIGHT_STRATA = frozenset({"COR2", "OTHER_COR"})
OTHER_STRATA = frozenset({"SELF1", "HON4", "CARE2", "AGENT1"})


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
# Reliability / agreement helpers
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
    if not rater_lists or not rater_lists[0]:
        return float("nan")
    n_units = len(rater_lists[0])
    assert all(len(r) == n_units for r in rater_lists)
    coincidence: dict[tuple[Any, Any], float] = {}
    n_pairable = 0.0
    for u in range(n_units):
        vals = [r[u] for r in rater_lists if r[u] is not None]
        m = len(vals)
        if m < 2:
            continue
        n_pairable += m * (m - 1)
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
    do_num = sum(o for (a, b), o in coincidence.items() if a != b)
    do = do_num / n_pairable
    n_c: Counter[Any] = Counter()
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
    boots = [values_fn(rng.integers(0, n, size=n)) for _ in range(n_boot)]
    lo, hi = np.nanquantile(np.asarray(boots, dtype=float), [0.025, 0.975])
    return float(point), float(lo), float(hi)


def wilson_ci(successes: int, n: int, z: float = 1.96) -> list[float | None]:
    if n <= 0:
        return [None, None]
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0.0, centre - half), min(1.0, centre + half)]


def confusion(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict[str, Any]:
    mat = {a: {b: 0 for b in labels} for a in labels}
    for t, p in zip(y_true, y_pred):
        if t not in mat:
            mat[t] = {b: 0 for b in labels}
        if p not in mat[t]:
            for row in mat.values():
                row.setdefault(p, 0)
        mat[t][p] = mat[t].get(p, 0) + 1
    agree = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return {
        "labels": labels,
        "matrix": mat,
        "n": len(y_true),
        "pct_agreement": (agree / len(y_true)) if y_true else None,
        "cohen_kappa": cohen_kappa(y_true, y_pred) if y_true else None,
    }


def binary_erosion_metrics(human: list[str | None], judge: list[str | None]) -> dict[str, Any]:
    """Judge = reference for precision; human = reference for recall (as specified).

    precision = P(human Weaker | judge Weaker)
    recall = P(judge Weaker | human Weaker)
    """
    pairs = [(h, j) for h, j in zip(human, judge) if h is not None and j is not None]
    if not pairs:
        return {"n": 0}
    h_bin = [1 if h == "Weaker" else 0 for h, _ in pairs]
    j_bin = [1 if j == "Weaker" else 0 for _, j in pairs]
    conf = confusion([str(x) for x in j_bin], [str(x) for x in h_bin], ["0", "1"])
    n_judge_w = sum(j_bin)
    n_human_w = sum(h_bin)
    n_both_w = sum(1 for h, j in zip(h_bin, j_bin) if h == 1 and j == 1)
    prec = (n_both_w / n_judge_w) if n_judge_w else None
    rec = (n_both_w / n_human_w) if n_human_w else None
    return {
        **conf,
        "precision_human_given_judge_weaker": prec,
        "precision_wilson95": wilson_ci(n_both_w, n_judge_w) if n_judge_w else [None, None],
        "recall_judge_given_human_weaker": rec,
        "recall_wilson95": wilson_ci(n_both_w, n_human_w) if n_human_w else [None, None],
        "n_judge_weaker": n_judge_w,
        "n_human_weaker": n_human_w,
        "n_both_weaker": n_both_w,
    }


# ---------------------------------------------------------------------------
# Provenance
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


def write_provenance(returned_dir: Path) -> dict[str, Any]:
    prov_path = returned_dir / "provenance.json"
    prov: dict[str, Any] = {}
    if prov_path.exists():
        try:
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prov = {}
    for path in sorted(returned_dir.iterdir()):
        if path.name.startswith(".") or path.name == "provenance.json":
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in {".json", ".csv"} and path.name.startswith("normalize"):
            continue
        if path.name in {"normalized_codes.csv", "practice_scores.json", "normalize_report.json"}:
            continue
        entry: dict[str, Any] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "format": path.suffix.lower().lstrip(".") or "unknown",
        }
        if path.suffix.lower() == ".xlsx":
            entry.update(_xlsx_doc_props(path.read_bytes()))
        elif path.suffix.lower() == ".txt":
            entry["format"] = "csv_text"
        prov[path.name] = entry
    dump_json(prov_path, prov)
    return prov


# ---------------------------------------------------------------------------
# Readers + v1→v2
# ---------------------------------------------------------------------------


def map_v1_to_v2(q1: str | None, q3: str | None) -> tuple[str | None, str | None, str | None]:
    q1v2 = V1_Q1_TO_V2.get(q1) if q1 else None
    q2v2 = V1_Q2_TO_V2.get(q1) if q1v2 == "Weaker" and q1 else None
    q3v2 = V1_Q3_TO_V2.get(q3) if q3 else None
    return q1v2, q2v2, q3v2


def _norm_q1(v: Any) -> str | None:
    s = _as_str(v)
    if s is None:
        return None
    t = s.strip().title()
    return t if t in Q1V2 else s


def _norm_q2(v: Any) -> str | None:
    s = _as_str(v)
    if s is None:
        return None
    t = s.strip().title()
    if t in ("Y", "Yes"):
        return "Yes"
    if t in ("N", "No"):
        return "No"
    return t if t in Q2V2 else s


def _norm_q3(v: Any) -> str | None:
    s = _as_str(v)
    if s is None:
        return None
    t = s.strip().title()
    return t if t in Q3V2 else s


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
    """Read v2 returns: xlsx/csv/txt. May lack row and/or ORIGINAL/REVISED."""
    suf = path.suffix.lower()
    if suf in {".csv", ".txt"}:
        df = pd.read_csv(path)
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
    if "row" not in df.columns:
        df.insert(0, "row", range(1, len(df) + 1))
    else:
        df["row"] = df["row"].astype(int)
    df["Q1_demand"] = df["Q1_demand"].map(_norm_q1)
    df["Q2_decides_itself"] = df["Q2_decides_itself"].map(_norm_q2)
    df["Q3_overall"] = df["Q3_overall"].map(_norm_q3)
    return df


def alignment_check_coder_c(
    q1_c_by_key: list[str | None],
    q1_d_by_key: list[str | None],
    *,
    seed: int = SEED,
    n_perm: int = N_PERM_ALIGN,
) -> dict[str, Any]:
    """Raw Q1 agreement C vs D under the claimed mapping, vs permutations of C's labels."""
    pairs = [(a, b) for a, b in zip(q1_c_by_key, q1_d_by_key) if a is not None and b is not None]
    n = len(pairs)
    if n == 0:
        raise SystemExit("alignment check: no paired Q1 values")
    c_obs = [a for a, _ in pairs]
    d_obs = [b for _, b in pairs]
    observed = sum(1 for a, b in zip(c_obs, d_obs) if a == b)
    rng = np.random.default_rng(seed)
    c_arr = np.array(c_obs, dtype=object)
    perms = []
    for _ in range(n_perm):
        shuffled = c_arr[rng.permutation(n)]
        perms.append(int(sum(1 for a, b in zip(shuffled, d_obs) if a == b)))
    perms_a = np.asarray(perms, dtype=float)
    p_ge = float(np.mean(perms_a >= observed))
    return {
        "label": LABEL,
        "n": n,
        "observed_agree": int(observed),
        "observed_pct": observed / n,
        "permutation_mean": float(np.mean(perms_a)),
        "permutation_p999": float(np.quantile(perms_a, 0.999)),
        "p_value_ge_observed": p_ge,
        "n_permutations": n_perm,
        "seed": seed,
        "passed_above_p999": bool(observed > np.quantile(perms_a, 0.999)),
    }


def normalize_returns(
    returned_dir: Path,
    *,
    key_path: Path,
    sheet_map_path: Path,
    mapping_v2_path: Path,
    alignment_out: Path | None = None,
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
        "invalid_values": [],
        "coders_present": [],
        "alignment_c": None,
    }
    rows_out: list[dict[str, Any]] = []

    def check_texts(coder: str, row: int, key_id: str, orig: Any, rev: Any) -> None:
        kr = key_by.loc[key_id]
        if _norm_ws(orig) != _norm_ws(kr["original"]) or _norm_ws(rev) != _norm_ws(kr["revised"]):
            report["text_mismatches"].append({"coder": coder, "row": row, "key_id": key_id})

    def validate_v2(coder: str, row: int, q1: str | None, q2: str | None, q3: str | None) -> None:
        if q1 is not None and q1 not in Q1V2:
            report["invalid_values"].append({"coder": coder, "row": row, "field": "Q1v2", "value": q1})
        if q2 is not None and q2 not in Q2V2:
            report["invalid_values"].append({"coder": coder, "row": row, "field": "Q2v2", "value": q2})
        if q3 is not None and q3 not in Q3V2:
            report["invalid_values"].append({"coder": coder, "row": row, "field": "Q3v2", "value": q3})
        if q1 is None:
            report["missing"].append({"coder": coder, "row": row, "field": "Q1v2"})
        if q3 is None:
            report["missing"].append({"coder": coder, "row": row, "field": "Q3v2"})
        if q1 == "Weaker" and q2 is None:
            report["q2_flags"].append({"coder": coder, "row": row, "flag": "Q2_missing_when_Weaker"})
        if q1 is not None and q1 != "Weaker" and q2 is not None:
            report["q2_flags"].append({"coder": coder, "row": row, "flag": "Q2_present_when_not_Weaker"})

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

    # --- B ---
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
            candidates = sorted(returned_dir.glob(f"coder{coder}.*"))
            candidates = [p for p in candidates if p.suffix.lower() in {".xlsx", ".csv", ".txt"}]
            if not candidates:
                continue
            report["coders_present"].append(coder)
            path = candidates[0]
            df = read_v2_sheet(path)
            sub = mapping_v2[mapping_v2.coder == coder].sort_values("row")
            has_stim = "ORIGINAL" in df.columns and "REVISED" in df.columns

            if coder == "C":
                rows_set = set(int(x) for x in df["row"].tolist())
                if rows_set != set(range(1, 121)):
                    raise SystemExit(f"coder C: row values must be exactly 1–120 once; got {sorted(rows_set)[:5]}… n={len(rows_set)}")

            if len(df) != 120:
                raise SystemExit(f"coder {coder}: expected 120 rows, got {len(df)}")

            for _, m in sub.iterrows():
                row = int(m["row"])
                a_row = int(m["coderA_row"])
                key_id = map_a[a_row]
                rr = df[df.row == row]
                if rr.empty:
                    report["missing"].append({"coder": coder, "row": row, "field": "row"})
                    continue
                r = rr.iloc[0]
                if has_stim:
                    check_texts(coder, row, key_id, r["ORIGINAL"], r["REVISED"])
                q1 = r["Q1_demand"] if not _blank(r["Q1_demand"]) else None
                q2 = r["Q2_decides_itself"] if not _blank(r["Q2_decides_itself"]) else None
                q3 = r["Q3_overall"] if not _blank(r["Q3_overall"]) else None
                # Re-normalise in case pandas coerced None→NaN in object/float columns
                q1 = _norm_q1(q1)
                q2 = _norm_q2(q2)
                q3 = _norm_q3(q3)
                validate_v2(coder, row, q1, q2, q3)
                rows_out.append(
                    {
                        "coder": coder,
                        "instrument": "v2",
                        "row": row,
                        "key_id": key_id,
                        "Q1v2": q1 if q1 in Q1V2 else q1,
                        "Q2v2": q2,  # keep even if flagged
                        "Q3v2": q3,
                        "Q1v1": None,
                    }
                )

    if report["text_mismatches"]:
        raise SystemExit(f"TEXT MISMATCH: {report['text_mismatches'][:5]}")
    if report["invalid_values"]:
        raise SystemExit(f"INVALID VALUES: {report['invalid_values'][:5]}")

    table = pd.DataFrame(rows_out)

    # Statistical alignment for C (D83) when C has no stimulus columns
    c_paths = sorted(returned_dir.glob("coderC.*"))
    c_paths = [p for p in c_paths if p.suffix.lower() in {".xlsx", ".csv", ".txt"}]
    c_needs_stat_align = False
    if c_paths:
        cdf = read_v2_sheet(c_paths[0])
        c_needs_stat_align = "ORIGINAL" not in cdf.columns or "REVISED" not in cdf.columns

    if (
        c_needs_stat_align
        and "C" in report["coders_present"]
        and "D" in report["coders_present"]
    ):
        key_ids = sorted(key["key_id"].tolist())

        def ser(coder: str) -> list[Any]:
            sub = table[table.coder == coder].set_index("key_id")
            return [sub.loc[k, "Q1v2"] if k in sub.index else None for k in key_ids]

        align = alignment_check_coder_c(ser("C"), ser("D"))
        report["alignment_c"] = align
        if alignment_out is not None:
            dump_json(alignment_out, align)
        if not align["passed_above_p999"]:
            raise SystemExit(
                "ALIGNMENT FAIL: C–D Q1 agreement not above 99.9th percentile of "
                f"permutations (observed={align['observed_agree']}, "
                f"p999={align['permutation_p999']}). Misalignment likely."
            )

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
        q1_ok = q2_ok = q2_n = 0
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
# Analysis
# ---------------------------------------------------------------------------


def _alpha_boot(c1: list[Any], c2: list[Any], rng: np.random.Generator) -> dict[str, Any]:
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


def _vs_judge_full(human: list[str | None], judge: list[str | None]) -> dict[str, Any]:
    labels3 = ["Weaker", "Same", "Stronger"]
    pairs = [(h, j) for h, j in zip(human, judge) if h is not None and j is not None]
    if not pairs:
        return {"n": 0}
    h_list = [p[0] for p in pairs]
    j_list = [p[1] for p in pairs]
    three = confusion(j_list, h_list, labels3)
    binary = binary_erosion_metrics(human, judge)
    return {"three_way": three, "binary_erosion": binary}


def _stratum_pool(stratum: str) -> str | None:
    if stratum in OVERSIGHT_STRATA:
        return "oversight"
    if stratum in OTHER_STRATA:
        return "other"
    return None  # non-erosion etc.


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
    strata = [str(key_by.loc[k, "stratum"]) if k in key_by.index else None for k in key_ids]

    def series(coder: str, col: str) -> list[Any]:
        sub = table[table.coder == coder].set_index("key_id")
        return [sub.loc[k, col] if k in sub.index else None for k in key_ids]

    present = set(table.coder.unique())

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
        judge_mimo.append(None if _blank(f) else FATE_TO_Q1V2.get(str(f)))
    fate_gpt = [str(key_by.loc[k, "fate_gpt54"]) if k in key_by.index else None for k in key_ids]

    c_pri, d_pri = primary_coders
    have_primary = c_pri in present and d_pri in present

    reliability: dict[str, Any] = {
        "label": LABEL,
        "primary_coders": list(primary_coders),
        "have_primary": have_primary,
    }
    hvj: dict[str, Any] = {"label": LABEL, "gpt54": {}, "mimo": {}}
    q2_vs: dict[str, Any] = {"label": LABEL}
    secondary: dict[str, Any] = {"label": LABEL, "note": "A and B used v1 mapped to v2"}
    oversight: dict[str, Any] = {"label": LABEL, "exploratory": True}
    by_stratum_rows: list[dict[str, Any]] = []

    if have_primary:
        q1_c = series(c_pri, "Q1v2")
        q1_d = series(d_pri, "Q1v2")
        er_c = [None if x is None else (x == "Weaker") for x in q1_c]
        er_d = [None if x is None else (x == "Weaker") for x in q1_d]
        reliability["q1_three_way"] = _alpha_boot(q1_c, q1_d, rng)
        reliability["binary_erosion"] = _alpha_boot(er_c, er_d, rng)

        q2_c = series(c_pri, "Q2v2")
        q2_d = series(d_pri, "Q2v2")
        both_weak = [i for i, (a, b) in enumerate(zip(q1_c, q1_d)) if a == "Weaker" and b == "Weaker"]
        reliability["q2_both_weaker"] = _alpha_boot(
            [q2_c[i] for i in both_weak], [q2_d[i] for i in both_weak], rng
        )

        q3_c = series(c_pri, "Q3v2")
        q3_d = series(d_pri, "Q3v2")
        q3_idx = [
            i
            for i, (a, b) in enumerate(zip(q3_c, q3_d))
            if a is not None and b is not None and a != "Unsure" and b != "Unsure"
        ]
        reliability["q3_excl_unsure"] = _alpha_boot(
            [q3_c[i] for i in q3_idx], [q3_d[i] for i in q3_idx], rng
        )

        consensus_q1 = [a if a == b else None for a, b in zip(q1_c, q1_d)]
        consensus_q2 = [
            (q2_c[i] if q2_c[i] == q2_d[i] else None) if i in set(both_weak) else None
            for i in range(len(key_ids))
        ]
        consensus_q3 = [a if a == b else None for a, b in zip(q3_c, q3_d)]

        for name, human in [(c_pri, q1_c), (d_pri, q1_d), ("consensus", consensus_q1)]:
            hvj["gpt54"][f"coder_{name}" if name != "consensus" else "consensus"] = _vs_judge_full(
                human, judge_gpt
            )
            hvj["mimo"][f"coder_{name}" if name != "consensus" else "consensus"] = _vs_judge_full(
                human, judge_mimo
            )

        # Q2 vs SUBORDINATED
        q2_vs["n_both_weaker"] = len(both_weak)
        for lab, q2s in [(c_pri, q2_c), (d_pri, q2_d)]:
            y = [1 if q2s[i] == "Yes" else 0 for i in both_weak]
            j = [1 if fate_gpt[i] == "SUBORDINATED" else 0 for i in both_weak]
            q2_vs[f"coder_{lab}_vs_subordinated"] = {
                "pct_agreement": (sum(a == b for a, b in zip(y, j)) / len(y)) if y else None,
                "cohen_kappa": cohen_kappa(y, j) if y else None,
                "n": len(y),
                "n_yes": sum(y),
                "n_subordinated": sum(j),
            }
        # consensus Q2 on both-weaker rows where C and D agree on Q2
        cons_idx = [i for i in both_weak if q2_c[i] is not None and q2_c[i] == q2_d[i]]
        y = [1 if q2_c[i] == "Yes" else 0 for i in cons_idx]
        j = [1 if fate_gpt[i] == "SUBORDINATED" else 0 for i in cons_idx]
        q2_vs["consensus_vs_subordinated"] = {
            "pct_agreement": (sum(a == b for a, b in zip(y, j)) / len(y)) if y else None,
            "cohen_kappa": cohen_kappa(y, j) if y else None,
            "n": len(y),
            "n_yes": sum(y),
            "n_subordinated": sum(j),
        }

        # By stratum
        for who, q1s, q2s, q3s in [
            (c_pri, q1_c, q2_c, q3_c),
            (d_pri, q1_d, q2_d, q3_d),
            ("consensus", consensus_q1, consensus_q2, consensus_q3),
        ]:
            for stratum in STRATUM_ORDER:
                idxs = [i for i, s in enumerate(strata) if s == stratum]
                if who == "consensus":
                    idxs = [i for i in idxs if q1s[i] is not None]
                n = len(idxs)
                q1_counts = Counter(q1s[i] for i in idxs if q1s[i] is not None)
                weak_idxs = [i for i in idxs if q1s[i] == "Weaker"]
                n_weak = len(weak_idxs)
                n_q2_yes = sum(1 for i in weak_idxs if q2s[i] == "Yes")
                q3_w = Counter(q3s[i] for i in weak_idxs if q3s[i] is not None)
                by_stratum_rows.append(
                    {
                        "label": LABEL,
                        "coder": who,
                        "stratum": stratum,
                        "n": n,
                        "n_Weaker": q1_counts.get("Weaker", 0),
                        "n_Same": q1_counts.get("Same", 0),
                        "n_Stronger": q1_counts.get("Stronger", 0),
                        "pct_Weaker": (q1_counts.get("Weaker", 0) / n) if n else None,
                        "n_weaker_Q2_Yes": n_q2_yes,
                        "pct_weaker_Q2_Yes": (n_q2_yes / n_weak) if n_weak else None,
                        "n_weaker_Q3_Worse": q3_w.get("Worse", 0),
                        "n_weaker_Q3_Neutral": q3_w.get("Neutral", 0),
                        "n_weaker_Q3_Better": q3_w.get("Better", 0),
                        "n_weaker_Q3_Unsure": q3_w.get("Unsure", 0),
                    }
                )

        # Oversight vs other Q3 among Weaker
        fisher_block: dict[str, Any] = {}
        q3_pool_block: dict[str, Any] = {}
        for who, q1s, q3s in [
            (c_pri, q1_c, q3_c),
            (d_pri, q1_d, q3_d),
            ("consensus", consensus_q1, consensus_q3),
        ]:
            pools: dict[str, Counter[str]] = {"oversight": Counter(), "other": Counter()}
            for i, s in enumerate(strata):
                if q1s[i] != "Weaker" or q3s[i] is None:
                    continue
                pool = _stratum_pool(str(s))
                if pool is None:
                    continue
                pools[pool][q3s[i]] += 1
            q3_pool_block[who] = {
                pool: dict(ctr) for pool, ctr in pools.items()
            }
            # Fisher: Worse vs not-Worse × oversight vs other
            a = pools["oversight"].get("Worse", 0)
            b = sum(v for k, v in pools["oversight"].items() if k != "Worse")
            c = pools["other"].get("Worse", 0)
            d = sum(v for k, v in pools["other"].items() if k != "Worse")
            table2 = [[a, b], [c, d]]
            if sum(sum(row) for row in table2) > 0 and (a + b) > 0 and (c + d) > 0:
                oddsratio, pval = fisher_exact(table2)
            else:
                oddsratio, pval = float("nan"), float("nan")
            fisher_block[who] = {
                "table_Worse_vs_not_by_oversight_other": {
                    "oversight_Worse": a,
                    "oversight_not_Worse": b,
                    "other_Worse": c,
                    "other_not_Worse": d,
                },
                "odds_ratio": float(oddsratio) if oddsratio == oddsratio else None,
                "p_value": float(pval) if pval == pval else None,
            }
        oversight["q3_among_weaker_by_pool"] = q3_pool_block
        oversight["fisher_worse_vs_pool"] = fisher_block
    else:
        reliability["note"] = f"Primary coders {primary_coders} not both present; primary metrics deferred."

    pd.DataFrame(by_stratum_rows).to_csv(out_dir / "by_stratum_v2.csv", index=False)

    # Keep q3_by_stratum.csv for backward compat with older tests (simple long form)
    q3_rows = []
    for coder in sorted(present):
        sub = table[table.coder == coder]
        for _, r in sub.iterrows():
            stratum = key_by.loc[r["key_id"], "stratum"] if r["key_id"] in key_by.index else None
            q3_rows.append({"label": LABEL, "coder": coder, "stratum": stratum, "Q3v2": r["Q3v2"]})
    q3_df = pd.DataFrame(q3_rows)
    if len(q3_df):
        counts = q3_df.groupby(["stratum", "coder", "Q3v2"], dropna=False).size().reset_index(name="n")
        totals = counts.groupby(["stratum", "coder"])["n"].transform("sum")
        counts["pct"] = counts["n"] / totals
        counts.insert(0, "label", LABEL)
        counts.to_csv(out_dir / "q3_by_stratum.csv", index=False)

    # Secondary: A/B + four-coder pairwise (binary + three-way)
    if "A" in present and "B" in present:
        q1_a = series("A", "Q1v2")
        q1_b = series("B", "Q1v2")
        er_a = [None if x is None else (x == "Weaker") for x in q1_a]
        er_b = [None if x is None else (x == "Weaker") for x in q1_b]
        secondary["ab_q1_three_way"] = _alpha_boot(q1_a, q1_b, rng)
        secondary["ab_binary_erosion"] = _alpha_boot(er_a, er_b, rng)
        both = [
            (a == "Weaker", b == "Weaker")
            for a, b in zip(q1_a, q1_b)
            if a is not None and b is not None
        ]
        secondary["ab_binary_erosion_agree_count"] = {
            "agree": sum(1 for a, b in both if a == b),
            "n": len(both),
        }
        secondary["gpt54_vs_A"] = _vs_judge_full(q1_a, judge_gpt)
        secondary["gpt54_vs_B"] = _vs_judge_full(q1_b, judge_gpt)

        coders_for_four = [c for c in ("A", "B", "C", "D") if c in present]
        secondary["coders_in_multi"] = coders_for_four
        secondary["note_instruments"] = "A and B used v1 (mapped to v2); C and D used v2 when present."
        pairwise_q1 = {}
        pairwise_bin = {}
        for i, c1 in enumerate(coders_for_four):
            for c2 in coders_for_four[i + 1 :]:
                s1, s2 = series(c1, "Q1v2"), series(c2, "Q1v2")
                pairwise_q1[f"{c1}_{c2}"] = _alpha_boot(s1, s2, rng)
                pairwise_bin[f"{c1}_{c2}"] = _alpha_boot(
                    [None if x is None else (x == "Weaker") for x in s1],
                    [None if x is None else (x == "Weaker") for x in s2],
                    rng,
                )
        secondary["pairwise_q1_alpha"] = pairwise_q1
        secondary["pairwise_binary_erosion_alpha"] = pairwise_bin
        if len(coders_for_four) >= 2:
            rater_q1 = [series(c, "Q1v2") for c in coders_for_four]
            rater_bin = [
                [None if x is None else (x == "Weaker") for x in series(c, "Q1v2")]
                for c in coders_for_four
            ]

            def multi_q1(idx):
                return krippendorff_alpha_nominal_multi([[lst[i] for i in idx] for lst in rater_q1])

            def multi_bin(idx):
                return krippendorff_alpha_nominal_multi([[lst[i] for i in idx] for lst in rater_bin])

            a1, lo1, hi1 = bootstrap_ci(multi_q1, len(key_ids), rng)
            a2, lo2, hi2 = bootstrap_ci(multi_bin, len(key_ids), rng)
            secondary["four_coder_q1_alpha"] = {
                "alpha": a1,
                "ci95": [lo1, hi1],
                "n_units": len(key_ids),
                "coders": coders_for_four,
            }
            secondary["four_coder_binary_erosion_alpha"] = {
                "alpha": a2,
                "ci95": [lo2, hi2],
                "n_units": len(key_ids),
                "coders": coders_for_four,
            }

    dump_json(out_dir / "reliability_v2.json", reliability)
    dump_json(out_dir / "human_vs_judge_v2.json", hvj)
    dump_json(out_dir / "q2_vs_subordinated.json", q2_vs)
    dump_json(out_dir / "oversight_vs_other_q3.json", oversight)
    dump_json(out_dir / "secondary_v1_mapped.json", secondary)

    # summary.md
    lines = [
        f"# Human coding v2 analysis — {LABEL}",
        "",
        "## Deviations (D83)",
        "- No practice sheets or time logs collected from C or D.",
        "- C returned a CSV text file without stimuli (statistical alignment).",
        "- D returned a Google Sheets export without a `row` column (textual alignment).",
        "",
        f"- Coders present: {sorted(present)}",
        f"- Primary (C, D) available: {have_primary}",
        "",
    ]
    if have_primary:
        lines += ["## Reliability (C–D)", ""]
        for key_name, title in [
            ("q1_three_way", "Q1 three-way"),
            ("binary_erosion", "Binary erosion (Weaker vs not)"),
            ("q2_both_weaker", "Q2 (both Weaker)"),
            ("q3_excl_unsure", "Q3 excl. Unsure"),
        ]:
            block = reliability.get(key_name, {})
            lines.append(
                f"- **{title}:** α = {block.get('alpha'):.4f} "
                f"[{block.get('ci95')[0]:.4f}, {block.get('ci95')[1]:.4f}] "
                f"(n={block.get('n')})"
                if block.get("alpha") is not None
                else f"- **{title}:** n={block.get('n')}"
            )
        lines += ["", "## Human vs GPT-5.4", ""]
        for who in (c_pri, d_pri, "consensus"):
            keyw = f"coder_{who}" if who != "consensus" else "consensus"
            block = hvj["gpt54"].get(keyw, {})
            three = block.get("three_way", {})
            binary = block.get("binary_erosion", {})
            lines.append(f"### {who}")
            lines.append(
                f"- Three-way: pct agree = {three.get('pct_agreement')}, "
                f"κ = {three.get('cohen_kappa')}, n = {three.get('n')}"
            )
            lines.append(
                f"- Binary: pct agree = {binary.get('pct_agreement')}, "
                f"κ = {binary.get('cohen_kappa')}, "
                f"precision (human|judge Weaker) = {binary.get('precision_human_given_judge_weaker')} "
                f"Wilson {binary.get('precision_wilson95')}, "
                f"recall (judge|human Weaker) = {binary.get('recall_judge_given_human_weaker')} "
                f"Wilson {binary.get('recall_wilson95')}"
            )
            lines.append(f"- Confusion (three-way, judge→human): `{json.dumps(three.get('matrix'))}`")
            lines.append("")
        lines += ["## Q2 vs SUBORDINATED (both Weaker)", ""]
        for k in sorted(q2_vs.keys()):
            if k in {"label", "n_both_weaker"}:
                continue
            lines.append(f"- **{k}:** {q2_vs[k]}")
        lines.append(f"- n both Weaker: {q2_vs.get('n_both_weaker')}")
        lines += ["", "## Oversight vs other Q3 among Weaker (exploratory)", ""]
        lines.append(f"```json\n{json.dumps(oversight, indent=2, sort_keys=True)}\n```")
        lines.append("")
    if "A" in present and "B" in present:
        lines += ["## Secondary (A/B v1-mapped; pairwise with C/D)", ""]
        lines.append(f"- A–B α Q1: {secondary.get('ab_q1_three_way')}")
        lines.append(f"- A–B α binary: {secondary.get('ab_binary_erosion')}")
        lines.append(f"- A–B binary raw agree: {secondary.get('ab_binary_erosion_agree_count')}")
        lines.append(f"- Four-coder α Q1: {secondary.get('four_coder_q1_alpha')}")
        lines.append(f"- Four-coder α binary: {secondary.get('four_coder_binary_erosion_alpha')}")
        lines.append(f"- Pairwise Q1: {json.dumps(secondary.get('pairwise_q1_alpha'), sort_keys=True)}")
        lines.append(
            f"- Pairwise binary: {json.dumps(secondary.get('pairwise_binary_erosion_alpha'), sort_keys=True)}"
        )
        lines.append("")
    lines += ["Themes T1–T7 are not analysed (D81).", ""]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "label": LABEL,
        "present": sorted(present),
        "have_primary": have_primary,
        "reliability": reliability,
        "secondary": secondary,
        "hvj": hvj,
        "q2_vs": q2_vs,
        "oversight": oversight,
    }


# ---------------------------------------------------------------------------
# Synthetic / CLI
# ---------------------------------------------------------------------------


def _write_v2_filled(path: Path, items: list[tuple[str, str]], seed: int) -> None:
    rng = np.random.default_rng(seed)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Coding"
    ws.append(["row", "ORIGINAL", "REVISED", "Q1_demand", "Q2_decides_itself", "Q3_overall", "notes"])
    for i, (o, r) in enumerate(items, 1):
        q1 = ["Weaker", "Same", "Stronger"][int(rng.integers(0, 3))]
        q2 = ("Yes" if rng.random() < 0.4 else "No") if q1 == "Weaker" else None
        q3 = ["Worse", "Neutral", "Better", "Unsure"][int(rng.integers(0, 4))]
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
        alignment_out=syn / "alignment_check_coderC.json",
    )
    dump_json(syn / "normalize_report.json", report)
    table.to_csv(syn / "normalized_codes.csv", index=False)
    info = analyze_table(table, key, syn / "results", primary_coders=("C", "D"))
    return {"n_rows": len(table), "report": report, "analysis": info, "out": str(syn)}


def run_primary() -> dict[str, Any]:
    """Ingest A/B/C/D from returned/ and write primary analysis outputs."""
    base = study_root()
    out = base / "out"
    returned = out / "returned"
    write_provenance(returned)
    res_out = results_dir()
    table, report = normalize_returns(
        returned,
        key_path=out / "sampling_key.csv",
        sheet_map_path=out / "sheet_map.csv",
        mapping_v2_path=out / "v2" / "mapping_v2.csv",
        alignment_out=res_out / "alignment_check_coderC.json",
    )
    dump_json(returned / "normalize_report.json", report)
    table.to_csv(returned / "normalized_codes.csv", index=False)
    key = pd.read_csv(out / "sampling_key.csv")
    info = analyze_table(table, key, res_out, primary_coders=("C", "D"))
    return {"normalize_report": report, "analysis": info}


def run_interim() -> dict[str, Any]:
    """Legacy interim: A/B only + synthetic C/D."""
    base = study_root()
    out = base / "out"
    returned = out / "returned"
    write_provenance(returned)
    # Temporarily hide C/D if present for interim A/B-only results dir path
    table, report = normalize_returns(
        returned,
        key_path=out / "sampling_key.csv",
        sheet_map_path=out / "sheet_map.csv",
        mapping_v2_path=out / "v2" / "mapping_v2.csv",
    )
    # Filter to A/B for interim-style write if C/D present — prefer run_primary when C/D exist
    if "C" in report["coders_present"] and "D" in report["coders_present"]:
        return run_primary()
    dump_json(returned / "normalize_report.json", report)
    table.to_csv(returned / "normalized_codes.csv", index=False)
    key = pd.read_csv(out / "sampling_key.csv")
    info = analyze_table(table, key, results_dir(), primary_coders=("C", "D"))
    dry = synthetic_cd_dry_run(out)
    return {"normalize_report": report, "analysis": info, "synthetic": dry}


def verify_stimuli(
    coder_a_sheet: Path,
    mapping_provided: Path,
    rebuild_dir: Path,
) -> dict[str, Any]:
    import os
    import subprocess
    import sys

    rebuild_dir.mkdir(parents=True, exist_ok=True)
    env = dict(**os.environ)
    env["SKIP_PDF"] = "1"
    subprocess.run(
        [sys.executable, str(v2_root() / "build_v2.py"), str(coder_a_sheet), str(rebuild_dir)],
        check=True,
        env=env,
    )
    rebuilt = rebuild_dir / "mapping_v2.csv"
    mapping_identical = mapping_provided.read_text(encoding="utf-8") == rebuilt.read_text(encoding="utf-8")
    return {"mapping_identical": mapping_identical, "rebuild_dir": str(rebuild_dir)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--primary", action="store_true", help="Ingest returned A–D and run D81 primary analysis")
    p.add_argument("--interim", action="store_true", help="A/B secondary + synthetic C/D (or primary if C/D present)")
    p.add_argument("--synthetic-only", action="store_true")
    args = p.parse_args()
    if args.primary:
        info = run_primary()
        print(
            json.dumps(
                {
                    "primary": True,
                    "coders": info["analysis"]["present"],
                    "have_primary": info["analysis"]["have_primary"],
                    "alignment": info["normalize_report"].get("alignment_c"),
                    "q1_alpha": info["analysis"]["reliability"].get("q1_three_way"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.synthetic_only:
        info = synthetic_cd_dry_run()
        print(json.dumps({"synthetic": True, "n_rows": info["n_rows"]}, indent=2, sort_keys=True))
        return
    if args.interim:
        info = run_interim()
        print(json.dumps({"interim": True, "coders": info["analysis"]["present"]}, indent=2, sort_keys=True))
        return
    p.error("use --primary, --interim, or --synthetic-only")


if __name__ == "__main__":
    main()
