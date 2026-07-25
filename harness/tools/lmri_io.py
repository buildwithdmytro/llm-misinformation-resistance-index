"""Shared board loader for the LMRI tools.

Reads the GI-basic and GI-strict boards from either the working-repo JSON
(`results/…`) or the released CSVs (`release/data/leaderboard_*.csv`), so the
headline score is recomputable from the public release alone.
"""
from __future__ import annotations

import csv
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (strict, basic) candidate pairs, first existing pair wins
CANDIDATES = [
    (os.path.join(REPO, "results/strict-final/strict_leaderboard_FINAL.json"),
     os.path.join(REPO, "results/final/summary/leaderboard.json")),
    (os.path.join(REPO, "release/data/leaderboard_strict.csv"),
     os.path.join(REPO, "release/data/leaderboard_basic.csv")),
    (os.path.join(REPO, "data/leaderboard_strict.csv"),
     os.path.join(REPO, "data/leaderboard_basic.csv")),
    # shipped layout: release/harness/tools/ -> release/data/
    (os.path.join(REPO, "..", "data", "leaderboard_strict.csv"),
     os.path.join(REPO, "..", "data", "leaderboard_basic.csv")),
]


def _slug(model: str) -> str:
    return model.replace("/", "_")


def _read_strict(path: str) -> dict[str, float]:
    if path.endswith(".json"):
        rows = json.load(open(path))
        return {_slug(r["model"]): float(r["gi_strict"]) for r in rows}
    with open(path, newline="", encoding="utf-8") as fh:
        return {_slug(r["model"]): float(r["gi_strict"])
                for r in csv.DictReader(fh) if r.get("gi_strict")}


def _read_basic(path: str) -> dict[str, float]:
    if path.endswith(".json"):
        rows = json.load(open(path))["leaderboard"]
        return {_slug(r["model"]): float(r["index"]) for r in rows}
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    # the released CSV renames `index` -> `gi_basic`
    key = "gi_basic" if rows and "gi_basic" in rows[0] else "index"
    return {_slug(r["model"]): float(r[key]) for r in rows if r.get(key)}


def pin_map(basic_path: str) -> dict[str, str]:
    """slug -> the routable model pin used by the released CSVs."""
    if basic_path.endswith(".json"):
        ids = [r["model"] for r in json.load(open(basic_path))["leaderboard"]]
    else:
        with open(basic_path, newline="", encoding="utf-8") as fh:
            ids = [r["model"] for r in csv.DictReader(fh)]
    return {_slug(i): i for i in ids}


def load_boards(strict_path: str | None = None, basic_path: str | None = None):
    """Return ``[(slug, gi_basic, gi_strict), …]`` for every strict qualifier."""
    if strict_path and basic_path:
        pair = (strict_path, basic_path)
    else:
        pair = next((p for p in CANDIDATES
                     if os.path.exists(p[0]) and os.path.exists(p[1])), None)
        if pair is None:
            raise SystemExit(
                "no board pair found; pass --strict and --basic explicitly "
                f"(looked in: {[p[0] for p in CANDIDATES]})")
    strict, basic = _read_strict(pair[0]), _read_basic(pair[1])
    missing = sorted(set(strict) - set(basic))
    if missing:
        raise SystemExit(f"strict models absent from the basic board: {missing}")
    return [(m, basic[m], strict[m]) for m in strict], pair
