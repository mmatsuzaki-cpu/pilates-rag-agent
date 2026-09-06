#!/bin/bash
# Gemini APIのクレジット切れ見張り（毎日1回）
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
{
    echo "💳 $(date '+%Y-%m-%d %H:%M:%S')"
    /usr/bin/env python3 src/gemini_credit_watch.py
} >> "output/logs/gemini_credit_$(date +%Y-%m).log" 2>&1
