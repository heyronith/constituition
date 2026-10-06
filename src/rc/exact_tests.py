"""Exact conditional tests for confirmatory H1 fallback (prereg §6.6)."""

from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import binomtest


@dataclass(frozen=True)
class ExactConditionalH1:
    n_cor_events: int
    n_total_events: int
    cor_at_risk_share: float
    p_value_one_sided: float
    estimate: float
    method: str = "exact_conditional_binomial"


def exact_conditional_h1(
    n_cor_events: int,
    n_total_events: int,
    cor_at_risk_share: float,
) -> ExactConditionalH1:
    """COR events ~ Binomial(total events, p = COR at-risk share), one-sided > share.

    Used as primary H1 inference when fewer than 20 COR+AGENT events occur.
    """
    if n_total_events < 0 or n_cor_events < 0 or n_cor_events > n_total_events:
        raise ValueError("invalid event counts")
    if not 0.0 <= cor_at_risk_share <= 1.0:
        raise ValueError("cor_at_risk_share must be in [0, 1]")
    if n_total_events == 0:
        return ExactConditionalH1(
            n_cor_events=0,
            n_total_events=0,
            cor_at_risk_share=cor_at_risk_share,
            p_value_one_sided=1.0,
            estimate=float("nan"),
        )
    result = binomtest(
        n_cor_events,
        n_total_events,
        p=cor_at_risk_share,
        alternative="greater",
    )
    return ExactConditionalH1(
        n_cor_events=n_cor_events,
        n_total_events=n_total_events,
        cor_at_risk_share=cor_at_risk_share,
        p_value_one_sided=float(result.pvalue),
        estimate=n_cor_events / n_total_events,
    )


def tost_log_hr(
    log_hr: float,
    se: float,
    *,
    lower_hr: float = 0.80,
    upper_hr: float = 1.25,
    alpha: float = 0.05,
) -> dict[str, float | str | bool]:
    """TOST for HR in [lower_hr, upper_hr] on the log scale (prereg §6.5)."""
    import math

    from scipy.stats import norm

    if se <= 0 or not math.isfinite(log_hr) or not math.isfinite(se):
        return {
            "equivalent": False,
            "label": "inconclusive",
            "p_lower": 1.0,
            "p_upper": 1.0,
            "p_tost": 1.0,
        }
    lo = math.log(lower_hr)
    hi = math.log(upper_hr)
    # H0: log_hr <= lo  vs  H1: log_hr > lo
    z_lo = (log_hr - lo) / se
    p_lo = 1.0 - norm.cdf(z_lo)
    # H0: log_hr >= hi  vs  H1: log_hr < hi
    z_hi = (hi - log_hr) / se
    p_hi = 1.0 - norm.cdf(z_hi)
    p_tost = max(p_lo, p_hi)
    equivalent = p_tost < alpha
    # Directional evidence for H-alt: HR significantly < 1
    z_halt = (0.0 - log_hr) / se  # one-sided HR < 1 ↔ log_hr < 0
    p_halt = 1.0 - norm.cdf(z_halt)
    if equivalent:
        label = "selective erosion absent at the scale we can detect"
    elif p_halt < alpha:
        label = "evidence for H-alt"
    else:
        label = "inconclusive"
    return {
        "equivalent": equivalent,
        "label": label,
        "p_lower": float(p_lo),
        "p_upper": float(p_hi),
        "p_tost": float(p_tost),
        "p_halt_lt_1": float(p_halt),
    }


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values (same order as input)."""
    n = len(p_values)
    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    prev = 0.0
    for rank, idx in enumerate(order):
        factor = n - rank
        adj = min(1.0, p_values[idx] * factor)
        adj = max(adj, prev)
        adjusted[idx] = adj
        prev = adj
    return adjusted
