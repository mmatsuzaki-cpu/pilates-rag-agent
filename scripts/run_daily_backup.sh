#!/bin/bash
# Mac 22:00 JST daily 実績速報 (画像ダッシュボード)
#
# GitHub Actions の予約実行(daily.yml)は無料枠だと数時間遅延し、夜中〜未明に
# 着弾していたため、Mac の 22:00 起動を「主役」にする(2026-06-04)。
# GitHub Actions は遅延バックアップとして残す(Macがスリープ等で動けなかった日の保険)。
# alert_sender.py の冪等性チェック((N日時点)marker)で二重送信を防止。

cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/daily_$(date +%Y-%m-%d).log"

{
    echo "===================================="
    echo "🌙 Mac daily起動: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    /usr/bin/env python3 -u src/alert_sender.py
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
