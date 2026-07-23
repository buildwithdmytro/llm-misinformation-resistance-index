#!/bin/bash
# Add vertex_ai/gemini-3.6-flash to the GI-basic (final) leaderboard.
# Gen (gemini-3.6-flash) and judge (gemini-3.5-flash) are BOTH on the Vertex
# Express key, so they run STRICTLY SEQUENTIALLY here — never concurrent — to
# respect the single-Vertex-stream quota rule. Wall-aware: sleeps through quota
# walls and resumes (both gen and judge are resumable / skip-completed).
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PYTHONPATH=src
RD=results/final
M=vertex_ai/gemini-3.6-flash
SLUG=vertex_ai_gemini-3.6-flash
RESP="$RD/raw/$SLUG.responses.jsonl"
JUDGE="$RD/raw/$SLUG.judge.jsonl"
LOG="$RD/gemini36flash.log"

N_ITEMS=$(python3 -c "import sys; sys.path.insert(0,'src'); from gaslight.data import load_items; print(len(load_items()))")
echo "[$(date +%F' '%T)] target items: $N_ITEMS" >> "$LOG"

# ---- count non-errored (item,sample) pairs in a jsonl ----
count_ok() {  # $1 = path
  python3 - "$1" <<'PY'
import json, sys, os
p = sys.argv[1]
seen = set()
if os.path.exists(p):
    for l in open(p):
        try: r = json.loads(l)
        except Exception: continue
        if r.get('error'): continue
        seen.add((r.get('item_id'), r.get('sample_idx')))
print(len(seen))
PY
}

strip_err() {  # drop errored rows so resume regenerates them
  python3 - "$1" <<'PY'
import json, sys, os
p = sys.argv[1]
if not os.path.exists(p): sys.exit()
rows = [l for l in open(p)]
keep = []
for l in rows:
    try: r = json.loads(l)
    except Exception: continue
    if not r.get('error'): keep.append(l)
if len(keep) < len(rows):
    open(p, 'w').writelines(keep)
PY
}

# ============ PHASE 1: GENERATION (gemini-3.6-flash) ============
while true; do
  B=$(count_ok "$RESP")
  echo "[$(date +%F' '%T)] GEN pass start: $B/$N_ITEMS ok" >> "$LOG"
  if [ "$B" -ge "$N_ITEMS" ]; then
    echo "[$(date +%F' '%T)] GEN-COMPLETE" >> "$LOG"; break
  fi
  timeout 2400 python3 -m gaslight.run \
    --config configs/models.final.yaml --models "$M" \
    --results-dir "$RD" --pace 2 >> "$LOG" 2>&1
  strip_err "$RESP"
  A=$(count_ok "$RESP")
  echo "[$(date +%F' '%T)] GEN pass end: $A/$N_ITEMS ok (+$((A-B)))" >> "$LOG"
  if [ $((A - B)) -lt 5 ] && [ "$A" -lt "$N_ITEMS" ]; then
    echo "[$(date +%F' '%T)] GEN quota wall — sleeping 30m" >> "$LOG"
    sleep 1800
  fi
done

# ============ PHASE 2: JUDGE (gemini-3.5-flash, single stream) ============
# judge.py scans all *.responses.jsonl but skips already-judged keys, so only
# the new model's 180 responses get judged. Judge model comes from the
# models.final.yaml `judge:` block = vertex_ai/gemini-3.5-flash.
while true; do
  B=$(count_ok "$JUDGE")
  echo "[$(date +%F' '%T)] JUDGE pass start: $B/$N_ITEMS judged" >> "$LOG"
  if [ "$B" -ge "$N_ITEMS" ]; then
    echo "[$(date +%F' '%T)] JUDGE-COMPLETE" >> "$LOG"; break
  fi
  timeout 2400 python3 -m gaslight.judge \
    --config configs/models.final.yaml \
    --results-dir "$RD" --pace 2 >> "$LOG" 2>&1
  A=$(count_ok "$JUDGE")
  echo "[$(date +%F' '%T)] JUDGE pass end: $A/$N_ITEMS judged (+$((A-B)))" >> "$LOG"
  if [ $((A - B)) -lt 5 ] && [ "$A" -lt "$N_ITEMS" ]; then
    echo "[$(date +%F' '%T)] JUDGE quota wall — sleeping 30m" >> "$LOG"
    sleep 1800
  fi
done

# ============ PHASE 3: REPORT (rebuild leaderboard) ============
python3 -m gaslight.report --results-dir "$RD" \
  --out "$RD/summary" --no-charts >> "$LOG" 2>&1
echo "[$(date +%F' '%T)] REPORT-DONE — ALL-COMPLETE" >> "$LOG"
