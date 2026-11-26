# Series S hardware run with the preset used for the interactive prologue comparison.
# Usage: powershell -NoProfile -File tools\run_series_s.ps1 [-Data <dir>] [-Log <dir>]
param([string]$Data = 'C:\Meraki\.local\upstream-rorodev6\state\data', [string]$Log = 'C:\Meraki\.local\upstream-rorodev6\logs\latest')
$root = 'C:\Meraki\.local\upstream-rorodev6'
New-Item -ItemType Directory -Force $Log | Out-Null
$env:VICTORY_GAME_DIR = 'C:\Meraki\.local\title-ssd\GTA_VI_FOR_PC_LEGAL'
$env:VICTORY_CACHE_DIR = "$root\state\cache"
$env:VICTORY_DATA_DIR = $Data
$env:VICTORY_SHADER_LOOP_LIMIT = '256'
$env:VICTORY_RELAY = '2'; $env:VICTORY_INDIRECT_WINDOW = '1'; $env:VICTORY_LATE_WAIT = '3'; $env:VICTORY_WIDE_BACK = '1'
$env:VICTORY_CARD_BUFFERS_MIN_MB = '1'; $env:VICTORY_CARD_BUFFERS_MB = '1024'; $env:VICTORY_JOIN_COPIES = '1'; $env:VICTORY_CARD_REHASH_RUNS = '1'
$env:VICTORY_RT_RESOLVE = '1'; $env:VICTORY_CARD_PAGE_FETCH = '1'; $env:VICTORY_CARD_PACK_FETCH = '0'; $env:VICTORY_HEAP_FULL_EVERY = '64'
& "$root\target-d\diag\victory.exe" run "$env:VICTORY_GAME_DIR\game_scarlett_master.exe" --console series-s --execute 1> "$Log\out.txt" 2> "$Log\err.txt"
