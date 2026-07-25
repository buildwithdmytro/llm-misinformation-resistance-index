#!/bin/bash
# Strict (escalation) run for openrouter/anthropic/claude-opus-5 — puts it on
# the HEADLINE GI-strict leaderboard. Gen runs on OpenRouter; the escalation
# `run` stage does gen + INLINE judge (gemini-3.5-flash on Vertex Express) in
# ONE process, sequentially — a single Vertex judge stream, never concurrent.
#
# Wall-aware: errored gen/judge rows are terminal for a chain (chain_dead), so
# each pass strips them and resumes. Convergence = a pass that finishes on its
# own (timeout NOT triggered) leaving zero errored rows behind. Quota walls
# surface as errored rows and/or tiny progress deltas -> sleep 30m, resume.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PYTHONPATH=src
RD=results/strict-final
CFG=/tmp/claude-1000/opus5_strict.yaml
SLUG=openrouter_anthropic_claude-opus-5
GEN="$RD/raw/$SLUG.escalation.jsonl"
JDG="$RD/raw/$SLUG.escalation.judge.jsonl"
LOG="$RD/opus5_strict.log"

# non-errored gen rows (progress signal)
gen_ok()  { python3 - "$GEN" <<'PY'
import json,sys,os
p=sys.argv[1]; n=0
if os.path.exists(p):
    for l in open(p):
        try: r=json.loads(l)
        except: continue
        if not r.get('error'): n+=1
print(n)
PY
}
# errored rows across gen+judge (blockers)
err_total() { python3 - "$GEN" "$JDG" <<'PY'
import json,sys,os
n=0
for p in sys.argv[1:]:
    if not os.path.exists(p): continue
    for l in open(p):
        try: r=json.loads(l)
        except: continue
        if r.get('error'): n+=1
print(n)
PY
}
strip_err() { python3 - "$GEN" "$JDG" <<'PY'
import json,sys,os
for p in sys.argv[1:]:
    if not os.path.exists(p): continue
    rows=[l for l in open(p)]
    good=[]
    for l in rows:
        try: r=json.loads(l)
        except: continue
        if not r.get('error'): good.append(l)
    if len(good)<len(rows): open(p,'w').writelines(good)
PY
}

stall=0
echo "[$(date +%F' '%T)] STRICT-START claude-opus-5 (48 items x 3 samples x <=5 rounds)" >> "$LOG"
while true; do
  strip_err
  B=$(gen_ok)
  echo "[$(date +%F' '%T)] pass start: $B non-errored gen rows" >> "$LOG"
  timeout 2400 python3 -m gaslight.escalation run \
    --config "$CFG" --subset configs/strict_subset.yaml \
    --results-dir "$RD" --pace 1 --max-attempts 3 >> "$LOG" 2>&1
  rc=$?
  E=$(err_total)
  A=$(gen_ok)
  echo "[$(date +%F' '%T)] pass end rc=$rc: $A gen rows (+$((A-B))), $E errored rows" >> "$LOG"
  # Natural finish (not killed by timeout) with no errors left to strip = DONE.
  if [ "$rc" -eq 0 ] && [ "$E" -eq 0 ]; then
    echo "[$(date +%F' '%T)] STRICT-RUN-COMPLETE" >> "$LOG"; break
  fi
  strip_err
  # Little/no forward progress *twice running* => quota wall; back off. A single
  # stalled pass is usually just convergence: the run finished, one row errored,
  # and stripping it leaves exactly one row to redo — sleeping 30m for that is
  # wasted time and makes the log read as though a wall was hit when none was.
  if [ $((A - B)) -lt 10 ]; then
    stall=$((stall + 1))
    if [ "$stall" -ge 2 ]; then
      echo "[$(date +%F' '%T)] wall (no progress x$stall) — sleeping 30m" >> "$LOG"
      sleep 1800
      stall=0
    else
      echo "[$(date +%F' '%T)] no progress; retrying stripped rows immediately" >> "$LOG"
    fi
  else
    stall=0
  fi
done

# ---- JUDGE CATCH-UP: fill round-0 explicitness bits (the passF gate). ----
# Inline judging produces fold verdicts only; a strict score is NOT final
# until every round-0 row carries bits (the kimi-k3 / gemini-3.6-flash lesson).
while true; do
  echo "[$(date +%F' '%T)] BITS pass start" >> "$LOG"
  timeout 2400 python3 -m gaslight.escalation judge \
    --config "$CFG" --subset configs/strict_subset.yaml \
    --results-dir "$RD" --pace 1 --max-attempts 5 >> "$LOG" 2>&1
  rc=$?
  MISSING=$(python3 - "$JDG" <<'PY'
import json,sys
last={}
for l in open(sys.argv[1]):
    r=json.loads(l)
    if r.get('round')==0: last[(r['item_id'],r['sample_idx'])]=r
print(sum(1 for r in last.values() if r.get('bits') is None))
PY
)
  echo "[$(date +%F' '%T)] BITS pass end rc=$rc: $MISSING round-0 rows missing bits" >> "$LOG"
  if [ "$rc" -eq 0 ] && [ "$MISSING" -eq 0 ]; then
    echo "[$(date +%F' '%T)] BITS-COMPLETE" >> "$LOG"; break
  fi
  if [ "$rc" -ne 0 ]; then
    echo "[$(date +%F' '%T)] BITS wall — sleeping 30m" >> "$LOG"
    sleep 1800
  fi
done

# ---- SCORE: produce the strict scorecard for this model ----
python3 -m gaslight.escalation score \
  --config "$CFG" --subset configs/strict_subset.yaml \
  --results-dir "$RD" >> "$LOG" 2>&1
echo "[$(date +%F' '%T)] SCORE-DONE — ALL-COMPLETE" >> "$LOG"
