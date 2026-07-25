#!/usr/bin/env python3
"""Sensitivity of the LMRI ranking to its two free parameters (k, w_basic).

The stretch constant k and the basic weight w_basic are chosen, not derived, so
the published ranking must be shown to be robust to them. This computes, for a
grid of (k, w_basic), the Spearman rank correlation and the maximum rank
displacement against the released parameters (k=5, w_basic=0.2).

    PYTHONPATH=src python3 tools/lmri_sensitivity.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)
from gaslight.score import lmri_combined  # noqa: E402
from lmri_io import load_boards  # noqa: E402

OUT = "results/strict-final/lmri_sensitivity.json"

KS = [1, 2, 5, 10, 25, 100]
WS = [0.0, 0.1, 0.2, 0.3, 0.5]
K_REF, W_REF = 5.0, 0.2


def ranking(pairs, k, w):
    """Model slugs ordered best-first under (k, w)."""
    scored = [(m, lmri_combined(b, s, k=k, w_basic=w)) for m, b, s in pairs]
    scored.sort(key=lambda x: -x[1])
    return [m for m, _ in scored]


def spearman(rank_a, rank_b):
    """Rank correlation between two orderings of the same items (no ties)."""
    pos_a = {m: i for i, m in enumerate(rank_a)}
    pos_b = {m: i for i, m in enumerate(rank_b)}
    n = len(rank_a)
    d2 = sum((pos_a[m] - pos_b[m]) ** 2 for m in rank_a)
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def max_displacement(rank_a, rank_b):
    pos_b = {m: i for i, m in enumerate(rank_b)}
    return max(abs(i - pos_b[m]) for i, m in enumerate(rank_a))


def main() -> None:
    pairs, _used = load_boards()

    ref = ranking(pairs, K_REF, W_REF)
    grid = []
    for k in KS:
        for w in WS:
            r = ranking(pairs, k, w)
            grid.append({
                "k": k, "w_basic": w,
                "spearman_vs_released": round(spearman(ref, r), 4),
                "max_rank_shift": max_displacement(ref, r),
                "top1": r[0], "top3": r[:3],
            })

    # k-only sweep at the released weight, and w-only sweep at the released k
    k_only = [g for g in grid if g["w_basic"] == W_REF]
    w_only = [g for g in grid if g["k"] == K_REF]

    summary = {
        "n_models": len(pairs),
        "released_params": {"k": K_REF, "w_basic": W_REF},
        "min_spearman_over_grid": round(min(g["spearman_vs_released"] for g in grid), 4),
        "max_rank_shift_over_grid": max(g["max_rank_shift"] for g in grid),
        "min_spearman_k_sweep": round(min(g["spearman_vs_released"] for g in k_only), 4),
        "max_rank_shift_k_sweep": max(g["max_rank_shift"] for g in k_only),
        "top1_always_same": len({g["top1"] for g in grid}) == 1,
        "top1_set": sorted({g["top1"] for g in grid}),
        "grid": grid,
    }
    json.dump(summary, open(OUT, "w"), indent=1)

    print(f"models: {summary['n_models']}   released: k={K_REF}, w_basic={W_REF}")
    print(f"\nk sweep at w_basic={W_REF}:")
    for g in k_only:
        print(f"  k={g['k']:>3}  spearman={g['spearman_vs_released']:.4f}  "
              f"max_shift={g['max_rank_shift']}  top1={g['top1'].split('_')[-1]}")
    print(f"\nw_basic sweep at k={K_REF}:")
    for g in w_only:
        print(f"  w={g['w_basic']:.1f}  spearman={g['spearman_vs_released']:.4f}  "
              f"max_shift={g['max_rank_shift']}  top1={g['top1'].split('_')[-1]}")
    print(f"\nfull {len(KS)}x{len(WS)} grid: min spearman "
          f"{summary['min_spearman_over_grid']}, max rank shift "
          f"{summary['max_rank_shift_over_grid']}, "
          f"top-1 stable={summary['top1_always_same']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
