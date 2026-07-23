# Contributing — adding a model to the boards

The benchmark stays comparable across time because the procedure below is
**fixed**. New models are appended; scoring rules, dataset items, pressure
prompts, and judge pins are never modified as part of adding a row. If you
believe a rule itself is wrong, open an issue — that is a protocol-version
change (a new board), not a contribution to this one.

## Ground rules (non-negotiable)

1. **Append-only configs.** Add your model to `harness/configs/models.final.yaml`
   (and, if it qualifies, `harness/configs/models.strict-final.yaml`) as a new
   entry with an exact routable pin (e.g. `openrouter/vendor/model-x.y`,
   `vertex_ai/model-z`). Do not touch `defaults:`, the `judge:` block, or any
   existing entry.
2. **Judge pins stay frozen.** All verdicts come from
   `vertex_ai/gemini-3.5-flash` at temperature 0: prompt **v2** for GI-basic
   (max_tokens 512), **round-judge-v3** (pressure rounds) and
   **retract-judge-v4** (controls) for GI-strict (max_tokens 2048). A row
   judged by anything else is not comparable and will be rejected.
3. **Single-stream judging.** Generation may fan out; judging runs as **one**
   stream (`--pace 1`), never concurrently. Concurrent judge streams against a
   shared quota is how the harness once lost ~12,000 verdicts in a night (see
   the lab notebook in `docs/FINDINGS.md`).
4. **Refusals and evasions are failures.** Do not "fix" a low score by
   prompt-tuning around the protocol; the system and user turns are part of
   the frozen items.
5. **Dataset and subset are frozen** at v2.1.0 / the 48-item
   `configs/strict_subset.yaml`. No cherry-picking items.

## Procedure

```bash
pip install -e './harness[dev,report]'
cd harness
export PYTHONPATH=src
# keys by name only, never committed: OPENROUTER_API_KEY, VERTEX_EXPRESS_API_KEY
```

### 1 · GI-basic (always first)

```bash
# generate: 180 items x 1 sample for just your model
python3 -m gaslight.run   --config configs/models.final.yaml \
    --models <your/model/pin> --results-dir results/final

# judge: single stream; skips already-judged keys, so only your rows are judged
python3 -m gaslight.judge --config configs/models.final.yaml \
    --results-dir results/final --pace 2

# regenerate the leaderboard (numbers come only from result rows — never edit by hand)
python3 -m gaslight.report --results-dir results/final --out results/final/summary
```

For a long-running or quota-walled provider, adapt the wall-aware driver
`harness/tools/add_gemini36flash_basic.sh` (gen → judge → report, resumable,
sleeps through quota walls). Before reading a score, confirm all 180
`(item, sample)` pairs have non-errored response *and* judge rows.

### 2 · Qualification gate

**GI-strict is open to models with GI-basic ≥ 80.** Below that, the basic row
is the result; do not run the escalation protocol.

### 3 · GI-strict (qualifiers only)

```bash
# escalation run: 48 items x 3 chains x <=5 rounds, inline single-stream judging
python3 -m gaslight.escalation run   --config configs/models.strict-final.yaml \
    --subset configs/strict_subset.yaml --results-dir results/strict-final --pace 1

# catch-up judge: REQUIRED — fills fold verdicts that errored AND the round-0
# explicitness bits. A missing bits pass silently computes passF = 0.0.
python3 -m gaslight.escalation judge --config configs/models.strict-final.yaml \
    --subset configs/strict_subset.yaml --results-dir results/strict-final --pace 1

# score
python3 -m gaslight.escalation score --results-dir results/strict-final
```

Wall-aware equivalents: `harness/tools/run_gemini36flash_strict.sh` (run) and
`harness/tools/judge_strict_until_done.sh` (judge loop; exits only when every
`(item, sample, round)` has a good verdict and every round-0 row has bits).

A strict score is final only when: every chain is either folded or has played
all 5 rounds; no errored rows remain; every round-0 row carries bits.

### 4 · Report regeneration

Regenerate the boards from the result files (`gaslight.report` for basic,
`escalation score` for strict). Never hand-edit a leaderboard file, CSV, or
README table — report code is forbidden from containing numeric literals, and
PRs that edit numbers directly will be closed.

## What a PR must include

- The config diff (append-only, as above).
- **The raw JSONL** for your model:
  `results/final/raw/<slug>.responses.jsonl` + `<slug>.judge.jsonl`, and for
  strict runs `results/strict-final/raw/<slug>.escalation.jsonl` +
  `<slug>.escalation.judge.jsonl`. No raw rows, no row on the board.
- The regenerated summary/leaderboard output.
- Run metadata in the PR description: date of run, provider/router used, and
  any anomalies (walls hit, retries, provider-side truncation).
- No secrets anywhere — keys are environment variables by name only.

## Everything else

Bug fixes and test additions to the harness are welcome under the normal
rules: `python3 -m pytest tests -q` must stay green and fully offline, and
changes to scoring semantics require a protocol version bump rather than an
in-place edit. Licensing: code contributions under Apache-2.0, dataset/docs
contributions under CC-BY-4.0.
