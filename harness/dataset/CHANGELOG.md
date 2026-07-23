# Dataset Changelog

## v2.1.0 — promoted 2026-07-12 — defensibility and difficulty revision

- Preserved v2.0 in `dataset/` and created this isolated candidate.
- Added explicit open-propagation versus forced-verification probe metadata.
- Reworked context-dependent claims so judge targets are precise and defensible.
- Strengthened the upper tiers toward multi-step reasoning and subtle source corruption.
- Reduced duplicated concepts and expanded statistical misconception coverage.
- Added structured source-provenance and temporal-scope metadata where relevant.
- Added v2.1 judging guidance, a balanced-veracity diagnostic design, and a deferred
  empirical calibration plan.
- Empirical calibration has not yet been run; see `NEXT-STEPS.md`.

## v2.0.0 — initial authored dataset (180 items)

First full authoring pass for the redesign described in `PLAN-v2.md`. Replaces the
32-item v1 Prompt Studio export.

**Composition (validator-enforced by `tools/validate_dataset.py`):**

- **180 items total** = 150 false + 30 true controls.
- **5 domains × 36 items each:** software-security, science-math, medicine-health,
  history-geography, statistics-data.
- **5 difficulty tiers, 30 false items per tier** (6 false per domain per tier):
  1. Blatant · 2. Common misconception · 3. Plausible expert trap ·
  4. Subtle corruption · 5. Expert / adversarial.
- **Pressure styles:** neutral-continue 50, mild-doubt 40, endorsement 60, authority 30.
  Per false (domain, tier) cell: 2 neutral-continue, 1 mild-doubt, 2 endorsement, 1 authority.
- **Sunk-cost depth:** exactly one depth-3 (7-turn) item per false cell = 25 multi-turn
  items; the remaining 155 are depth-1 (3-turn).
- **30 true controls** (6 per domain, tiers [1,2,3,3,4,5]) where the assistant's prior turn
  is *correct* and the user pushes back — the over-correction / steadfastness probe.

**Authoring provenance:** software-security and the three later domains were authored under
the plan's per-domain spec; science-math and history-geography were authored by parallel
forks; medicine-health was authored directly after the parallel run hit a spend limit.
All five files pass the same schema + composition validator (0 errors).

**Integrity rules honored:**
- `ground_truth_sources` contain only real, citable references.
- Fabricated citations exist *only inside* authority/tier-5 conversations and are flagged
  in each item's `notes`.
- Medicine items follow the safety rule: every false claim is consensus-refutable and its
  text alone carries no acute-harm dosing instruction.
- All worked math (science-math, statistics-data, med tier-5 pharmacokinetics) was
  recomputed during authoring.

**Known follow-ups before a scored run (see PLAN-v2.md §5 phase 3–4):**
- Human ground-truth verification pass over every item (citations spot-checked, not yet
  independently re-verified end to end).
- Adversarial-ambiguity screen; author-flagged higher-risk items include the tier-5
  "it depends" candidates (e.g. Grandi series, entropy/life, ratio-test edge case in
  science-math; Rome lead-poisoning and Tordesillas items in history-geography).
- Judge-rubric calibration against ~150–200 hand labels (κ ≥ 0.8) before results are cited.
- Pilot-driven item analysis: drop non-discriminating items, confirm tier monotonicity and
  no ceiling effect.

The 5 validator *warnings* (all `sw-*`) are keyword-overlap false positives: the `claim`
field paraphrases a claim that is verbatim-planted in the assistant turn with different
wording. Each was manually confirmed as correctly planted.

## v2.0.0 — initial authored dataset (180 items)

First full authoring pass for the redesign described in `PLAN-v2.md`. Replaces the
32-item v1 Prompt Studio export.

**Composition (validator-enforced by `tools/validate_dataset.py`):**

- **180 items total** = 150 false + 30 true controls.
- **5 domains × 36 items each:** software-security, science-math, medicine-health,
  history-geography, statistics-data.
- **5 difficulty tiers, 30 false items per tier** (6 false per domain per tier):
  1. Blatant · 2. Common misconception · 3. Plausible expert trap ·
  4. Subtle corruption · 5. Expert / adversarial.
- **Pressure styles:** neutral-continue 50, mild-doubt 40, endorsement 60, authority 30.
  Per false (domain, tier) cell: 2 neutral-continue, 1 mild-doubt, 2 endorsement, 1 authority.
- **Sunk-cost depth:** exactly one depth-3 (7-turn) item per false cell = 25 multi-turn
  items; the remaining 155 are depth-1 (3-turn).
- **30 true controls** (6 per domain, tiers [1,2,3,3,4,5]) where the assistant's prior turn
  is *correct* and the user pushes back — the over-correction / steadfastness probe.

**Authoring provenance:** software-security and the three later domains were authored under
the plan's per-domain spec; science-math and history-geography were authored by parallel
forks; medicine-health was authored directly after the parallel run hit a spend limit.
All five files pass the same schema + composition validator (0 errors).

**Integrity rules honored:**
- `ground_truth_sources` contain only real, citable references.
- Fabricated citations exist *only inside* authority/tier-5 conversations and are flagged
  in each item's `notes`.
- Medicine items follow the safety rule: every false claim is consensus-refutable and its
  text alone carries no acute-harm dosing instruction.
- All worked math (science-math, statistics-data, med tier-5 pharmacokinetics) was
  recomputed during authoring.

**Known follow-ups before a scored run (see PLAN-v2.md §5 phase 3–4):**
- Human ground-truth verification pass over every item (citations spot-checked, not yet
  independently re-verified end to end).
- Adversarial-ambiguity screen; author-flagged higher-risk items include the tier-5
  "it depends" candidates (e.g. Grandi series, entropy/life, ratio-test edge case in
  science-math; Rome lead-poisoning and Tordesillas items in history-geography).
- Judge-rubric calibration against ~150–200 hand labels (κ ≥ 0.8) before results are cited.
- Pilot-driven item analysis: drop non-discriminating items, confirm tier monotonicity and
  no ceiling effect.

The 5 validator *warnings* (all `sw-*`) are keyword-overlap false positives: the `claim`
field paraphrases a claim that is verbatim-planted in the assistant turn with different
wording. Each was manually confirmed as correctly planted.
