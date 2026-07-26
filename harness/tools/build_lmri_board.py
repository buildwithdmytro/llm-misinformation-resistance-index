#!/usr/bin/env python3
"""Build the headline LMRI leaderboard from the frozen GI-basic/GI-strict boards.

LMRI = 0.2 * GI-basic + 0.8 * log_stretch(GI-strict, k=5)  (see gaslight.score).
Defined only for strict qualifiers; regenerate whenever either board changes:

    PYTHONPATH=src python3 tools/build_lmri_board.py

Inputs are auto-detected (working-repo JSON, else the released CSVs); override
with --strict/--basic. Writes JSON, and CSV when --csv is given.
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)
from gaslight.score import lmri_combined, log_stretch  # noqa: E402
from lmri_io import load_boards, pin_map  # noqa: E402

FORMULA = ("lmri = 0.2*gi_basic + 0.8*(100*(1 - ln(1 + (100-gi_strict)/5) "
           "/ ln(1 + 100/5)))")
NOTE = ("Headline combined score. The log-stretch on the GI-strict failure side "
        "separates near-perfect models, whose raw endurance scores are "
        "compressed into a few points. Rank order is nearly invariant to the "
        "parameters (see lmri_sensitivity.json); the stretch changes spacing, "
        "not standing. Defined only for strict qualifiers.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict")
    ap.add_argument("--basic")
    ap.add_argument("--out", default="results/strict-final/lmri_leaderboard.json")
    ap.add_argument("--csv", help="also write this CSV (release/data/leaderboard_lmri.csv)")
    args = ap.parse_args()

    pairs, used = load_boards(args.strict, args.basic)
    rows = [{
        "model": m,
        "gi_basic": round(b, 1),
        "gi_strict": round(s, 1),
        "gi_strict_stretched": round(log_stretch(s), 1),
        "lmri": round(lmri_combined(b, s), 1),
    } for m, b, s in pairs]
    rows.sort(key=lambda r: -r["lmri"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump({"formula": FORMULA, "params": {"k": 5, "w_basic": 0.2},
               "note": NOTE, "leaderboard": rows},
              open(args.out, "w"), indent=1)
    print(f"sources: {os.path.basename(used[0])} + {os.path.basename(used[1])}")
    print(f"wrote {args.out} ({len(rows)} models)")

    if args.csv:
        # the released CSVs identify models by routable pin, not file-stem slug
        pins = pin_map(used[1])
        cols = ["rank", "model", "lmri", "gi_basic", "gi_strict",
                "gi_strict_stretched"]
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                out = {c: r[c] for c in cols}
                out["model"] = pins.get(r["model"], r["model"])
                w.writerow(out)
        print(f"wrote {args.csv}")

    for r in rows[:10]:
        print(f" {r['rank']:>2}. {r['lmri']:5.1f}  (basic {r['gi_basic']}, "
              f"strict {r['gi_strict']} -> {r['gi_strict_stretched']})  {r['model']}")


if __name__ == "__main__":
    main()
