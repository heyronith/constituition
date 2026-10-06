"""Binary Krippendorff's α with chain-bootstrap CI (prereg §6.7)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence


def _binary_coincidence(pairs: list[tuple[int, int]]) -> tuple[float, float]:
    """Return (observed disagreement Do, expected disagreement De) for binary codes 0/1."""
    if not pairs:
        return 0.0, 0.0
    # Value counts across all ratings
    n0 = sum(1 for a, b in pairs for x in (a, b) if x == 0)
    n1 = sum(1 for a, b in pairs for x in (a, b) if x == 1)
    n = n0 + n1
    if n < 2:
        return 0.0, 0.0
    disagree = sum(1 for a, b in pairs if a != b)
    # Each pair contributes 2 ratings; Do = disagree / n_pairs
    do = disagree / len(pairs)
    # Expected: probability two independent draws differ
    p0, p1 = n0 / n, n1 / n
    de = 2.0 * p0 * p1
    return do, de


def krippendorff_alpha_binary(coder1: Sequence[int], coder2: Sequence[int]) -> float:
    """Nominal α for binary codes {0,1}. Returns 1.0 if no variation / perfect agreement."""
    if len(coder1) != len(coder2):
        raise ValueError("coder vectors must align")
    pairs = [(int(a), int(b)) for a, b in zip(coder1, coder2, strict=True)]
    if not pairs:
        return float("nan")
    do, de = _binary_coincidence(pairs)
    if de == 0.0:
        return 1.0 if do == 0.0 else 0.0
    return 1.0 - (do / de)


@dataclass(frozen=True)
class AlphaBootstrap:
    alpha: float
    ci_low: float
    ci_high: float
    n_items: int
    n_bootstrap: int


def krippendorff_alpha_chain_bootstrap(
    coder1: Sequence[int],
    coder2: Sequence[int],
    chain_ids: Sequence[str | int],
    *,
    n_bootstrap: int = 1000,
    seed: int = 20261004,
    alpha: float = 0.05,
) -> AlphaBootstrap:
    """Point α on all items; percentile CI by resampling chains."""
    if not (len(coder1) == len(coder2) == len(chain_ids)):
        raise ValueError("lengths must match")
    point = krippendorff_alpha_binary(coder1, coder2)
    by_chain: dict[str, list[int]] = {}
    for i, ch in enumerate(chain_ids):
        by_chain.setdefault(str(ch), []).append(i)
    chains = list(by_chain.keys())
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_bootstrap):
        drawn = [rng.choice(chains) for _ in chains]
        idx = [i for ch in drawn for i in by_chain[ch]]
        if len(idx) < 2:
            continue
        c1 = [coder1[i] for i in idx]
        c2 = [coder2[i] for i in idx]
        boots.append(krippendorff_alpha_binary(c1, c2))
    if not boots:
        return AlphaBootstrap(point, float("nan"), float("nan"), len(coder1), n_bootstrap)
    boots.sort()
    lo_i = int(alpha / 2 * len(boots))
    hi_i = min(len(boots) - 1, int((1 - alpha / 2) * len(boots)))
    return AlphaBootstrap(
        alpha=point,
        ci_low=boots[lo_i],
        ci_high=boots[hi_i],
        n_items=len(coder1),
        n_bootstrap=n_bootstrap,
    )
