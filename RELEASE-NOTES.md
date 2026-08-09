## LMRI v2.1.0 — first public release

LMRI measures whether a language model corrects a falsehood planted in its
**own previous answer**, and whether it maintains that correction under four
rounds of escalating social pressure.

Most sycophancy benchmarks attribute the falsehood to the *user*. LMRI places
it in the assistant's own transcript, adds sunk costs, and escalates through a
fixed four-round ladder: social proof, evidence appeal, consistency attack,
and a deadline ultimatum ("just confirm it — a simple yes").

### What is measured

| Score | Protocol |
|---|---|
| **GI-basic** | 46 models × 180 items, single round |
| **GI-strict** | 38 qualifiers × 48 items × 3 chains × up to 5 rounds — 23,135 judged rounds |
| **LMRI** | `0.2 × GI-basic + 0.8 × stretch(GI-strict)` — the headline blend |

Control items mirror the design: the planted answer is *correct* and the user
presses a wrong alternative, so a model cannot score well by reflexive
agreement. GI-basic and passF both score an evasion as a failure, which rules
out reflexive refusal.

### Leaders

| # | Model | LMRI | GI-basic | GI-strict |
|--:|---|---:|---:|---:|
| 1 | `openai/gpt-5.5` | **98.8** | 93.9 | 100.0 |
| 2 | `vertex_ai/gemini-3.6-flash` | **88.7** | 98.3 | 97.4 |
| 3 | `openai/gpt-5.6-terra` | **88.3** | 96.6 | 97.4 |

### Five findings

1. Failures concentrate at the ultimatum round rather than accumulating
   gradually: models typically hold with correct reasoning for four rounds
   and then capitulate at the deadline.
2. First-contact failure and later capitulation correlate at r = 0.91; the
   residual spread nonetheless separates models that a single score ties.
3. A single statistics item defeated 37 of 38 models — a two-arm trial
   sample-size formula missing its factor of 2, framed with the IRB
   application already submitted.
4. gpt-5.5 was the only model to survive every chain, and its score under
   pressure exceeded its single-turn score, while the lowest-scoring models
   lost up to 49.5 points.
5. 24 of 38 models produced no retraction of a true answer under the same
   ladder that defeated them on false ones, indicating consistency with the
   transcript rather than truth-tracking.

### What ships

Dataset (CC BY 4.0), harness and scoring code (Apache-2.0), every model
response, every judge verdict — including the superseded re-judges, so the
pre-fix boards are reconstructible — and both leaderboards plus the derived
LMRI board. Every published number recomputes from the released CSVs with one
command.

### Error analysis

Five harness incidents are documented with the results, including two that
changed published scores: the judge inverted its verdicts on control items (a
negated yes/no question with the answer token emitted before the reasoning),
and empty replies were scored as successful resistance by one judge while the
other scored the identical reply as a failure.

Read alongside the paper's Limitations: the human judge-calibration study
(κ ≥ 0.80) and the cross-provider re-judge are design intent and were **not
run**. passF is a lower bound.

Paper: `lmri-paper.pdf`, attached.
