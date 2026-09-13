#!/bin/bash
# 契約率40%以下アラート(ピラティス版) — launchd から 9/11/14/17時に起動
# 当日マーカーで1日1回だけ投稿。該当0名の日はマーカーを立てず次の回で再判定。
# Macスリープ明けは WiFi/DNS 未復帰で落ちるため、ネット疎通を待ってから実行する
# (harinature-jisseki/run_contract_rate_alert.sh と同じ対策)。
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/contract_alert_$(date +%Y-%m-%d).log"
MARKER="output/logs/contract_alert_$(date +%Y-%m-%d).done"
{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') 契約率アラート起動 ===="
  if [ -f "$MARKER" ]; then echo "本日投稿済み → 終了"; exit 0; fi
  for i in $(seq 1 20); do
    if /usr/bin/nc -z -G 5 slack.com 443 >/dev/null 2>&1 && \
       /usr/bin/nc -z -G 5 sheets.googleapis.com 443 >/dev/null 2>&1; then
      echo "ネット疎通OK (試行 $i)"; break
    fi
    echo "ネット未復帰 → 30秒待機 ($i/20)"; sleep 30
  done
  /usr/bin/caffeinate -i /usr/bin/env python3 -u src/contract_rate_alert.py --auto
  echo "終了 rc=$?"
} >> "$LOG" 2>&1
