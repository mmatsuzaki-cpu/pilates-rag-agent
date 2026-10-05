#!/bin/bash
# 集計表の翌月シート自動作成 (毎日8:20起動 / 27日〜月末に翌月分・1〜3日は当月分の取りこぼし救済)
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/monthly_tabs_$(date +%Y-%m).log"
{
    echo "===================================="
    echo "📄 monthly tabs $(date '+%Y-%m-%d %H:%M:%S')"
    for i in $(seq 1 24); do
        if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then break; fi
        echo "⏳ ネット未復帰、5秒待機 ($i/24)"; sleep 5
    done
    /usr/bin/env python3 src/create_next_month_tabs.py
} >> "$LOG" 2>&1
