#!/bin/bash
# 月間ランキング配信 (毎日9:00起動 / 1-7日・レッスンCSV取込後に配信)
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs data/lessons
LOG="output/logs/ranking_$(date +%Y-%m).log"
{
    echo "===================================="
    echo "🏆 monthly ranking $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    # ネット疎通を待つ(最大2分)
    for i in $(seq 1 24); do
        if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then echo "✅ ネット疎通OK"; break; fi
        echo "⏳ ネット未復帰、5秒待機 ($i/24)"; sleep 5
    done
    /usr/bin/env python3 src/monthly_ranking.py --auto
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
