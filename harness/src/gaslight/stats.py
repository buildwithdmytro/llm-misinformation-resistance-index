"""Pure statistics for the Gaslighting Index harness.

Bootstrap confidence intervals, paired bootstrap comparison, and statistical
tier grouping. See docs/CONTRACT.md §stats.py.

PURE: stdlib + numpy only. No I/O, no network, no litellm. All randomness flows
through a seeded ``numpy.random.default_rng`` so results are fully deterministic
given the seed.
"""

from __future__ import annotations

import numpy as np

__all__ = ["bootstrap_ci", "paired_bootstrap", "statistical_tiers"]

_NAN = float("nan")


def bootstrap_ci(
    values: list[float],
    *,
    n_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the MEAN of ``values``.

    Resamples the item-level values with replacement (items are the unit of
    generalization) ``n_resamples`` times, takes the mean of each resample, and
    reports the central ``ci`` percentile interval of those means. Deterministic
    given ``seed``. Returns the CI on the same scale as the input mean. Empty
    input -> ``(nan, nan)``.
    """
    arr = np.asarray(list(values), dtype=float)
    n = arr.size
    if n == 0:
        return (_NAN, _NAN)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_resamples, n))
    means = arr[idx].mean(axis=1)

    alpha = 1.0 - ci
    lo = float(np.percentile(means, 100.0 * (alpha / 2.0)))
    hi = float(np.percentile(means, 100.0 * (1.0 - alpha / 2.0)))
    return (lo, hi)


def paired_bootstrap(
    a: dict[str, float],
    b: dict[str, float],
    *,
    n_resamples: int = 10000,
    seed: int = 0,
) -> dict:
    """Paired bootstrap on the per-item score difference ``mean(a) - mean(b)``.

    Works over the *shared* item ids of ``a`` and ``b``: resamples item ids with
    replacement and recomputes ``mean(a) - mean(b)`` each time. Returns::

        {"mean_diff": float, "ci": (lo, hi), "p_two_sided": float,
         "separated": bool}

    ``separated`` is True iff the 95% CI of the difference excludes 0.
    ``p_two_sided`` is a bootstrap achieved-significance level (twice the smaller
    tail mass around 0), clamped to [0, 1]. No shared ids -> nan diff/ci,
    p 1.0, separated False.
    """
    shared = sorted(set(a) & set(b))
    n = len(shared)
    if n == 0:
        return {
            "mean_diff": _NAN,
            "ci": (_NAN, _NAN),
            "p_two_sided": 1.0,
            "separated": False,
        }

    diff = np.array([a[k] - b[k] for k in shared], dtype=float)
    mean_diff = float(diff.mean())

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_resamples, n))
    boot = diff[idx].mean(axis=1)

    lo = float(np.percentile(boot, 2.5))
    hi = float(np.percentile(boot, 97.5))
    separated = (lo > 0.0) or (hi < 0.0)

    # Two-sided bootstrap p: twice the smaller mass on either side of 0.
    p = 2.0 * min(float(np.mean(boot >= 0.0)), float(np.mean(boot <= 0.0)))
    p = float(min(1.0, p))

    return {
        "mean_diff": mean_diff,
        "ci": (lo, hi),
        "p_two_sided": p,
        "separated": separated,
    }


def _index_vector(entry: dict) -> dict[str, float]:
    """The index-relevant per-item score vector for one leaderboard entry.

    Prefers a precomputed ``index_item_scores``; otherwise concatenates
    ``false_item_scores`` (resistance component) and ``control_item_scores``
    (steadfastness component). False/control ids are namespaced so the two never
    collide and two models compare on a shared key space. This concatenation is a
    defensible proxy for overall (index) performance — resistance and
    steadfastness are exactly the two axes the index combines.
    """
    pre = entry.get("index_item_scores")
    if pre is not None:
        return {str(k): float(v) for k, v in dict(pre).items()}

    vec: dict[str, float] = {}
    for k, v in (entry.get("false_item_scores") or {}).items():
        vec[f"false::{k}"] = float(v)
    for k, v in (entry.get("control_item_scores") or {}).items():
        vec[f"control::{k}"] = float(v)
    return vec


def statistical_tiers(entries: list[dict]) -> list[int]:
    """Group leaderboard entries into statistical tiers.

    ``entries`` are leaderboard rows already sorted by ``index`` descending. Each
    carries ``"model"``, ``"index"``, and either a precomputed
    ``"index_item_scores"`` per-item vector or ``"false_item_scores"`` /
    ``"control_item_scores"`` (see :func:`_index_vector`).

    Walks the entries in index-descending order. Tier 1 starts at the top. Each
    subsequent model joins the *current tier's leader's* tier if it is NOT
    separated from that leader (per :func:`paired_bootstrap` on the
    index-relevant per-item vectors); otherwise it starts a new tier and becomes
    that tier's leader. Returns 1-based tier ints aligned to ``entries``.
    """
    if not entries:
        return []

    tiers = [1]
    leader_vec = _index_vector(entries[0])
    current_tier = 1

    for entry in entries[1:]:
        vec = _index_vector(entry)
        res = paired_bootstrap(leader_vec, vec)
        if res["separated"]:
            current_tier += 1
            leader_vec = vec  # this entry leads the new tier
        tiers.append(current_tier)

    return tiers
