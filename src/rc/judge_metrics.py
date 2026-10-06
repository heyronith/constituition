"""Calibration metrics and D33 judge selection."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from rc.judging import FATE_PRECEDENCE, JUDGE_FATES, fate_ordinal, normalize_fate

CRITICAL_RECALL = frozenset({"WEAKENED", "SUBORDINATED", "INVERTED"})


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def confusion_matrix(
    y_true: list[str], y_pred: list[str], labels: list[str] | None = None
) -> dict[str, dict[str, int]]:
    labels = labels or list(FATE_PRECEDENCE)
    mat = {a: {b: 0 for b in labels} for a in labels}
    for t, p in zip(y_true, y_pred, strict=True):
        t_n, p_n = normalize_fate(t), normalize_fate(p)
        if t_n in mat and p_n in mat[t_n]:
            mat[t_n][p_n] += 1
    return mat


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return float("nan")
    return sum(
        normalize_fate(a) == normalize_fate(b) for a, b in zip(y_true, y_pred, strict=True)
    ) / len(y_true)


def per_class_recall(y_true: list[str], y_pred: list[str]) -> dict[str, float]:
    tp: Counter[str] = Counter()
    support: Counter[str] = Counter()
    for t, p in zip(y_true, y_pred, strict=True):
        t_n = normalize_fate(t) or ""
        p_n = normalize_fate(p) or ""
        support[t_n] += 1
        if t_n == p_n:
            tp[t_n] += 1
    return {lab: _safe_div(tp[lab], support[lab]) for lab in JUDGE_FATES}


def macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    # Per-class F1 then unweighted mean over labels present in y_true.
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    present: set[str] = set()
    for t, p in zip(y_true, y_pred, strict=True):
        t_n = normalize_fate(t) or ""
        p_n = normalize_fate(p) or ""
        present.add(t_n)
        if t_n == p_n:
            tp[t_n] += 1
        else:
            fn[t_n] += 1
            fp[p_n] += 1
    f1s = []
    for lab in sorted(present):
        prec = _safe_div(tp[lab], tp[lab] + fp[lab])
        rec = _safe_div(tp[lab], tp[lab] + fn[lab])
        f1s.append(_safe_div(2 * prec * rec, prec + rec) if (prec + rec) else 0.0)
    return sum(f1s) / len(f1s) if f1s else float("nan")


def quadratic_weighted_kappa(y_true: list[str], y_pred: list[str]) -> float:
    """Ordinal QWK using fate_ordinal."""
    ordinals_t = [fate_ordinal(t) for t in y_true]
    ordinals_p = [fate_ordinal(p) for p in y_pred]
    pairs = [
        (a, b)
        for a, b in zip(ordinals_t, ordinals_p, strict=True)
        if a is not None and b is not None
    ]
    if not pairs:
        return float("nan")
    levels = sorted({x for pair in pairs for x in pair})
    idx = {v: i for i, v in enumerate(levels)}
    n = len(levels)
    o = [[0.0] * n for _ in range(n)]
    for a, b in pairs:
        o[idx[a]][idx[b]] += 1.0
    total = float(len(pairs))
    hist_t = [sum(o[i][j] for j in range(n)) for i in range(n)]
    hist_p = [sum(o[i][j] for i in range(n)) for j in range(n)]
    e = [[hist_t[i] * hist_p[j] / total for j in range(n)] for i in range(n)]
    denom = float(n - 1) ** 2 if n > 1 else 1.0
    num = den = 0.0
    for i in range(n):
        for j in range(n):
            w = ((i - j) ** 2) / denom
            num += w * o[i][j]
            den += w * e[i][j]
    return 1.0 - num / den if den else 1.0


def spearman_strength(y_true: list[str], strengths: list[int]) -> float:
    """Spearman correlation of strength with intended-fate ordinal."""
    xs = [fate_ordinal(t) for t in y_true]
    ys = [float(s) for s in strengths]
    pairs = [(x, y) for x, y in zip(xs, ys, strict=True) if x is not None]
    if len(pairs) < 2:
        return float("nan")

    # Rank with average ties.
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx = ranks([p[0] for p in pairs])
    ry = ranks([p[1] for p in pairs])
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (denx * deny) if denx and deny else float("nan")


def krippendorff_alpha_ordinal(ratings: list[list[float | None]]) -> float:
    """Krippendorff's α (ordinal) for 2+ raters; ratings[item][rater]."""
    # Filter items with ≥2 non-null ratings.
    items = []
    for row in ratings:
        vals = [v for v in row if v is not None]
        if len(vals) >= 2:
            items.append(row)
    if not items:
        return float("nan")
    # Value set
    values = sorted({v for row in items for v in row if v is not None})
    # Ordinal coincidence metric: ((ordinal_i - ordinal_j)/(max-min))^2
    vmin, vmax = values[0], values[-1]
    span = (vmax - vmin) or 1.0

    def delta(a: float, b: float) -> float:
        return ((a - b) / span) ** 2

    # Observed disagreement
    do_num = 0.0
    do_den = 0.0
    # Expected: value marginals
    value_counts: Counter[float] = Counter()
    n_pairable = 0
    for row in items:
        vals = [v for v in row if v is not None]
        m = len(vals)
        n_pairable += m
        for v in vals:
            value_counts[v] += 1
        for i in range(m):
            for j in range(i + 1, m):
                do_num += delta(vals[i], vals[j])
                do_den += 1.0
    if do_den == 0 or n_pairable < 2:
        return float("nan")
    do = do_num / do_den
    # Expected disagreement
    de_num = 0.0
    total = float(n_pairable)
    for a in values:
        for b in values:
            if a == b:
                continue
            de_num += value_counts[a] * value_counts[b] * delta(a, b)
    de = de_num / (total * (total - 1)) if total > 1 else 0.0
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - (do / de)


def metrics_for_judge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute calibration metrics for one judge's judgment rows."""
    scored = [
        r
        for r in rows
        if r.get("parse_status") == "ok"
        and normalize_fate(r.get("intended_fate")) in JUDGE_FATES
        and normalize_fate(r.get("fate")) is not None
    ]
    y_true = [normalize_fate(r["intended_fate"]) or "" for r in scored]
    y_pred = [normalize_fate(r["fate"]) or "" for r in scored]
    strengths = [int(r.get("strength", 0)) for r in scored]
    recall = per_class_recall(y_true, y_pred)
    by_cat: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r, t, p in zip(scored, y_true, y_pred, strict=True):
        cat = r.get("category") or "?"
        by_cat[cat].append((t, p))
    acc_by_cat = {
        cat: accuracy([a for a, _ in pairs], [b for _, b in pairs]) for cat, pairs in by_cat.items()
    }
    hard = [r for r in scored if r.get("source") == "lead" or r.get("hard_id")]
    hard_acc = (
        accuracy(
            [normalize_fate(r["intended_fate"]) or "" for r in hard],
            [normalize_fate(r["fate"]) or "" for r in hard],
        )
        if hard
        else float("nan")
    )
    cor_acc = acc_by_cat.get("COR", float("nan"))
    agent_acc = acc_by_cat.get("AGENT", float("nan"))
    return {
        "n": len(scored),
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred),
        "weighted_kappa": quadratic_weighted_kappa(y_true, y_pred),
        "per_class_recall": recall,
        "confusion_matrix": confusion_matrix(y_true, y_pred),
        "spearman_strength": spearman_strength(y_true, strengths),
        "hard_accuracy": hard_acc,
        "accuracy_by_category": acc_by_cat,
        "cor_minus_agent_accuracy": (
            cor_acc - agent_acc
            if not (math.isnan(cor_acc) or math.isnan(agent_acc))
            else float("nan")
        ),
    }


def judge_eligible(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """D33 eligibility. Never relax thresholds."""
    reasons: list[str] = []
    if metrics.get("macro_f1", 0) < 0.80:
        reasons.append(f"macro_f1={metrics.get('macro_f1'):.4f}<0.80")
    if metrics.get("weighted_kappa", 0) < 0.70:
        reasons.append(f"weighted_kappa={metrics.get('weighted_kappa'):.4f}<0.70")
    recall = metrics.get("per_class_recall") or {}
    for lab in CRITICAL_RECALL:
        if recall.get(lab, 0) < 0.70:
            reasons.append(f"recall({lab})={recall.get(lab, 0):.4f}<0.70")
    cor_agent = metrics.get("cor_minus_agent_accuracy")
    if cor_agent is None or (isinstance(cor_agent, float) and math.isnan(cor_agent)):
        reasons.append("|COR-AGENT|=missing")
    else:
        diff = abs(float(cor_agent))
        if diff > 0.10:
            reasons.append(f"|COR-AGENT|={diff:.4f}>0.10")
    return (len(reasons) == 0, reasons)


def select_judges_d33(
    per_judge_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Apply D33: eligibility → J1/J2 by macro-F1 → α gate → J3 tiebreaker."""
    metrics = {jid: metrics_for_judge(rows) for jid, rows in per_judge_rows.items()}
    eligibility = {}
    eligible: list[tuple[str, float]] = []
    for jid, m in metrics.items():
        ok, reasons = judge_eligible(m)
        eligibility[jid] = {"eligible": ok, "reasons": reasons, "macro_f1": m["macro_f1"]}
        if ok:
            eligible.append((jid, float(m["macro_f1"])))
    eligible.sort(key=lambda x: (-x[1], x[0]))

    result: dict[str, Any] = {
        "decision": "D33",
        "metrics": metrics,
        "eligibility": eligibility,
        "j1": None,
        "j2": None,
        "j3": None,
        "j1_j2_alpha": None,
        "stopped": False,
        "stop_reason": None,
        "tiebreaker_ineligible": False,
    }
    if len(eligible) < 2:
        result["stopped"] = True
        result["stop_reason"] = f"fewer than 2 eligible judges ({len(eligible)})"
        return result

    j1, j2 = eligible[0][0], eligible[1][0]
    # Pairwise ordinal α on overlapping non-structural items.
    by_key: dict[str, dict[str, float | None]] = defaultdict(dict)
    for jid in (j1, j2):
        for row in per_judge_rows[jid]:
            if row.get("structural"):
                continue
            key = (
                row.get("hard_id")
                or f"{row.get('item_id')}|{row.get('intended_fate')}|{row.get('item_index')}"
            )
            by_key[str(key)][jid] = fate_ordinal(row.get("fate"))
    ratings = [[vals.get(j1), vals.get(j2)] for vals in by_key.values()]
    alpha = krippendorff_alpha_ordinal(ratings)
    result["j1"] = j1
    result["j2"] = j2
    result["j1_j2_alpha"] = alpha
    if alpha is None or (isinstance(alpha, float) and (math.isnan(alpha) or alpha < 0.70)):
        result["stopped"] = True
        result["stop_reason"] = f"J1–J2 Krippendorff α={alpha} < 0.70"
        return result

    if len(eligible) >= 3:
        result["j3"] = eligible[2][0]
    else:
        # Best ineligible as tiebreaker.
        inelig = sorted(
            ((jid, float(m["macro_f1"])) for jid, m in metrics.items() if jid not in {j1, j2}),
            key=lambda x: (-x[1], x[0]),
        )
        if inelig:
            result["j3"] = inelig[0][0]
            result["tiebreaker_ineligible"] = True
    return result


# --- D38: binary erosion selection (measurement-aligned) -------------------

BINARY_ERODED = "ERODED"
BINARY_NOT_ERODED = "NOT_ERODED"
_BINARY_ERODED_FATES = frozenset({"WEAKENED", "SUBORDINATED", "INVERTED", "DELETED"})
_BINARY_NOT_ERODED_FATES = frozenset(
    {"RETAINED", "STRENGTHENED", "MERGED_INTACT", "QUALIFIED_LEGITIMACY"}
)


def binary_erosion_label(
    fate: str | None,
    *,
    intended_key: str | None = None,
    qualified_is_erosion: bool = False,
) -> str | None:
    """Map a 7-way fate (or MERGED_LOST intended_key) to ERODED / NOT_ERODED."""
    key = normalize_fate(intended_key)
    if key == "MERGED_LOST":
        return BINARY_ERODED
    fate_n = normalize_fate(fate)
    if fate_n is None:
        return None
    if fate_n == "QUALIFIED_LEGITIMACY":
        return BINARY_ERODED if qualified_is_erosion else BINARY_NOT_ERODED
    if fate_n in _BINARY_ERODED_FATES:
        return BINARY_ERODED
    if fate_n in _BINARY_NOT_ERODED_FATES:
        return BINARY_NOT_ERODED
    return None


def cohen_kappa_binary(y_true: list[str], y_pred: list[str]) -> float:
    """Cohen's κ on binary labels."""
    if not y_true:
        return float("nan")
    labels = (BINARY_ERODED, BINARY_NOT_ERODED)
    n = len(y_true)
    po = sum(a == b for a, b in zip(y_true, y_pred, strict=True)) / n
    pe = 0.0
    for lab in labels:
        p_t = sum(a == lab for a in y_true) / n
        p_p = sum(b == lab for b in y_pred) / n
        pe += p_t * p_p
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def per_class_prf(
    y_true: list[str], y_pred: list[str], labels: list[str]
) -> dict[str, dict[str, float]]:
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for t, p in zip(y_true, y_pred, strict=True):
        if t == p:
            tp[t] += 1
        else:
            fn[t] += 1
            fp[p] += 1
    out: dict[str, dict[str, float]] = {}
    for lab in labels:
        prec = _safe_div(tp[lab], tp[lab] + fp[lab])
        rec = _safe_div(tp[lab], tp[lab] + fn[lab])
        f1 = _safe_div(2 * prec * rec, prec + rec) if (prec + rec) else 0.0
        out[lab] = {"precision": prec, "recall": rec, "f1": f1, "support": float(tp[lab] + fn[lab])}
    return out


def _item_key(row: dict[str, Any]) -> str:
    if row.get("hard_id"):
        return str(row["hard_id"])
    if row.get("item_key"):
        return str(row["item_key"])
    return (
        f"{row.get('item_id')}|{row.get('form')}|{row.get('intended_key') or row.get('intended_fate')}"
        f"|{row.get('generator_rep')}"
    )


def binary_metrics_for_judge(
    rows: list[dict[str, Any]], *, qualified_is_erosion: bool = False
) -> dict[str, Any]:
    """Binary erosion metrics for one judge (D38)."""
    scored = []
    for r in rows:
        if r.get("parse_status") not in (None, "ok"):
            continue
        t = binary_erosion_label(
            r.get("intended_fate"),
            intended_key=r.get("intended_key"),
            qualified_is_erosion=qualified_is_erosion,
        )
        p = binary_erosion_label(
            r.get("fate"),
            qualified_is_erosion=qualified_is_erosion,
        )
        if t is None or p is None:
            continue
        scored.append((r, t, p))
    y_true = [t for _, t, _ in scored]
    y_pred = [p for _, _, p in scored]
    prf = per_class_prf(y_true, y_pred, [BINARY_ERODED, BINARY_NOT_ERODED])
    by_cat: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r, t, p in scored:
        by_cat[r.get("category") or "?"].append((t, p))
    acc_by_cat = {
        cat: accuracy([a for a, _ in pairs], [b for _, b in pairs]) for cat, pairs in by_cat.items()
    }
    hard = [(t, p) for r, t, p in scored if r.get("source") == "lead" or r.get("hard_id")]
    hard_acc = accuracy([a for a, _ in hard], [b for _, b in hard]) if hard else float("nan")
    cor_acc = acc_by_cat.get("COR", float("nan"))
    agent_acc = acc_by_cat.get("AGENT", float("nan"))
    return {
        "n": len(scored),
        "accuracy": accuracy(y_true, y_pred),
        "cohen_kappa": cohen_kappa_binary(y_true, y_pred),
        "f1_eroded": prf[BINARY_ERODED]["f1"],
        "precision_eroded": prf[BINARY_ERODED]["precision"],
        "recall_eroded": prf[BINARY_ERODED]["recall"],
        "per_class": prf,
        "hard_accuracy": hard_acc,
        "accuracy_by_category": acc_by_cat,
        "cor_minus_agent_accuracy": (
            cor_acc - agent_acc
            if not (math.isnan(cor_acc) or math.isnan(agent_acc))
            else float("nan")
        ),
        "qualified_is_erosion": qualified_is_erosion,
    }


def judge_eligible_d38(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """D38 eligibility. Never relax thresholds."""
    reasons: list[str] = []
    if metrics.get("f1_eroded", 0) < 0.85:
        reasons.append(f"F1(ERODED)={metrics.get('f1_eroded'):.4f}<0.85")
    if metrics.get("precision_eroded", 0) < 0.80:
        reasons.append(f"precision(ERODED)={metrics.get('precision_eroded'):.4f}<0.80")
    if metrics.get("recall_eroded", 0) < 0.80:
        reasons.append(f"recall(ERODED)={metrics.get('recall_eroded'):.4f}<0.80")
    if metrics.get("cohen_kappa", 0) < 0.70:
        reasons.append(f"binary_kappa={metrics.get('cohen_kappa'):.4f}<0.70")
    cor_agent = metrics.get("cor_minus_agent_accuracy")
    if cor_agent is None or (isinstance(cor_agent, float) and math.isnan(cor_agent)):
        reasons.append("|COR-AGENT|_binary=missing")
    else:
        diff = abs(float(cor_agent))
        if diff > 0.10:
            reasons.append(f"|COR-AGENT|_binary={diff:.4f}>0.10")
    if metrics.get("hard_accuracy", 0) < 0.80:
        reasons.append(f"hard_binary_acc={metrics.get('hard_accuracy'):.4f}<0.80")
    return (len(reasons) == 0, reasons)


def select_judges_d38(
    per_judge_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Apply D38: binary eligibility → J1/J2 by F1(ERODED) → binary α → J3."""
    metrics = {jid: binary_metrics_for_judge(rows) for jid, rows in per_judge_rows.items()}
    sensitivity = {
        jid: binary_metrics_for_judge(rows, qualified_is_erosion=True)
        for jid, rows in per_judge_rows.items()
    }
    eligibility: dict[str, Any] = {}
    eligible: list[tuple[str, float]] = []
    for jid, m in metrics.items():
        ok, reasons = judge_eligible_d38(m)
        eligibility[jid] = {
            "eligible": ok,
            "reasons": reasons,
            "f1_eroded": m["f1_eroded"],
        }
        if ok:
            eligible.append((jid, float(m["f1_eroded"])))
    eligible.sort(key=lambda x: (-x[1], x[0]))

    result: dict[str, Any] = {
        "decision": "D38",
        "metrics": metrics,
        "sensitivity_qualified_as_eroded": sensitivity,
        "eligibility": eligibility,
        "j1": None,
        "j2": None,
        "j3": None,
        "j1_j2_alpha": None,
        "stopped": False,
        "stop_reason": None,
        "tiebreaker_ineligible": False,
    }
    if len(eligible) < 2:
        result["stopped"] = True
        result["stop_reason"] = f"fewer than 2 eligible judges ({len(eligible)})"
        return result

    j1, j2 = eligible[0][0], eligible[1][0]
    by_key: dict[str, dict[str, float | None]] = defaultdict(dict)
    for jid in (j1, j2):
        for row in per_judge_rows[jid]:
            if row.get("structural"):
                continue
            lab = binary_erosion_label(row.get("fate"))
            if lab is None:
                continue
            by_key[_item_key(row)][jid] = 1.0 if lab == BINARY_ERODED else 0.0
    ratings = [[vals.get(j1), vals.get(j2)] for vals in by_key.values()]
    alpha = krippendorff_alpha_ordinal(ratings)
    result["j1"] = j1
    result["j2"] = j2
    result["j1_j2_alpha"] = alpha
    if alpha is None or (isinstance(alpha, float) and (math.isnan(alpha) or alpha < 0.70)):
        result["stopped"] = True
        result["stop_reason"] = f"J1–J2 binary Krippendorff α={alpha} < 0.70"
        return result

    if len(eligible) >= 3:
        result["j3"] = eligible[2][0]
    else:
        inelig = sorted(
            (
                (jid, float(m["f1_eroded"]))
                for jid, m in metrics.items()
                if jid not in {j1, j2}
            ),
            key=lambda x: (-x[1], x[0]),
        )
        if inelig:
            result["j3"] = inelig[0][0]
            result["tiebreaker_ineligible"] = True
    return result
