#!/bin/bash
# 毎月1日 10:30 JST 契約率推移レポート配信 (Mac主役 / GitHub Actions は遅延バックアップ)
# ネット疎通待ち + caffeinate は daily と同じ方針。
# trend_report.py の冪等性チェックで二重送信は防止される。
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/trend_$(date +%Y-%m).log"
{
    echo "===================================="
    echo "📈 契約率推移レポート起動: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    for i in $(seq 1 24); do
        if /usr/bin/nslookup slack.com >/dev/null 2>&1 || /sbin/ping -c1 -t3 8.8.8.8 >/dev/null 2>&1; then
            echo "[$(date '+%H:%M:%S')] ✅ ネット疎通OK (試行 $i)"; break
        fi
        echo "[$(date '+%H:%M:%S')] ⏳ ネット未復帰、5秒待機 ($i/24)"; sleep 5
    done
    /usr/bin/caffeinate -i /usr/bin/env python3 -u src/trend_report.py
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
