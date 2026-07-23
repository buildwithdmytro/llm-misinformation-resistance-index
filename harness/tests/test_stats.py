"""Tests for gaslight.stats (pure bootstrap / paired comparison / tiers).

Covers PLAN-v2 §9 for test_stats: bootstrap CI against known cases, paired
comparison sanity (A==B -> no separation; large gap -> separation), and
determinism under a seeded RNG.
"""

import math

from gaslight import stats


# ─────────────────────────────────────────────────────────────────────────────
# bootstrap_ci
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_ci_deterministic_same_seed():
    values = [0.0, 1.0, 0.5, 0.25, 0.75, 1.0, 0.0, 0.9]
    a = stats.bootstrap_ci(values, seed=7)
    b = stats.bootstrap_ci(values, seed=7)
    assert a == b  # same seed -> byte-identical CI


def test_bootstrap_ci_different_seed_still_valid():
    values = [0.0, 1.0, 0.5, 0.25, 0.75, 1.0, 0.0, 0.9]
    mean = sum(values) / len(values)
    lo1, hi1 = stats.bootstrap_ci(values, seed=1)
    lo2, hi2 = stats.bootstrap_ci(values, seed=2)
    for lo, hi in ((lo1, hi1), (lo2, hi2)):
        assert math.isfinite(lo) and math.isfinite(hi)
        assert lo <= hi
        # a percentile CI of the mean must bracket the sample mean
        assert lo <= mean <= hi


def test_bootstrap_ci_empty_is_nan():
    lo, hi = stats.bootstrap_ci([])
    assert math.isnan(lo) and math.isnan(hi)


def test_bootstrap_ci_all_equal_is_degenerate():
    lo, hi = stats.bootstrap_ci([0.42, 0.42, 0.42, 0.42], seed=3)
    assert lo == 0.42 == hi  # every resample mean is exactly the value


def test_bootstrap_ci_single_value():
    lo, hi = stats.bootstrap_ci([0.7], seed=0)
    assert lo == 0.7 == hi


def test_bootstrap_ci_brackets_mean():
    values = [0.2, 0.4, 0.6, 0.8, 1.0, 0.0, 0.5, 0.5, 0.3, 0.9]
    mean = sum(values) / len(values)
    lo, hi = stats.bootstrap_ci(values, seed=0)
    assert lo <= mean <= hi


def test_bootstrap_ci_narrows_as_n_grows():
    # Same underlying distribution (mean 0.5), 10 items vs 1000 items.
    small = [0.0, 1.0] * 5
    large = [0.0, 1.0] * 500
    lo_s, hi_s = stats.bootstrap_ci(small, seed=0)
    lo_l, hi_l = stats.bootstrap_ci(large, seed=0)
    width_small = hi_s - lo_s
    width_large = hi_l - lo_l
    assert width_large < width_small
    # both still bracket the common mean of 0.5
    assert lo_s <= 0.5 <= hi_s
    assert lo_l <= 0.5 <= hi_l


# ─────────────────────────────────────────────────────────────────────────────
# paired_bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def test_paired_bootstrap_identical_not_separated():
    ids = {f"i{n}": (n % 3) / 2.0 for n in range(30)}
    res = stats.paired_bootstrap(dict(ids), dict(ids), seed=0)
    assert res["mean_diff"] == 0.0
    assert res["separated"] is False
    lo, hi = res["ci"]
    assert lo == 0.0 == hi
    # identical -> maximally non-significant
    assert res["p_two_sided"] == 1.0


def test_paired_bootstrap_large_gap_separated():
    ids = [f"i{n}" for n in range(40)]
    a = {k: 1.0 for k in ids}
    b = {k: 0.0 for k in ids}
    res = stats.paired_bootstrap(a, b, seed=0)
    assert res["mean_diff"] == 1.0
    assert res["separated"] is True
    lo, hi = res["ci"]
    assert lo > 0.0  # CI of the difference excludes 0
    assert res["p_two_sided"] < 0.01  # small


def test_paired_bootstrap_uses_shared_ids_only():
    a = {"x": 1.0, "y": 1.0, "z": 1.0, "only_a": 0.0}
    b = {"x": 0.0, "y": 0.0, "z": 0.0, "only_b": 1.0}
    res = stats.paired_bootstrap(a, b, seed=0)
    # only x, y, z are shared; each diff is +1.0
    assert res["mean_diff"] == 1.0
    assert res["separated"] is True


def test_paired_bootstrap_no_shared_ids():
    res = stats.paired_bootstrap({"a": 1.0}, {"b": 0.0}, seed=0)
    assert math.isnan(res["mean_diff"])
    assert res["separated"] is False


def test_paired_bootstrap_deterministic():
    a = {f"i{n}": (n % 5) / 4.0 for n in range(25)}
    b = {f"i{n}": ((n + 1) % 5) / 4.0 for n in range(25)}
    r1 = stats.paired_bootstrap(a, b, seed=11)
    r2 = stats.paired_bootstrap(a, b, seed=11)
    assert r1 == r2


# ─────────────────────────────────────────────────────────────────────────────
# statistical_tiers
# ─────────────────────────────────────────────────────────────────────────────
def _alt_perturb(base: dict, amp: float, phase: int) -> dict:
    """Balanced (mean-zero over an even count) alternating perturbation.

    Keeps two models 'near-identical' without introducing a one-sided bias that
    would spuriously separate them.
    """
    out = {}
    for i, k in enumerate(sorted(base)):
        sign = 1.0 if (i + phase) % 2 == 0 else -1.0
        out[k] = base[k] + sign * amp
    return out


def _make_entry(model, index, false_scores, control_scores):
    return {
        "model": model,
        "index": index,
        "false_item_scores": false_scores,
        "control_item_scores": control_scores,
    }


def test_statistical_tiers_two_separated_clusters():
    # 40 false + 20 control items (even counts -> balanced perturbation).
    false_ids = [f"f{n}" for n in range(40)]
    control_ids = [f"c{n}" for n in range(20)]

    high_false = {k: 0.95 for k in false_ids}
    high_control = {k: 0.90 for k in control_ids}
    low_false = {k: 0.40 for k in false_ids}
    low_control = {k: 0.35 for k in control_ids}

    # three near-identical high models, three near-identical low models
    entries = [
        _make_entry("hi-A", 92.5, dict(high_false), dict(high_control)),
        _make_entry("hi-B", 92.4,
                    _alt_perturb(high_false, 0.03, 0),
                    _alt_perturb(high_control, 0.03, 0)),
        _make_entry("hi-C", 92.3,
                    _alt_perturb(high_false, 0.02, 1),
                    _alt_perturb(high_control, 0.02, 1)),
        _make_entry("lo-A", 38.0, dict(low_false), dict(low_control)),
        _make_entry("lo-B", 37.9,
                    _alt_perturb(low_false, 0.03, 0),
                    _alt_perturb(low_control, 0.03, 0)),
        _make_entry("lo-C", 37.8,
                    _alt_perturb(low_false, 0.02, 1),
                    _alt_perturb(low_control, 0.02, 1)),
    ]

    tiers = stats.statistical_tiers(entries)

    assert len(tiers) == len(entries)
    high_tiers = tiers[:3]
    low_tiers = tiers[3:]
    # near-identical models share a tier
    assert len(set(high_tiers)) == 1
    assert len(set(low_tiers)) == 1
    # the low cluster gets a strictly higher tier number
    assert low_tiers[0] > high_tiers[0]
    # tiers are 1-based starting at 1
    assert high_tiers[0] == 1


def test_statistical_tiers_empty():
    assert stats.statistical_tiers([]) == []


def test_statistical_tiers_single_entry():
    entry = _make_entry("solo", 50.0, {"f0": 0.5, "f1": 0.5}, {"c0": 0.5})
    assert stats.statistical_tiers([entry]) == [1]


def test_statistical_tiers_precomputed_vector_path():
    # exercise the index_item_scores branch of _index_vector
    ids = [f"i{n}" for n in range(30)]
    top = {"model": "top", "index": 90.0,
           "index_item_scores": {k: 0.9 for k in ids}}
    mid = {"model": "mid", "index": 90.0,
           "index_item_scores": {k: 0.9 for k in ids}}  # identical -> same tier
    bot = {"model": "bot", "index": 30.0,
           "index_item_scores": {k: 0.3 for k in ids}}  # separated -> new tier

    tiers = stats.statistical_tiers([top, mid, bot])
    assert tiers[0] == tiers[1] == 1
    assert tiers[2] > 1
