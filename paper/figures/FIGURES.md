# Figure manifest

All figures are generated from `release_numbers.json` (the release's single
source of truth) with matplotlib (Agg backend). Each figure ships as a vector
PDF (primary, for LaTeX) and a 200-dpi PNG twin (for the GitHub README).
Style: DejaVu Serif, 8–9 pt, colorblind-safe palette (#0173B2 blue,
#029E73 green, sequential ColorBrewer reds), no in-figure titles — captions
live in LaTeX.

---

## fig_survival_ladder.pdf / .png

**What it plots.** Horizontal 100 %-stacked bars, one row per model, for 10
GI-strict models (top to bottom): gpt-5.5, gpt-5.6-sol, kimi-k2.6,
gemini-3.6-flash, claude-opus-4.8, gemini-3.5-flash,
nemotron-3-super-120b-a12b, deepseek-v3.2, llama-4-maverick,
mistral-large-2512. Each bar splits that model's false-item pressure chains
(x-axis: share of false-item chains, %) into six outcomes: folded at round 0
through folded at round 4 (sequential reds, lightest to darkest) and held all
5 rounds (green). The held share is annotated at the end of each bar
(e.g. gpt-5.5 100.0 %, mistral-large-2512 7.9 %). Chain counts are normalized
per model by the sum of its histogram row (the model's effective false-chain
count).

**Data fields.** `survival_histograms[<model>].false` = `[fold@r0, fold@r1,
fold@r2, fold@r3, fold@r4, held]`.

**Suggested LaTeX caption.**
> Outcome of every false-item pressure chain for ten GI-strict models, as a
> share of each model's chains. Red segments mark the pressure round at which
> the model folded (round 0 = first contact, lightest, through round 4,
> darkest); green marks chains where the model held through all five rounds,
> with the held share annotated at the bar end. gpt-5.5 held 100.0\% of its
> chains, while mistral-large-2512 held only 7.9\%.

---

## fig_two_axes.pdf / .png

**What it plots.** Scatter of all 37 GI-strict models. x-axis: first-contact
failure (% of a model's false chains failed at round 0); y-axis: capitulation
(% of round-0 survivors that later folded under pressure). Both axes start
at 0 with padding above the maxima (x max 52.6, y max 83.3, both
mistral-large-2512). Eight models carry small leader-line labels: gpt-5.5,
kimi-k2.6, gemini-3.6-flash, gemini-3.5-flash, llama-4-maverick,
llama-4-scout, nemotron-3-super, mistral-large-2512. Light grey grid;
unlabeled points are the remaining strict models.

**Data fields.** `two_axes[<model>].r0_fail_pct` and
`two_axes[<model>].capitulation_pct`.

**Suggested LaTeX caption.**
> First-contact failure (share of false chains failed at round~0) versus
> capitulation (share of round-0 survivors that later folded) for all 37
> GI-strict models. The two failure modes separated cleanly: models such as
> nemotron-3-super often failed on first contact yet held relatively firm
> afterwards, while gemini-3.5-flash rarely failed at round~0 but capitulated
> at a higher rate once pressured, indicating that initial accuracy and
> resistance to sustained pressure are largely distinct skills.

---

## fig_basic_vs_strict.pdf / .png

**What it plots.** Scatter of GI-basic (x-axis, single-turn index) against
GI-strict (y-axis, multi-round index) for the 37 models that qualified for
the strict track (GI-basic ≥ 80). Rows are joined on the model slug
(GI-basic model ids use `/`, replaced by `_` to match strict slugs). Both
axes span 30–101 with a dashed grey y = x reference line. Labeled points:
gpt-5.5 (the only perfect GI-strict, 100.0) and the three largest negative
deltas — mistral-large-2512 (84.6 → 35.1), llama-4-scout (81.4 → 42.8), and
mistral-medium-3-5 (85.1 → 53.5).

**Data fields.** `leaderboard_basic[].index` (joined by
`leaderboard_basic[].model` with `/`→`_`) vs `leaderboard_strict[].gi_strict`.

**Suggested LaTeX caption.**
> Single-turn GI-basic versus multi-round GI-strict for the 37 qualifying
> models (GI-basic $\geq$ 80), with a dashed $y=x$ reference. Sustained
> pressure compressed nothing at the top --- gpt-5.5 rose to the only perfect
> 100.0 --- but collapsed the bottom of the field: mistral-large-2512 fell
> from 84.6 to 35.1, llama-4-scout from 81.4 to 42.8, and mistral-medium-3-5
> from 85.1 to 53.5, showing that single-turn accuracy did not predict
> resistance to escalating pressure.

---

## fig_domains.pdf / .png

**What it plots.** Narrow single-column (~3.5 in) bar chart of pooled
pressure-round survival by dataset domain, sorted ascending, values annotated
above each bar: medicine/health 73.9 %, science/math 77.2 %,
software/security 80.6 %, statistics/data 81.0 %, history/geography 88.0 %.
y-axis: share of pressure rounds survived (%), 0–100. Domain display names
come from the dataset metadata.

**Data fields.** `domain_survival_pct` (keys `med`, `sci`, `sw`, `stat`,
`hist`) with display names from `dataset.domain_names`.

**Suggested LaTeX caption.**
> Share of pressure rounds survived, pooled across all GI-strict models, by
> dataset domain. Medicine/health was the hardest domain (73.9\%) and
> history/geography the easiest (88.0\%), a spread of 14.1 percentage points.

---

## Regeneration

The figures were produced by a standalone script that reads only
`release_numbers.json`; re-running it re-renders all eight files
deterministically (matplotlib 3.7, Agg backend, `bbox_inches='tight'`,
PNG at 200 dpi).
