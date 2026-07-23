#!/bin/bash
# Usage: run_wave.sh <or-config> <gem-config|-> <results-dir>
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PYTHONPATH=src
OR_CFG=$1; GEM_CFG=$2; RES=$3
{
  echo "[$(date +%F' '%T)] WAVE gen start"
  python3 -m gaslight.run --config "$OR_CFG" --results-dir "$RES" &
  P1=$!
  if [ "$GEM_CFG" != "-" ]; then
    python3 -m gaslight.run --config "$GEM_CFG" --results-dir "$RES" --pace 3 &
    P2=$!
    wait $P2
  fi
  wait $P1
  echo "[$(date +%F' '%T)] gen done, JUDGE start"
  python3 -m gaslight.judge --config "$OR_CFG" --results-dir "$RES" --pace 4
  echo "[$(date +%F' '%T)] WAVE COMPLETE"
} >> "$RES/wave.log" 2>&1
