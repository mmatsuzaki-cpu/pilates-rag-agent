#!/bin/bash
# 毎日22:00 実績速報を Slack に送信
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/daily_$(date +%Y-%m-%d).log"
{
    echo "===================================="
    echo "🌅 daily $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    /usr/bin/env python3 src/alert_sender.py
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
