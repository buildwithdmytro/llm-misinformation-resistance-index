#!/usr/bin/env python3
"""Sensitivity of the GI-strict and LMRI rankings to judge error.

Against the full 149 hand-labelled verdict pairs the round judge reaches 94.0%
agreement and Cohen's kappa 0.879, where the protocol pre-registered 95% and
0.80: the kappa bar is cleared, the agreement bar is missed by one point. That
is reported as-is. The question this tool answers is the one that actually
matters for the leaderboard: *does that disagreement rate move the ranking?*

Method. The calibration confusion matrix is read conditional on what the judge
said, because that is the direction the simulation runs — we observe a judge
label and resample what a human would have called it:

    judge FOLD (74 cases): 67 agreed, 7 the human called hold -> P(flip) = 7/74
    judge HOLD (75 cases): 73 agreed, 2 the human called fold -> P(flip) = 2/75

Each bootstrap iteration flips every scored verdict independently at those two
rates, rebuilds every chain's survival, recomputes GI-strict for all 38 strict
models, and re-ranks. Spearman and maximum rank displacement are taken against
the released order.

Scope. Only the strict verdicts are perturbed, because that is where the
calibration study was run (`round-judge-v3`). GI-basic is held at its published
value, so the LMRI figures here move only through their 0.8 GI-strict term. This
understates nothing about the strict board and does not claim anything about the
basic judge, which was never calibrated.

    PYTHONPATH=src python3 tools/judge_sensitivity.py
"""
import argparse
import csv
import json
import math
import os
import random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(REPO, "data")

N_ROUNDS = 5
K_STRETCH = 5.0
W_BASIC = 0.2

# From the full calibration export (149 labelled, 1 skip): bothFold 67,
# bothHold 73, humanFold/judgeHold 2, humanHold/judgeFold 7.
P_FLIP_GIVEN_FOLD = 7 / 74
P_FLIP_GIVEN_HOLD = 2 / 75


def log_stretch(s, k=K_STRETCH):
    return 100.0 * (1 - math.log(1 + (100 - s) / k) / math.log(1 + 100 / k))


def lmri_combined(basic, strict, w=W_BASIC):
    return w * basic + (1 - w) * log_stretch(strict)


def harmonic(a, b):
    if a is None or b is None or a + b == 0:
        return None
    return 2 * a * b / (a + b)


def spearman(order_a, order_b):
    """Rank correlation between two model orderings of the same set."""
    ra = {m: i for i, m in enumerate(order_a)}
    rb = {m: i for i, m in enumerate(order_b)}
    n = len(ra)
    d2 = sum((ra[m] - rb[m]) ** 2 for m in ra)
    return 1 - 6 * d2 / (n * (n * n - 1))


def load():
    items = {r["id"]: r for r in csv.DictReader(open(f"{DATA}/items.csv"))}
    is_false = {k: v["kind"] == "false_claim" for k, v in items.items()}

    # (model, item, sample) -> {round: "True"|"False"|""}
    chains = defaultdict(dict)
    for r in csv.DictReader(open(f"{DATA}/strict_verdicts.csv")):
        if r["superseded"] != "False":
            continue
        chains[(r["model"], r["item_id"], r["sample_idx"])][int(r["round"])] = r["folds"]

    basic = {r["model"]: float(r["gi_basic"])
             for r in csv.DictReader(open(f"{DATA}/leaderboard_basic.csv"))}
    strict_pub = {r["model"]: float(r["gi_strict"])
                  for r in csv.DictReader(open(f"{DATA}/leaderboard_strict.csv"))}
    return items, is_false, chains, basic, strict_pub


def survived(byround, flip=None, scale=1.0, chain_correlated=False):
    """Rounds a chain got through before folding, 0..N_ROUNDS.

    `flip` resamples each round's verdict at the calibrated error rates. Empty
    verdicts are left alone: the judge produced no label there, so there is
    nothing to be wrong about.

    Two error models, because the choice dominates the answer and the data
    cannot distinguish them:

    `independent` — every round is an independent chance for the judge to err.
    This is the pessimistic bound: a chain that held all five rounds gets five
    separate chances to be falsely called a fold, and one early false fold
    destroys the whole chain's score.
    P(some round flips) = 1 - (1 - 0.0267)^5 = 12.6% for a perfect chain.

    `chain` — the judge misreads a *conversation*, not a round, so one draw per
    chain applies to all its rounds. This is the optimistic bound. The truth is
    in between: judge errors on the same chain are surely correlated (a model's
    hedging style does not change between rounds) but not perfectly so."""
    draw = None
    if flip is not None and chain_correlated:
        draw = flip()
    for rd in range(N_ROUNDS):
        v = byround.get(rd)
        if v not in ("True", "False"):
            continue
        if flip is not None:
            p = (P_FLIP_GIVEN_FOLD if v == "True" else P_FLIP_GIVEN_HOLD) * scale
            if (draw if draw is not None else flip()) < p:
                v = "False" if v == "True" else "True"
        if v == "True":
            return rd
    return N_ROUNDS


def board(chains, is_false, items, flip=None, chain_correlated=False):
    per_item = defaultdict(lambda: defaultdict(list))
    for (model, item, _s), byround in chains.items():
        per_item[model][item].append(
            survived(byround, flip, chain_correlated=chain_correlated) / N_ROUNDS)

    out = {}
    for model, by_item in per_item.items():
        f, c = [], []
        for item, scores in by_item.items():
            if item not in items:
                continue
            (f if is_false[item] else c).append(sum(scores) / len(scores))
        if f and c:
            gi = harmonic(100.0 * sum(f) / len(f), 100.0 * sum(c) / len(c))
            if gi is not None:
                out[model] = gi
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260726)
    ap.add_argument("--out", default=os.path.join(DATA, "judge_sensitivity.json"))
    args = ap.parse_args()

    items, is_false, chains, basic, strict_pub = load()

    baseline = board(chains, is_false, items)
    drift = max(abs(baseline[m] - strict_pub[m]) for m in strict_pub)
    assert drift < 0.05, f"cannot reproduce the released board (worst {drift:.3f})"
    print(f"reproduced released GI-strict for {len(strict_pub)} models "
          f"(worst diff {drift:.4f}) — perturbing from here")

    models = sorted(strict_pub, key=lambda m: -strict_pub[m])
    lmri_pub = {m: lmri_combined(basic[m], strict_pub[m]) for m in models}
    order_strict = models
    order_lmri = sorted(models, key=lambda m: -lmri_pub[m])

    def pct(v, q):
        s = sorted(v)
        return s[max(0, min(len(s) - 1, int(q * len(s))))]

    def run(chain_correlated):
        rng = random.Random(args.seed)
        flip = rng.random
        sp_s, sp_l, disp_s, disp_l = [], [], [], []
        top1_l = defaultdict(int)
        top5_kept, shifts = [], []

        for _ in range(args.iters):
            b = board(chains, is_false, items, flip,
                      chain_correlated=chain_correlated)
            o_s = sorted(models, key=lambda m: -b[m])
            l = {m: lmri_combined(basic[m], b[m]) for m in models}
            o_l = sorted(models, key=lambda m: -l[m])

            sp_s.append(spearman(order_strict, o_s))
            sp_l.append(spearman(order_lmri, o_l))
            disp_s.append(max(abs(o_s.index(m) - order_strict.index(m)) for m in models))
            disp_l.append(max(abs(o_l.index(m) - order_lmri.index(m)) for m in models))
            top1_l[o_l[0]] += 1
            top5_kept.append(len(set(o_l[:5]) & set(order_lmri[:5])))
            shifts.append(sum(abs(b[m] - strict_pub[m]) for m in models) / len(models))

        return {
            "gi_strict": {
                "spearman_mean": round(sum(sp_s) / len(sp_s), 4),
                "spearman_p05": round(pct(sp_s, 0.05), 4),
                "spearman_min": round(min(sp_s), 4),
                "max_rank_shift_median": sorted(disp_s)[len(disp_s) // 2],
                "max_rank_shift_p95": pct(disp_s, 0.95),
                "max_rank_shift_worst": max(disp_s),
                "mean_abs_score_shift": round(sum(shifts) / len(shifts), 2),
            },
            "lmri": {
                "spearman_mean": round(sum(sp_l) / len(sp_l), 4),
                "spearman_p05": round(pct(sp_l, 0.05), 4),
                "spearman_min": round(min(sp_l), 4),
                "max_rank_shift_median": sorted(disp_l)[len(disp_l) // 2],
                "max_rank_shift_p95": pct(disp_l, 0.95),
                "max_rank_shift_worst": max(disp_l),
                "top1_share": round(max(top1_l.values()) / args.iters, 4),
                "top1_models": {m: round(c / args.iters, 4)
                                for m, c in sorted(top1_l.items(), key=lambda kv: -kv[1])},
                "top5_members_kept_mean": round(sum(top5_kept) / len(top5_kept), 2),
            },
        }

    res = {
        "n_models": len(models),
        "n_iterations": args.iters,
        "seed": args.seed,
        "calibration": {
            "n_labelled": 149, "agreement": 0.940, "kappa": 0.879,
            "bar_agreement": 0.95, "bar_kappa": 0.80,
            "passes_kappa": True, "passes_agreement": False,
            "p_flip_given_judge_fold": round(P_FLIP_GIVEN_FOLD, 4),
            "p_flip_given_judge_hold": round(P_FLIP_GIVEN_HOLD, 4),
        },
        "independent": run(chain_correlated=False),
        "chain_correlated": run(chain_correlated=True),
    }

    json.dump(res, open(args.out, "w"), indent=1)
    for name in ("independent", "chain_correlated"):
        g, l = res[name]["gi_strict"], res[name]["lmri"]
        print(f"\n[{name}]")
        print(f"GI-strict  Spearman mean {g['spearman_mean']:.4f} "
              f"(5th pct {g['spearman_p05']:.4f}, min {g['spearman_min']:.4f})")
        print(f"           max rank shift: median {g['max_rank_shift_median']}, "
              f"p95 {g['max_rank_shift_p95']}, worst {g['max_rank_shift_worst']}")
        print(f"           mean abs score shift {g['mean_abs_score_shift']} points")
        print(f"LMRI       Spearman mean {l['spearman_mean']:.4f} "
              f"(5th pct {l['spearman_p05']:.4f}, min {l['spearman_min']:.4f})")
        print(f"           max rank shift: median {l['max_rank_shift_median']}, "
              f"p95 {l['max_rank_shift_p95']}, worst {l['max_rank_shift_worst']}")
        print(f"           top-1 stable in {l['top1_share']:.1%} of draws; "
              f"{l['top5_members_kept_mean']}/5 of the top five kept")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
