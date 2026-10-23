#!/bin/sh
# Resumable 3.0.5 paired runs (starter 70 + hunter 20) for the bots given as args, e.g. `sh scripts/run305.sh h2 v5`.
# Each bot needs fixed copies bots/<bot>-305a and bots/<bot>-305b. Finished games are skipped.
cd "$(dirname "$0")/.."
export CAMBC=${CAMBC:-$HOME/cambc305/cambc-3.0.5.data/scripts/cambc}
A=$(ls maps3 | sed 's/.map26a//' | awk '{print $1":a"}' | tr '\n' ' '); B=$(ls maps3 | sed 's/.map26a//' | awk '{print $1":b"}' | tr '\n' ' ')
HA=""; HB=""; for m in 00ambush 00contest 00eight 00expanse 00packs 00split 00swirl 01boss_battle 01corridors 01islands; do HA="$HA $m:a"; HB="$HB $m:b"; done
for bot in "$@"; do
  for s in a b; do
    [ $s = a ] && S=$A && H=$HA || { S=$B; H=$HB; }
    pgrep -f "games.py ${bot}-305$s " >/dev/null && continue
    nohup sh -c "python3 scripts/games.py ${bot}-305$s starter results/run305/${bot}_starter 1 $S; python3 scripts/games.py ${bot}-305$s hunter results/run305/${bot}_hunter 1 $H" >> results/run305/${bot}$s.log 2>&1 &
  done
done
