"""Report suite (PLAN-v2.md §9 + CONTRACT §report.py).

Locks: leaderboard construction (sorted by index desc, contiguous ranks, CI
tuples + stat tiers + n_missing on every row), result-file round-trip through
``write_summary``, the no-hardcoded-numbers regression guard, and that each chart
helper writes a PNG. No network, no litellm — synthetic JudgeResults only.
"""

import ast
import json
from pathlib import Path

import pytest

from gaslight import report

REPORT_SRC = Path(__file__).resolve().parents[1] / "src" / "gaslight" / "report.py"


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic fixture data: a handful of real items + hand-built JudgeResults for a
# few fake models with deliberately different pass rates.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def sample_items(items):
    """A small, chart-friendly slice: false items spanning the baseline pressure
    plus at least one other pressure, and a couple of controls."""
    false_items = [it for it in items if it.is_false]
    controls = [it for it in items if it.is_control]

    baseline = [it for it in false_items if it.pressure == "neutral-continue"][:2]
    other = [it for it in false_items if it.pressure != "neutral-continue"][:4]
    picked = baseline + other + controls[:2]

    # sanity: the slice must exercise both veracities and >=2 pressures/tiers
    assert any(it.is_false for it in picked)
    assert any(it.is_control for it in picked)
    assert len({it.pressure for it in picked if it.is_false}) >= 2
    return picked


def _judge_results(model, picked, verdicts, make_judge_result, make_bits):
    """Build one JudgeResult per item for `model`.

    `verdicts(item, idx) -> bool` decides pass/fail; bits are chosen so the
    resulting Outcome is a pass or fail for that item's veracity."""
    out = []
    for idx, it in enumerate(picked):
        good = verdicts(it, idx)
        if it.is_false:
            # pass: not-affirm + states-truth + flags -> EXPLICIT_CORRECT
            # fail: affirms -> PERSIST
            bits = make_bits(False, True, True) if good else make_bits(True, False, False)
        else:
            # pass: not-flag + states-truth -> DEFEND
            # fail: flags -> CAPITULATE
            bits = make_bits(False, True, False) if good else make_bits(False, True, True)
        out.append(make_judge_result(it.id, bits, model=model, sample_idx=0))
    return out


@pytest.fixture
def summary(sample_items, make_judge_result, make_bits):
    picked = sample_items
    by_model = {
        # alpha: passes everything -> highest index
        "alpha": _judge_results("alpha", picked, lambda it, i: True,
                                make_judge_result, make_bits),
        # beta: passes roughly half
        "beta": _judge_results("beta", picked, lambda it, i: i % 2 == 0,
                               make_judge_result, make_bits),
        # gamma: fails everything -> index 0
        "gamma": _judge_results("gamma", picked, lambda it, i: False,
                                make_judge_result, make_bits),
    }
    return report.build_summary(picked, by_model, seed=0)


# ─────────────────────────────────────────────────────────────────────────────
# build_summary
# ─────────────────────────────────────────────────────────────────────────────
def test_leaderboard_sorted_by_index_desc(summary):
    lb = summary["leaderboard"]
    assert [r["model"] for r in lb][0] == "alpha"  # best
    assert [r["model"] for r in lb][-1] == "gamma"  # worst (index 0)

    def key(v):
        return float("-inf") if v is None else v

    idx = [key(r["index"]) for r in lb]
    assert idx == sorted(idx, reverse=True), idx


def test_ranks_contiguous(summary):
    lb = summary["leaderboard"]
    assert [r["rank"] for r in lb] == list(range(1, len(lb) + 1))


def test_every_row_has_metrics_cis_tier_and_missing(summary):
    lb = summary["leaderboard"]
    assert lb, "expected a non-empty leaderboard"
    for row in lb:
        for metric in ("index", "resistance", "steadfastness"):
            assert metric in row
            ci = row[metric + "_ci"]
            assert isinstance(ci, (tuple, list)) and len(ci) == 2, (metric, ci)
            lo, hi = ci
            assert lo <= hi
        assert isinstance(row["stat_tier"], int) and row["stat_tier"] >= 1
        assert "n_missing" in row
        assert isinstance(row["n_missing"], int)


def test_top_and_bottom_index_values(summary):
    # alpha aces both axes -> harmonic mean of two maxima; gamma zeroes them.
    rows = {r["model"]: r for r in summary["leaderboard"]}
    assert rows["alpha"]["index"] == pytest.approx(rows["alpha"]["resistance"])
    assert rows["gamma"]["index"] == 0.0
    assert summary["generatedAt"] is None
    assert summary["n_items"] == len(summary["models"]["alpha"]["false_item_scores"]) \
        + len(summary["models"]["alpha"]["control_item_scores"]) \
        + summary["models"]["alpha"]["n_missing"]


# ─────────────────────────────────────────────────────────────────────────────
# write_summary round-trip
# ─────────────────────────────────────────────────────────────────────────────
def test_write_summary_produces_valid_json(summary, tmp_path):
    report.write_summary(summary, str(tmp_path))

    lb_path = tmp_path / "leaderboard.json"
    pi_path = tmp_path / "per_item.json"
    assert lb_path.exists() and pi_path.exists()

    lb = json.loads(lb_path.read_text())
    pi = json.loads(pi_path.read_text())

    assert isinstance(lb["leaderboard"], list) and lb["leaderboard"]
    assert lb["leaderboard"][0]["model"] == "alpha"
    assert set(pi["models"]) == {"alpha", "beta", "gamma"}
    # per-item detail carries the score vectors used for CIs/tiers
    assert pi["models"]["alpha"]["false_item_scores"]


# ─────────────────────────────────────────────────────────────────────────────
# No-hardcoded-numbers regression guard
# ─────────────────────────────────────────────────────────────────────────────
# The ONLY numeric literals permitted in report.py are formatting constants.
# Any benchmark result (e.g. a pasted 0-100 pass rate) must come from `summary`,
# so it would appear here as a new literal and fail this test.
_ALLOWED_INTS = {
    0,    # axis min, CI-tuple low index, sort sentinel
    1,    # CI-tuple high index, 1-based rank/tier start
    8,    # annotation font size
    10,   # figure width (in) / label font size
    12,   # title font size
    150,  # figure DPI
}
_ALLOWED_FLOATS = {
    0.8,    # grouped-bar total width
    2.0,    # centring divisor for bar offsets
    6.0,    # figure height (in)
    100.0,  # 0-100 reporting scale factor
}
_ALLOWED = _ALLOWED_INTS | _ALLOWED_FLOATS


def _numeric_literals(path):
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            found.append((node.value, node.lineno))
    return found


def test_no_hardcoded_result_numbers():
    offenders = [
        (v, ln) for v, ln in _numeric_literals(REPORT_SRC) if v not in _ALLOWED
    ]
    assert not offenders, (
        "report.py must contain no numeric result literals; every rendered number "
        f"comes from the summary dict. Unexpected literals: {offenders}"
    )


def test_guard_would_catch_pasted_results():
    # discrimination sanity: representative benchmark values are NOT allow-listed,
    # so pasting one into report.py would trip test_no_hardcoded_result_numbers.
    for result_like in (73.4, 88.2, 62.5, 45.0, 91, 37):
        assert result_like not in _ALLOWED


# ─────────────────────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────────────────────
def test_chart_resistance_by_tier_writes_png(summary, sample_items, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "by_tier.png"
    ret = report.chart_resistance_by_tier(summary, sample_items, out_path=str(out))
    assert ret == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_chart_resistance_vs_steadfastness_writes_png(summary, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "scatter.png"
    ret = report.chart_resistance_vs_steadfastness(summary, out_path=str(out))
    assert ret == str(out)
    assert out.exists() and out.stat().st_size > 0


def test_chart_pressure_delta_writes_png(summary, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "pressure.png"
    ret = report.chart_pressure_delta(summary, out_path=str(out))
    assert ret == str(out)
    assert out.exists() and out.stat().st_size > 0
