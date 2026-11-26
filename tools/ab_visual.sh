#!/bin/bash
# One controlled visual launch: ab_visual.sh <name> "<extra env assignments>"
# Launches the Series S cutscene run, sends Enter with focus verified, takes screenshots at +150/+165/+180 s after
# Enter, then closes the game. Output: C:\Meraki\.local\upstream-rorodev6\ab\<name>\{err.txt,shot-*.png}
name="$1"; extra="$2"
root=/c/Meraki/.local/upstream-rorodev6
out=$root/ab/$name; mkdir -p "$out"
cd $root/repo
env $extra \
  VICTORY_CARD_PAGE_FETCH=1 VICTORY_CARD_PACK_FETCH=1 VICTORY_SHADER_LOOP_LIMIT=256 VICTORY_RELAY=2 \
  VICTORY_INDIRECT_WINDOW=1 VICTORY_LATE_WAIT=3 VICTORY_WIDE_BACK=1 VICTORY_CARD_BUFFERS_MIN_MB=1 \
  VICTORY_CARD_BUFFERS_MB=1024 VICTORY_JOIN_COPIES=1 VICTORY_CARD_REHASH_RUNS=1 \
  VICTORY_GAME_DIR='C:\Meraki\.local\title-ssd\GTA_VI_FOR_PC_LEGAL' \
  VICTORY_CACHE_DIR='C:\Meraki\.local\upstream-rorodev6\state\cache' \
  VICTORY_DATA_DIR='C:\Meraki\.local\upstream-rorodev6\state\data' \
  ../target-d/diag/victory.exe run 'C:\Meraki\.local\title-ssd\GTA_VI_FOR_PC_LEGAL\game_scarlett_master.exe' \
  --console series-s --execute > "$out/out.txt" 2> "$out/err.txt" &
for i in $(seq 1 60); do sleep 3; P=$(tasklist | grep -i victory.exe | awk '{print $2}'); [ -n "$P" ] && break; done
sleep 25
cd /c/Meraki
for try in 1 2 3 4 5 6; do python .local/upstream-rorodev6/keys.py $P ENTER && break; sleep 5; done
sleep 150
for t in 150 165 180; do
  powershell -NoProfile -File .local/upstream-rorodev6/shot.ps1 "C:\\Meraki\\.local\\upstream-rorodev6\\ab\\$name\\shot-$t.png"
  [ $t != 180 ] && sleep 15
done
powershell -NoProfile -Command "Get-Process victory -ea 0 | Stop-Process -Force"
sleep 4
