#!/usr/bin/env python3
"""Export the LMRI release CSVs for the Hugging Face dataset.

Reads only from the parent repo; writes only into release/data/.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys

PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PARENT, "src"))

import yaml  # noqa: E402

# Expected model counts come from the boards themselves, never hardcoded, so
# adding a model does not require editing this exporter.
N_BASIC = len(json.load(open(os.path.join(
    PARENT, "results/final/summary/leaderboard.json")))["leaderboard"])
N_STRICT = len(json.load(open(os.path.join(
    PARENT, "results/strict-final/strict_leaderboard_FINAL.json"))))

from gaslight.data import load_items  # noqa: E402
from gaslight.score import classify  # noqa: E402
from gaslight.types import JudgeBits  # noqa: E402

OUT = os.path.join(PARENT, "release", "data")
os.makedirs(OUT, exist_ok=True)

DOMAIN_NAMES = {
    "hist": "history/geography",
    "med": "medicine/health",
    "sci": "science/math",
    "stat": "statistics/data",
    "sw": "software/security",
}

BASIC_RAW = os.path.join(PARENT, "results", "final", "raw")
STRICT_RAW = os.path.join(PARENT, "results", "strict-final", "raw")

validation: dict[str, object] = {}


def b(v):
    """Bool -> 'True'/'False'; None -> ''."""
    if v is None:
        return ""
    return bool(v)


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {path}: {len(rows)} rows")


# ── 1. items.csv ─────────────────────────────────────────────────────────────
with open(os.path.join(PARENT, "configs", "strict_subset.yaml"), encoding="utf-8") as fh:
    strict_ids = set(yaml.safe_load(fh)["items"])
assert len(strict_ids) == 48, f"strict subset has {len(strict_ids)} ids, expected 48"

items = load_items()
by_id = {it.id: it for it in items}
rows = []
n_false = n_control = 0
sub_false = sub_control = 0
for it in items:
    code = it.id.split("-")[0]
    kind = "false_claim" if it.is_false else "control"
    if it.is_false:
        n_false += 1
    else:
        n_control += 1
    in_sub = it.id in strict_ids
    if in_sub:
        if it.is_false:
            sub_false += 1
        else:
            sub_control += 1
    rows.append([
        it.id,
        code,
        DOMAIN_NAMES[code],
        it.tier,
        kind,
        it.claim,
        it.ground_truth,
        json.dumps(it.messages(), ensure_ascii=False),
        b(in_sub),
    ])
write_csv(
    "items.csv",
    ["id", "domain", "domain_name", "tier", "kind", "claim", "ground_truth", "messages", "in_strict_subset"],
    rows,
)
validation["items"] = {
    "total": len(rows), "false": n_false, "control": n_control,
    "in_strict_subset": sub_false + sub_control,
    "subset_false": sub_false, "subset_control": sub_control,
}

# ── model-id normalization map (file stem <-> slashed model id) ─────────────
stem_to_model: dict[str, str] = {}
for f in sorted(glob.glob(os.path.join(STRICT_RAW, "*.escalation.jsonl"))):
    stem = os.path.basename(f)[: -len(".escalation.jsonl")]
    with open(f, encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    stem_to_model[stem] = first["model"]

# ── 2. basic_responses.csv ───────────────────────────────────────────────────
resp_files = sorted(glob.glob(os.path.join(BASIC_RAW, "*.responses.jsonl")))
assert len(resp_files) == N_BASIC, f"{len(resp_files)} responses files, expected {N_BASIC}"
rows = []
n_err = 0
for f in resp_files:
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("error"):
                n_err += 1
            rows.append([
                d["model"], d["item_id"], d["sample_idx"], d["output_text"],
                d.get("thinking_text", ""),  # not recorded in the basic run; kept for schema parity
                d.get("latency_ms", ""), d.get("prompt_tokens", 0),
                d.get("completion_tokens", 0), d.get("error") or "",
            ])
write_csv(
    "basic_responses.csv",
    ["model", "item_id", "sample_idx", "output_text", "thinking_text",
     "latency_ms", "prompt_tokens", "completion_tokens", "error"],
    rows,
)
validation["basic_responses"] = {"total": len(rows), "non_error": len(rows) - n_err, "error": n_err}

# ── 3. basic_verdicts.csv ────────────────────────────────────────────────────
# 46th judge file (grok-4.5) belongs to a region-blocked, non-leaderboard run — excluded.
judge_files = sorted(
    f for f in glob.glob(os.path.join(BASIC_RAW, "*.judge.jsonl"))
    if "x-ai_grok" not in os.path.basename(f)
)
assert len(judge_files) == N_BASIC, f"{len(judge_files)} judge files, expected {N_BASIC}"
rows = []
n_no_bits = 0
for f in judge_files:
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            bits_d = d.get("bits")
            if bits_d is None:
                n_no_bits += 1
                rows.append([d["model"], d["item_id"], "", "", "", "",
                             d.get("judge_model", ""), "v2"])
                continue
            bits = JudgeBits(
                affirms_target=bool(bits_d["affirms_target"]),
                states_truth=bool(bits_d["states_truth"]),
                flags_reversal=bool(bits_d["flags_reversal"]),
            )
            outcome = classify(by_id[d["item_id"]], bits).value
            rows.append([
                d["model"], d["item_id"],
                b(bits.affirms_target), b(bits.states_truth), b(bits.flags_reversal),
                outcome, d.get("judge_model", ""), "v2",
            ])
write_csv(
    "basic_verdicts.csv",
    ["model", "item_id", "affirms_target", "states_truth", "flags_reversal",
     "outcome", "judge_model", "judge_prompt_version"],
    rows,
)
validation["basic_verdicts"] = {"total": len(rows), "missing_bits": n_no_bits}

# ── 4. strict_transcripts.csv ────────────────────────────────────────────────
esc_files = sorted(glob.glob(os.path.join(STRICT_RAW, "*.escalation.jsonl")))
assert len(esc_files) == N_STRICT, f"{len(esc_files)} escalation files, expected {N_STRICT}"
rows = []
n_think = 0
for f in esc_files:
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("thinking_text"):
                n_think += 1
            rows.append([
                d["model"], d["item_id"], d["sample_idx"], d["round"],
                d["output_text"], d.get("thinking_text", ""),
                d.get("latency_ms", ""), d.get("prompt_tokens", 0),
                d.get("completion_tokens", 0),
            ])
write_csv(
    "strict_transcripts.csv",
    ["model", "item_id", "sample_idx", "round", "output_text", "thinking_text",
     "latency_ms", "prompt_tokens", "completion_tokens"],
    rows,
)
validation["strict_transcripts"] = {"total": len(rows), "nonempty_thinking": n_think}

# ── 5. strict_verdicts.csv ───────────────────────────────────────────────────
vfiles = sorted(glob.glob(os.path.join(STRICT_RAW, "*.escalation.judge.jsonl")))
assert len(vfiles) == N_STRICT, f"{len(vfiles)} escalation judge files, expected {N_STRICT}"
raw_rows = []  # (key, parsed row without superseded)
for f in vfiles:
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            key = (d["model"], d["item_id"], d["sample_idx"], d["round"])
            bits_d = d.get("bits")
            raw_rows.append((key, [
                d["model"], d["item_id"], d["sample_idx"], d["round"],
                b(d.get("folds")),
                b(bits_d["affirms_target"]) if bits_d else "",
                b(bits_d["states_truth"]) if bits_d else "",
                b(bits_d["flags_reversal"]) if bits_d else "",
                d.get("judge_model", ""), d.get("judge_prompt_version", ""),
                d.get("reasoning") or "", b(bool(d.get("empty_reply"))),
            ]))
# last occurrence of each key wins (superseded=False); earlier ones True
last_index: dict[tuple, int] = {}
for i, (key, _) in enumerate(raw_rows):
    last_index[key] = i
rows = []
n_superseded = 0
for i, (key, r) in enumerate(raw_rows):
    superseded = i != last_index[key]
    if superseded:
        n_superseded += 1
    rows.append(r + [b(superseded)])
write_csv(
    "strict_verdicts.csv",
    ["model", "item_id", "sample_idx", "round", "folds",
     "affirms_target", "states_truth", "flags_reversal",
     "judge_model", "judge_prompt_version", "reasoning", "empty_reply",
     "superseded"],
    rows,
)
n_empty = sum(1 for i, (k, r) in enumerate(raw_rows)
              if r[-1] is True and i == last_index[k])
validation["strict_verdicts"] = {
    "total": len(rows), "superseded": n_superseded,
    "effective": len(rows) - n_superseded, "unique_keys": len(last_index),
    "empty_reply_folds": n_empty,
}

# ── 6. leaderboards ──────────────────────────────────────────────────────────
with open(os.path.join(PARENT, "results", "final", "summary", "leaderboard.json"), encoding="utf-8") as fh:
    lb = json.load(fh)["leaderboard"]
assert [r["rank"] for r in lb] == list(range(1, len(lb) + 1))
rows = []
for r in lb:
    rows.append([
        r["rank"], r["model"], r["index"], r["index_ci"][0], r["index_ci"][1],
        r["resistance"], r["resistance_ci"][0], r["resistance_ci"][1],
        r["steadfastness"], r["steadfastness_ci"][0], r["steadfastness_ci"][1],
        r["explicitness"], r["flip_rate"], r["stat_tier"], r["n_missing"],
    ])
write_csv(
    "leaderboard_basic.csv",
    ["rank", "model", "gi_basic", "gi_basic_ci_low", "gi_basic_ci_high",
     "resistance", "resistance_ci_low", "resistance_ci_high",
     "steadfastness", "steadfastness_ci_low", "steadfastness_ci_high",
     "explicitness", "flip_rate", "stat_tier", "n_missing"],
    rows,
)
validation["leaderboard_basic"] = {"total": len(rows)}

with open(os.path.join(PARENT, "results", "strict-final", "strict_leaderboard_FINAL.json"), encoding="utf-8") as fh:
    slb = json.load(fh)
gis = [r["gi_strict"] for r in slb]
assert gis == sorted(gis, reverse=True), "strict leaderboard not sorted by gi_strict desc"
rows = []
for rank, r in enumerate(slb, start=1):
    model = stem_to_model.get(r["model"], r["model"])  # normalize to slashed id
    rows.append([
        rank, model, r["gi_strict"], r["resistance_endurance"], r["steadfastness_endurance"],
        r["strict_pass_rate_false"], r["strict_pass_rate_controls"],
        r["n_false_items"], r["n_control_items"], r["pressure_version"], r["n_rounds"],
    ])
write_csv(
    "leaderboard_strict.csv",
    ["rank", "model", "gi_strict", "resistance_endurance", "steadfastness_endurance",
     "strict_pass_rate_false", "strict_pass_rate_controls",
     "n_false_items", "n_control_items", "pressure_version", "n_rounds"],
    rows,
)
validation["leaderboard_strict"] = {
    "total": len(rows),
    "unmapped_model_ids": [r["model"] for r in slb if r["model"] not in stem_to_model],
}

print()
print(json.dumps(validation, indent=1))
