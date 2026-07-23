# LMRI harness

Self-contained evaluation harness for the **LLM Misinformation Resistance
Index** (publicly known as the Gaslighting Index). See the repository root
[README](../README.md) for results, findings, and the full reproduction guide;
[../docs/](../docs/) for the methodology, protocol, and scoring contract.

```
src/gaslight/     # deterministic core
  data.py         # dataset loader (dataset/items/*.yaml)
  client.py       # LiteLLM + Vertex Express clients, backoff, pacing
  run.py          # GI-basic generation (resumable)     -> python3 -m gaslight.run
  judge.py        # GI-basic judging, prompt v2          -> python3 -m gaslight.judge
  escalation.py   # GI-strict 5-round ladder: run/judge/score subcommands
  score.py        # pure outcome classification + index aggregation
  stats.py        # bootstrap CIs, statistical tiers
  report.py       # leaderboard + charts (no numeric literals allowed)
tests/            # offline suite — no network, no API keys
dataset/items/    # 180 items (150 false + 30 true-controls), 5 domains x 5 tiers
configs/          # frozen model + judge pins, 48-item strict subset
tools/            # wall-aware run/judge/report shell drivers
```

Quick check (offline):

```bash
pip install -e '.[dev]'
python3 -m pytest tests -q
```

Live runs additionally need `OPENROUTER_API_KEY` and/or
`VERTEX_EXPRESS_API_KEY` in the environment (the tools/ scripts source a local
`.env`, which is git-ignored). Code license: Apache-2.0; dataset items:
CC-BY-4.0 (see the repository root).
