#!/bin/bash
# Persistent single-stream judge loop for the GI-strict sweep. Survives Vertex
# daily-quota windows: judge whatever it can, compact files, sleep, retry.
# Exits (writing STRICT-JUDGE-COMPLETE) only when every (item,sample,round) has a
# good verdict and every round-0 row has bits. Single stream — never concurrent.
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PYTHONPATH=src
DIR=results/strict-final
LOG=$DIR/judge.log

remaining() {  # prints "<fold_missing> <bits_missing>"
  python3 - <<'PY'
import json, glob, os
raw='results/strict-final/raw'
fm=bm=0
for jf in glob.glob(raw+'/*.escalation.judge.jsonl'):
    rows=[json.loads(l) for l in open(jf)]
    gf=set(); gb=set(); keys=set()
    for r in rows:
        k=(r['item_id'],r['sample_idx'],r['round']); keys.add(k)
        if not r.get('error'): gf.add(k)
        if r['round']==0 and r.get('bits') is not None: gb.add(k)
    fm+=len(keys-gf); bm+=len({k for k in keys if k[2]==0}-gb)
print(fm, bm)
PY
}

compact() {  # keep best row per (item,sample,round): non-errored + bits win
  python3 - <<'PY'
import json, glob, os
raw='results/strict-final/raw'
for jf in glob.glob(raw+'/*.escalation.judge.jsonl'):
    best={}
    for l in open(jf):
        r=json.loads(l); k=(r['item_id'],r['sample_idx'],r['round'])
        old=best.get(k)
        if old is None: best[k]=r; continue
        # prefer: no-error, then has-bits (round 0)
        score=lambda x:(0 if x.get('error') else 1, 1 if x.get('bits') is not None else 0)
        if score(r)>score(old): best[k]=r
    tmp=jf+'.tmp'
    with open(tmp,'w') as fh:
        for r in best.values(): fh.write(json.dumps(r)+'\n')
    os.replace(tmp,jf)
PY
}

while true; do
  compact
  read FM BM < <(remaining)
  echo "[$(date +%F' '%T)] remaining: fold=$FM bits=$BM" >> "$LOG"
  if [ "$FM" -eq 0 ] && [ "$BM" -eq 0 ]; then
    echo "[$(date +%F' '%T)] SCORE" >> "$LOG"
    python3 -m gaslight.escalation score --results-dir "$DIR" >> "$LOG" 2>&1
    echo "[$(date +%F' '%T)] STRICT-JUDGE-COMPLETE" >> "$LOG"
    break
  fi
  BEFORE=$((FM + BM))
  # one bounded judge pass (20 min max) so the loop always cycles back to
  # compact/sleep even when a quota wall makes every row grind through backoff.
  timeout 1200 python3 -m gaslight.escalation judge \
    --config configs/models.strict-final.yaml \
    --subset configs/strict_subset.yaml --results-dir "$DIR" --pace 1 \
    --max-attempts 1 >> "$LOG" 2>&1
  # data-driven wall detection: did this pass actually reduce the remaining work?
  read NFM NBM < <(remaining)
  AFTER=$((NFM + NBM))
  PROGRESS=$((BEFORE - AFTER))
  echo "[$(date +%F' '%T)] pass progress: $PROGRESS units (remaining fold=$NFM bits=$NBM)" >> "$LOG"
  if [ "$PROGRESS" -lt 30 ]; then
    echo "[$(date +%F' '%T)] quota wall (progress=$PROGRESS) — sleeping 30m" >> "$LOG"
    sleep 1800
  else
    sleep 20
  fi
done
