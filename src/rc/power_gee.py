"""Discrete-time complementary log-log GEE (exchangeable) in pure Python."""

from __future__ import annotations

import math
from typing import Any


def _sigmoid_cloglog(eta: float) -> float:
    # P(y=1) = 1 - exp(-exp(eta))
    # Clamp for stability.
    eta = max(min(eta, 20.0), -20.0)
    return 1.0 - math.exp(-math.exp(eta))


def fit_cloglog_gee(
    rows: list[dict[str, Any]],
    *,
    max_iter: int = 25,
    tol: float = 1e-5,
) -> dict[str, Any]:
    """Fit cloglog with covariates: intercept, cor, self_reflect, cor×self.

    rows need: y (0/1), cor (0/1), self (0/1), chain_id (str).
    Returns coefs and sandwich SE for cor and interaction.
    """
    if not rows:
        return {"coefs": [], "se": [], "converged": False}

    # Design: [1, cor, self, cor*self]
    def x_of(r: dict[str, Any]) -> list[float]:
        cor = float(r["cor"])
        self = float(r["self"])
        return [1.0, cor, self, cor * self]

    xs = [x_of(r) for r in rows]
    ys = [float(r["y"]) for r in rows]
    chains = [str(r["chain_id"]) for r in rows]
    p = 4
    beta = [0.0] * p

    def predict(beta_v: list[float], x: list[float]) -> float:
        return _sigmoid_cloglog(sum(b * xi for b, xi in zip(beta_v, x, strict=True)))

    converged = False
    for _ in range(max_iter):
        # Score and Hessian (independence working correlation for IRLS step).
        score = [0.0] * p
        hess = [[0.0] * p for _ in range(p)]
        for x, y in zip(xs, ys, strict=True):
            mu = predict(beta, x)
            mu = min(max(mu, 1e-9), 1 - 1e-9)
            # dμ/dη = exp(η - exp(η)) = (1-μ) * (-log(1-μ))
            eta = sum(b * xi for b, xi in zip(beta, x, strict=True))
            eta = max(min(eta, 20.0), -20.0)
            dmu = math.exp(eta - math.exp(eta))
            w = (dmu * dmu) / (mu * (1 - mu) + 1e-12)
            resid = y - mu
            for j in range(p):
                score[j] += (dmu / (mu * (1 - mu) + 1e-12)) * resid * x[j]
                for k in range(p):
                    hess[j][k] += w * x[j] * x[k]
        # Solve hess Δ = score
        try:
            delta = _solve(hess, score)
        except ZeroDivisionError:
            break
        beta = [b + d for b, d in zip(beta, delta, strict=True)]
        if max(abs(d) for d in delta) < tol:
            converged = True
            break

    # Sandwich SE with exchangeable-ish clustering by chain (independence bread, meat by chain).
    meat = [[0.0] * p for _ in range(p)]
    by_chain: dict[str, list[int]] = {}
    for i, c in enumerate(chains):
        by_chain.setdefault(c, []).append(i)
    bread = [[0.0] * p for _ in range(p)]
    for x, y in zip(xs, ys, strict=True):
        mu = predict(beta, x)
        mu = min(max(mu, 1e-9), 1 - 1e-9)
        eta = sum(b * xi for b, xi in zip(beta, x, strict=True))
        eta = max(min(eta, 20.0), -20.0)
        dmu = math.exp(eta - math.exp(eta))
        w = (dmu * dmu) / (mu * (1 - mu) + 1e-12)
        for j in range(p):
            for k in range(p):
                bread[j][k] += w * x[j] * x[k]
    for idxs in by_chain.values():
        score_c = [0.0] * p
        for i in idxs:
            x, y = xs[i], ys[i]
            mu = predict(beta, x)
            mu = min(max(mu, 1e-9), 1 - 1e-9)
            eta = sum(b * xi for b, xi in zip(beta, x, strict=True))
            eta = max(min(eta, 20.0), -20.0)
            dmu = math.exp(eta - math.exp(eta))
            resid = y - mu
            for j in range(p):
                score_c[j] += (dmu / (mu * (1 - mu) + 1e-12)) * resid * x[j]
        for j in range(p):
            for k in range(p):
                meat[j][k] += score_c[j] * score_c[k]
    try:
        bread_inv = _invert(bread)
        # V = B^{-1} M B^{-1}
        tmp = _matmul(bread_inv, meat)
        cov = _matmul(tmp, bread_inv)
        se = [math.sqrt(max(cov[i][i], 0.0)) for i in range(p)]
    except ZeroDivisionError:
        se = [float("nan")] * p
        cov = None

    return {
        "coefs": beta,
        "se": se,
        "converged": converged,
        "names": ["intercept", "cor", "self", "cor_x_self"],
    }


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ZeroDivisionError("singular")
        m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            for j in range(col, n + 1):
                m[r][j] -= factor * m[col][j]
    return [m[i][n] for i in range(n)]


def _invert(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    aug = [a[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ZeroDivisionError("singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            for j in range(2 * n):
                aug[r][j] -= factor * aug[col][j]
    return [row[n:] for row in aug]


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    n = len(a)
    m = len(b[0])
    k = len(b)
    out = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            out[i][j] = sum(a[i][t] * b[t][j] for t in range(k))
    return out


def one_sided_z_test(coef: float, se: float) -> float:
    """Return one-sided p-value for H1: coef > 0."""
    if se <= 0 or math.isnan(se):
        return 1.0
    z = coef / se
    # 1 - Φ(z) approx
    return 0.5 * math.erfc(z / math.sqrt(2.0))
