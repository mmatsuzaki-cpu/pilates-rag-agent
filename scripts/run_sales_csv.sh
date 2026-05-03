#!/bin/bash
# 5分ごとに走り、~/Downloads/ に置かれた店舗CSVを検出 → スプシ反映 → Slack速報
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/sales_csv_$(date +%Y-%m-%d).log"
{
    /usr/bin/env python3 src/sales_csv_loader.py
} >> "$LOG" 2>&1
