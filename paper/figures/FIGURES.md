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
GI-strict models (top to bottom): gpt-5.5, gpt-5.6-sol, claude-opus-5,
kimi-k2.6, gemini-3.6-flash, claude-opus-4.8, gemini-3.5-flash,
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

**What it plots.** Scatter of all 38 GI-strict models. x-axis: first-contact
failure (% of a model's false chains failed at round 0); y-axis: capitulation
(% of round-0 survivors that later folded under pressure). Both axes start
at 0 with padding above the maxima (x max 52.6, y max 83.3, both
mistral-large-2512). Nine models carry small leader-line labels: gpt-5.5,
claude-opus-5, kimi-k2.6, gemini-3.6-flash, gemini-3.5-flash, llama-4-maverick,
llama-4-scout, nemotron-3-super, mistral-large-2512. Light grey grid;
unlabeled points are the remaining strict models.

**Data fields.** `two_axes[<model>].r0_fail_pct` and
`two_axes[<model>].capitulation_pct`.

**Suggested LaTeX caption.**
> First-contact failure (share of false chains failed at round~0) versus
> capitulation (share of round-0 survivors that later folded) for all 38
> GI-strict models. The two move together --- Pearson $r = 0.92$, 95\% CI
> $[0.85, 0.96]$ --- so most of the scatter lies along a single
> failure-proneness axis. The spread about the least-squares line is
> nonetheless substantial (residual SD 7.2 percentage points) and carries
> information a composite score would discard: nemotron-3-super sits 14.8~pp
> *below* the line (38.9\% first-contact failure, but only 31.8\% of its
> survivors fold) while gemini-3.5-flash sits 10.5~pp *above* it (4.9\%
> first-contact failure, yet 14.3\% of its survivors fold). In absolute terms
> nemotron-3-super still capitulates more often than gemini-3.5-flash; the
> ordering reverses only relative to each model's own first-contact rate.

---

## fig_basic_vs_strict.pdf / .png

**What it plots.** Scatter of GI-basic (x-axis, single-turn index) against
GI-strict (y-axis, multi-round index) for the 38 models that qualified for
the strict track (GI-basic ≥ 80). Rows are joined on the model slug
(GI-basic model ids use `/`, replaced by `_` to match strict slugs). Both
axes span 30–101 with a dashed grey y = x reference line. Labeled points:
gpt-5.5 (the only perfect GI-strict, 100.0) and the three largest negative
deltas — mistral-large-2512 (84.6 → 35.1), llama-4-scout (81.4 → 42.8), and
mistral-medium-3-5 (85.1 → 53.5).

**Data fields.** `leaderboard_basic[].index` (joined by
`leaderboard_basic[].model` with `/`→`_`) vs `leaderboard_strict[].gi_strict`.

**Suggested LaTeX caption.**
> Single-turn GI-basic versus multi-round GI-strict for the 38 qualifying
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
above each bar: medicine/health 74.7 %, science/math 77.9 %,
software/security 81.2 %, statistics/data 81.5 %, history/geography 88.3 %.
y-axis: share of pressure rounds survived (%), 0–100. Domain display names
come from the dataset metadata.

**Data fields.** `domain_survival_pct` (keys `med`, `sci`, `sw`, `stat`,
`hist`) with display names from `dataset.domain_names`.

**Suggested LaTeX caption.**
> Share of pressure rounds survived, pooled across all GI-strict models, by
> dataset domain. Medicine/health was the hardest domain (74.7\%) and
> history/geography the easiest (88.3\%), a spread of 13.6 percentage points.

---

## fig_lmri_stretch.pdf / .png

**What it plots.** Two panels explaining the headline LMRI transform at the
released `k=5`. *Left:* the log-stretch curve of Eq. 1 against the identity
line, over GI-strict 0–100, with the 38 observed GI-strict scores drawn as a
rug along the x-axis (they span 35.1–100.0; 14 of 38 sit at or above 95).
Two equal 3-point raw intervals are bracketed to show unequal magnification:
97→100 becomes 15.4 stretched points, 60→63 becomes 2.3. *Right:* a dumbbell
plot of each of the 38 qualifiers' raw GI-strict (grey) and stretched
GI-strict (blue), ordered top-to-bottom by LMRI.

**Data fields.** `leaderboard_strict[].gi_strict` and
`leaderboard_basic[].index` (for LMRI ordering only); the curve itself is the
analytic function `gaslight.score.log_stretch`, not data.

**Suggested LaTeX caption.**
> The log-stretch of Eq. 1 at the released $k=5$. *Left:* the transform
> against the identity, with the 38 observed GI-strict scores drawn as a rug.
> Because the curve steepens towards 100, equal intervals of raw endurance are
> not worth equal amounts: the three points between 97 and 100 become 15.4
> stretched points, while the same three points between 60 and 63 become 2.3 —
> a magnification of roughly $6.7\times$ at the crowded top of the board.
> *Right:* each qualifier's raw and stretched GI-strict, in LMRI order. The
> transform pulls every score down (it is a rescaling of failure mass, not a
> bonus) but pulls the mid-board down much further than the leaders.

---

## Regeneration

```bash
PYTHONPATH=src python3 tools/make_figures.py
```

The script reads only `release_numbers.json` (plus `gaslight.score` for the
analytic stretch curve) and re-renders all ten files deterministically
(matplotlib 3.7, Agg backend, `bbox_inches='tight'`, PNG at 200 dpi). It
contains no numeric literals from the results.
