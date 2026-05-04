#!/bin/bash
# 毎日22:00 松崎さん向け 振り返り蓄積完了 DM通知
# - 当日(YYYY-MM-DD) の feedback_*.log を parse → 件数を松崎さんDMへ送信
# - 全件0なら送らない(「通知不要」)
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/dm_notify_$(date +%Y-%m-%d).log"
{
    echo "===================================="
    echo "📩 dm_notify $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    /usr/bin/env python3 src/notify_after_sync.py
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
