"""Small exact tail probabilities: is a player's count clearly above (or below) the squad's?

A rule never judges a bare share. It asks how likely the player's count would be if they
went down (or were far, or alone...) at the squad's rate in the same fights; only a count that
is both well above that rate and unlikely by chance fires.
"""

from __future__ import annotations

import math

# Every term is computed as a logarithm (factorials via lgamma) and the tail is summed on that
# scale: plain floats overflow (math.comb of 1,000+ downs) or underflow (exp(-mu) above ~745)
# on long profiles, which made a rule crash or never fire.


def _logsumexp(logs: list[float]) -> float:
    if not logs:
        return -math.inf
    top = max(logs)
    if top == -math.inf:
        return top
    return top + math.log(sum(math.exp(x - top) for x in logs))


def _poisson_log_pmf(i: int, mu: float) -> float:
    return i * math.log(mu) - mu - math.lgamma(i + 1)


def poisson_sf(k: int, mu: float) -> float:
    """P(X >= k) for X ~ Poisson(mu)."""
    if k <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    if k <= mu:  # the tail is the big side: one minus the (small) head
        return max(0.0, 1.0 - poisson_cdf(k - 1, mu))
    logs: list[float] = []
    i = k
    while True:  # terms only shrink from here (i > mu); stop once they no longer count
        logs.append(_poisson_log_pmf(i, mu))
        if logs[-1] < logs[0] - 50:
            break
        i += 1
    return min(1.0, math.exp(_logsumexp(logs)))


def poisson_cdf(k: int, mu: float) -> float:
    """P(X <= k) for X ~ Poisson(mu)."""
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0
    if k > mu:  # the head is the big side
        return max(0.0, 1.0 - poisson_sf(k + 1, mu))
    return min(1.0, math.exp(_logsumexp([_poisson_log_pmf(i, mu) for i in range(k + 1)])))


def _binom_log_pmf(i: int, n: int, p: float) -> float:
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n or p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return min(1.0, math.exp(_logsumexp([_binom_log_pmf(i, n, p) for i in range(k, n + 1)])))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return 1.0 - binom_sf(k + 1, n, p)


def poisson_binomial_sf(k: int, probs: list[float]) -> float:
    """P(X >= k) where X is the number of successes of independent trials with `probs`."""
    if k <= 0:
        return 1.0
    dist = [1.0]
    for p in probs:
        p = min(max(p, 0.0), 1.0)
        nxt = [0.0] * (len(dist) + 1)
        for i, v in enumerate(dist):
            nxt[i] += v * (1 - p)
            nxt[i + 1] += v * p
        dist = nxt
    return min(1.0, sum(dist[k:]))
