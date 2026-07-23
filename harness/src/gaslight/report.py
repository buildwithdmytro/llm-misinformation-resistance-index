"""Summary + leaderboard + charts built from result files (see docs/CONTRACT.md
§report.py).

HARD RULE: this module contains **no numeric result literals** — every number
that ends up rendered comes from the ``summary`` dict produced by
:func:`build_summary`. The only bare numbers here are formatting constants
(figure sizes, DPI, axis limits, font sizes, offsets, the 0-100 scale factor,
list indices) — all named at the top of the module.

Purity note: ``build_summary`` is pure over its inputs (stdlib + numpy via
``stats``); it never reads wall-clock time (``generatedAt`` is left ``None`` — the
CLI stamps it). ``load_results``/``write_summary`` do file I/O. The chart helpers
lazily import matplotlib with the Agg backend so importing this module never
requires matplotlib.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from dataclasses import asdict

from . import score, stats
from .data import load_items
from .types import (
    JudgeResult,
    ModelResponse,
    judge_from_dict,
    response_from_dict,
)

# ─────────────────────────────────────────────────────────────────────────────
# Formatting constants (the ONLY numeric literals allowed in this module)
# ─────────────────────────────────────────────────────────────────────────────
_SCALE = 100.0            # per-item scores live in [0,1]; reported metrics in 0-100
_AXIS_MIN = 0             # metric axis lower bound
_AXIS_MAX = 100           # metric axis upper bound (0-100 scale)
_CI_LO = 0               # index of the low end of a (lo, hi) CI tuple
_CI_HI = 1               # index of the high end of a (lo, hi) CI tuple
_RANK_START = 1           # ranks and stat tiers are 1-based
_HALF = 2.0               # centring divisor for grouped-bar offsets
_JSON_INDENT = 2          # pretty-print indent for result JSON

_FIG_SIZE = (10.0, 6.0)   # inches
_DPI = 150
_BAR_GROUP_WIDTH = 0.8    # total width shared by one x-group's bars
_TITLE_FS = 12
_LABEL_FS = 10
_ANNOT_FS = 8

_BASELINE_PRESSURE = "neutral-continue"  # reference pressure for the delta chart


# ─────────────────────────────────────────────────────────────────────────────
# Summary construction (pure)
# ─────────────────────────────────────────────────────────────────────────────
def _scaled_ci(values, *, seed: int):
    """Bootstrap CI of the mean of ``values`` (in [0,1]), scaled to 0-100.

    Returns a ``(lo, hi)`` tuple, or ``None`` when there is nothing to resample
    (keeps ``NaN`` out of the JSON so it re-loads cleanly)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    lo, hi = stats.bootstrap_ci(vals, seed=seed)
    return (lo * _SCALE, hi * _SCALE)


def _sort_value(x):
    """Sort helper: ``None`` metrics sort to the bottom of a desc ranking."""
    return x if x is not None else float("-inf")


def build_summary(
    items: list,
    judge_results_by_model: dict[str, list[JudgeResult]],
    *,
    seed: int = 0,
) -> dict:
    """Aggregate every model and assemble the JSON-able summary dict.

    Per model: :func:`score.aggregate` -> ``ModelSummary``; bootstrap CIs
    (:func:`stats.bootstrap_ci`) on the resistance / steadfastness / index
    per-item vectors. A leaderboard is sorted by ``index`` descending
    (tie-break: resistance, then steadfastness), ranked, and split into
    statistical tiers (:func:`stats.statistical_tiers`). ``generatedAt`` is left
    ``None`` — the CLI stamps it.

    The index per-item vector is the concatenation of the false-item
    (resistance) and control-item (steadfastness) score vectors — the same
    index-relevant vector :mod:`stats` uses for tiering. Its CI therefore
    describes the mean of that union rather than the harmonic-mean point
    estimate; the two share a 0-100 scale but not a centre (documented risk).
    """
    models: dict[str, dict] = {}
    summaries: dict[str, score.ModelSummary] = {}

    for model, judge_results in judge_results_by_model.items():
        ms = score.aggregate(model, items, judge_results)
        summaries[model] = ms

        res_ci = _scaled_ci(ms.false_item_scores.values(), seed=seed)
        stead_ci = _scaled_ci(ms.control_item_scores.values(), seed=seed)
        index_vec = list(ms.false_item_scores.values()) + list(
            ms.control_item_scores.values()
        )
        index_ci = _scaled_ci(index_vec, seed=seed)

        entry = asdict(ms)
        entry["resistance_ci"] = res_ci
        entry["steadfastness_ci"] = stead_ci
        entry["index_ci"] = index_ci
        models[model] = entry

    # Leaderboard order: index desc, then resistance desc, then steadfastness
    # desc, with model id as a deterministic final tie-break.
    ordered = sorted(
        summaries.values(),
        key=lambda ms: (
            -_sort_value(ms.index),
            -_sort_value(ms.resistance),
            -_sort_value(ms.steadfastness),
            ms.model,
        ),
    )

    tier_entries = [
        {
            "model": ms.model,
            "index": ms.index,
            "false_item_scores": ms.false_item_scores,
            "control_item_scores": ms.control_item_scores,
        }
        for ms in ordered
    ]
    tiers = stats.statistical_tiers(tier_entries)

    leaderboard = []
    for rank, (ms, tier) in enumerate(zip(ordered, tiers), start=_RANK_START):
        m = models[ms.model]
        leaderboard.append(
            {
                "rank": rank,
                "model": ms.model,
                "index": ms.index,
                "index_ci": m["index_ci"],
                "resistance": ms.resistance,
                "resistance_ci": m["resistance_ci"],
                "steadfastness": ms.steadfastness,
                "steadfastness_ci": m["steadfastness_ci"],
                "explicitness": ms.explicitness,
                "flip_rate": ms.flip_rate,
                "stat_tier": tier,
                "n_missing": ms.n_missing,
            }
        )

    return {
        "generatedAt": None,
        "n_items": len(items),
        "models": models,
        "leaderboard": leaderboard,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Result file I/O
# ─────────────────────────────────────────────────────────────────────────────
def _read_jsonl(path: str):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_results(
    results_dir: str,
) -> tuple[list[ModelResponse], dict[str, list[JudgeResult]]]:
    """Load ``results/raw/*.responses.jsonl`` and ``*.judge.jsonl``.

    Returns ``(responses, judge_results_by_model)`` where judge results are keyed
    by their recorded model id. A missing ``raw`` dir yields empty results."""
    raw_dir = os.path.join(results_dir, "raw")

    responses: list[ModelResponse] = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.responses.jsonl"))):
        for row in _read_jsonl(path):
            responses.append(response_from_dict(row))

    judge_by_model: dict[str, list[JudgeResult]] = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.judge.jsonl"))):
        for row in _read_jsonl(path):
            jr = judge_from_dict(row)
            judge_by_model.setdefault(jr.model, []).append(jr)

    return responses, judge_by_model


def write_summary(summary: dict, out_dir: str) -> None:
    """Write ``leaderboard.json`` (ranking view) and ``per_item.json`` (per-model
    detail incl. per-item score vectors) into ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)

    leaderboard_doc = {
        "generatedAt": summary.get("generatedAt"),
        "n_items": summary.get("n_items"),
        "leaderboard": summary.get("leaderboard", []),
    }
    per_item_doc = {
        "generatedAt": summary.get("generatedAt"),
        "n_items": summary.get("n_items"),
        "models": summary.get("models", {}),
    }

    with open(os.path.join(out_dir, "leaderboard.json"), "w", encoding="utf-8") as fh:
        json.dump(leaderboard_doc, fh, indent=_JSON_INDENT, sort_keys=True)
    with open(os.path.join(out_dir, "per_item.json"), "w", encoding="utf-8") as fh:
        json.dump(per_item_doc, fh, indent=_JSON_INDENT, sort_keys=True)


# ─────────────────────────────────────────────────────────────────────────────
# Charts (matplotlib lazy-imported with the Agg backend inside each)
# ─────────────────────────────────────────────────────────────────────────────
def _pyplot():
    """Import matplotlib.pyplot with the non-interactive Agg backend."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _nan():
    return float("nan")


def _num(v):
    """Metric value for plotting: ``None`` -> NaN so the bar is simply absent."""
    return _nan() if v is None else float(v)


def _group_offsets(n, np):
    """Symmetric x-offsets that centre ``n`` bars within one group width."""
    n = max(n, _RANK_START)
    return (np.arange(n) - (n - _RANK_START) / _HALF) * (_BAR_GROUP_WIDTH / n)


def _finish(plt, fig, out_path):
    if out_path is None:
        return fig
    fig.savefig(out_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


def chart_resistance_by_tier(summary: dict, items: list, *, out_path=None):
    """Grouped bars: resistance (0-100) by difficulty tier, one series/model."""
    import numpy as np

    plt = _pyplot()
    models = summary.get("models", {})
    tiers = sorted({it.tier for it in items if it.is_false})
    names = list(models.keys())

    x = np.arange(len(tiers))
    offsets = _group_offsets(len(names), np)
    bar_w = _BAR_GROUP_WIDTH / max(len(names), _RANK_START)

    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    for j, name in enumerate(names):
        by_tier = models[name].get("by_tier") or {}
        heights = [_num(by_tier.get(t)) for t in tiers]
        ax.bar(x + offsets[j], heights, bar_w, label=name)

    ax.set_xticks(x)
    ax.set_xticklabels([str(t) for t in tiers])
    ax.set_ylim(_AXIS_MIN, _AXIS_MAX)
    ax.set_xlabel("Tier", fontsize=_LABEL_FS)
    ax.set_ylabel("Resistance", fontsize=_LABEL_FS)
    ax.set_title("Resistance by tier", fontsize=_TITLE_FS)
    if names:
        ax.legend(fontsize=_ANNOT_FS)
    return _finish(plt, fig, out_path)


def chart_resistance_vs_steadfastness(summary: dict, *, out_path=None):
    """Scatter of resistance vs steadfastness (0-100), labelled per model."""
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=_FIG_SIZE)

    for row in summary.get("leaderboard", []):
        r = row.get("resistance")
        s = row.get("steadfastness")
        if r is None or s is None:
            continue
        ax.scatter(r, s)
        ax.annotate(row.get("model", ""), (r, s), fontsize=_ANNOT_FS)

    ax.set_xlim(_AXIS_MIN, _AXIS_MAX)
    ax.set_ylim(_AXIS_MIN, _AXIS_MAX)
    ax.set_xlabel("Resistance", fontsize=_LABEL_FS)
    ax.set_ylabel("Steadfastness", fontsize=_LABEL_FS)
    ax.set_title("Resistance vs steadfastness", fontsize=_TITLE_FS)
    return _finish(plt, fig, out_path)


def chart_pressure_delta(summary: dict, *, out_path=None):
    """Grouped bars: each pressure's resistance minus the baseline pressure's."""
    import numpy as np

    plt = _pyplot()
    models = summary.get("models", {})
    names = list(models.keys())

    pressures = sorted(
        {
            p
            for m in models.values()
            for p in (m.get("by_pressure") or {})
            if p != _BASELINE_PRESSURE
        }
    )

    x = np.arange(len(pressures))
    offsets = _group_offsets(len(names), np)
    bar_w = _BAR_GROUP_WIDTH / max(len(names), _RANK_START)

    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    for j, name in enumerate(names):
        by_pressure = models[name].get("by_pressure") or {}
        base = by_pressure.get(_BASELINE_PRESSURE)
        heights = []
        for p in pressures:
            v = by_pressure.get(p)
            heights.append(_nan() if (v is None or base is None) else float(v) - base)
        ax.bar(x + offsets[j], heights, bar_w, label=name)

    ax.axhline(_AXIS_MIN)
    ax.set_xticks(x)
    ax.set_xticklabels(pressures)
    ax.set_xlabel("Pressure", fontsize=_LABEL_FS)
    ax.set_ylabel(f"Resistance delta vs {_BASELINE_PRESSURE}", fontsize=_LABEL_FS)
    ax.set_title("Pressure delta", fontsize=_TITLE_FS)
    if names:
        ax.legend(fontsize=_ANNOT_FS)
    return _finish(plt, fig, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None, *, now=None) -> int:
    """CLI: ``python -m gaslight.report --results-dir results --out results/summary``.

    ``now`` (caller-supplied ISO timestamp) stamps ``generatedAt``; absent, it is
    left ``None`` (no wall-clock in the library)."""
    parser = argparse.ArgumentParser(prog="gaslight.report")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--out", default=os.path.join("results", "summary"))
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args(argv)

    items = load_items()
    _responses, judge_by_model = load_results(args.results_dir)
    summary = build_summary(items, judge_by_model)
    summary["generatedAt"] = now

    write_summary(summary, args.out)

    if not args.no_charts:
        try:
            chart_resistance_by_tier(
                summary, items, out_path=os.path.join(args.out, "resistance_by_tier.png")
            )
            chart_resistance_vs_steadfastness(
                summary, out_path=os.path.join(args.out, "resistance_vs_steadfastness.png")
            )
            chart_pressure_delta(
                summary, out_path=os.path.join(args.out, "pressure_delta.png")
            )
        except ImportError:
            pass

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
