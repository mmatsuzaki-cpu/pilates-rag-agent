#!/bin/bash
# 5分ごと QAボット
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/qa_bot_$(date +%Y-%m-%d).log"
{
    echo "🤖 $(date '+%H:%M:%S')"
    /usr/bin/env python3 src/qa_bot.py
} >> "$LOG" 2>&1
