## LMRI v2.1.0 — first public release

Does a language model correct a falsehood planted in its **own previous answer** —
and keep that correction when a user leans on it, socially, four times over?

Most sycophancy benchmarks put the falsehood in the *user's* mouth. LMRI puts it
in the assistant's own transcript, adds sunk costs, and then escalates: a
colleague disagrees, two sources disagree, you're contradicting yourself, and
finally a deadline with "just confirm it — a simple yes."

### What's measured

| Score | Protocol |
|---|---|
| **GI-basic** | 46 models × 180 items, single round |
| **GI-strict** | 38 qualifiers × 48 items × 3 chains × up to 5 rounds — 23,135 judged rounds |
| **LMRI** | `0.2 × GI-basic + 0.8 × stretch(GI-strict)` — the headline blend |

Control items run the ladder in reverse: the planted answer is *correct* and the
user pushes a wrong one, so a model cannot win by reflexively agreeing. GI-basic
and passF both score a dodge as a failure, which closes off reflexively refusing.

### Leaders

| # | Model | LMRI | GI-basic | GI-strict |
|--:|---|---:|---:|---:|
| 1 | `openai/gpt-5.5` | **98.8** | 93.9 | 100.0 |
| 2 | `vertex_ai/gemini-3.6-flash` | **88.7** | 98.3 | 97.4 |
| 3 | `openai/gpt-5.6-terra` | **88.3** | 96.6 | 97.4 |

### Five findings

1. Models don't erode, they **snap** — four rounds of correct reasoning, then the
   deadline ultimatum, where the cheapest available token is agreement.
2. First-contact failure and later capitulation correlate at r = 0.91, but the
   residual spread separates models a single score ties.
3. **One statistics item broke 37 of 38 models** — a two-arm trial sample-size
   formula missing its factor of 2, with the IRB application already submitted.
4. gpt-5.5 was the only model to survive every chain — and it *rose* under
   pressure relative to its single-turn score, while the bottom of the field
   collapsed by up to 49.5 points.
5. **24 of 38 models never once retracted a true answer** under the same ladder
   that broke them on false ones. They defend the transcript, not the truth.

### What ships

Dataset (CC BY 4.0), harness and scoring code (Apache-2.0), every model response,
every judge verdict — including the superseded re-judges, so the pre-fix boards
are reconstructible — and both leaderboards plus the derived LMRI board. Every
published number recomputes from the released CSVs with one command.

### The lab notebook

Five incidents ship with the results, including two that moved published scores:
our own judge was **inverting its verdicts on control items** (a negated yes/no
question with the answer token emitted before the reasoning), and blank replies
were being scored as **successful resistance** by one judge while the other
scored the identical reply as a failure.

Read alongside the paper's Limitations: the human judge-calibration study
(κ ≥ 0.80) and the cross-provider re-judge are design intent and were **not run**.
passF is a lower bound.

Paper: `lmri-paper.pdf`, attached.
