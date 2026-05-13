#!/bin/bash
# 毎日10:00 振り返り全自動処理
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/feedback_$(date +%Y-%m-%d).log"
{
    echo "===================================="
    echo "📥 feedback $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    echo ""
    echo "📨 [1/4] Slack→Notion同期"
    /usr/bin/env python3 src/slack_fetcher.py
    echo ""
    echo "📥 [2/4] 受信箱処理"
    /usr/bin/env python3 src/inbox_processor.py
    echo ""
    echo "✨ [3/4] 成功事例検出"
    /usr/bin/env python3 src/success_detector.py --days 7
    echo ""
    echo "⭐ [4/6] 口コミ取得(Google + HPB)"
    /usr/bin/env python3 src/reviews_fetcher.py
    echo ""
    echo "📊 [5/6] 新スプシ「ピラティス実績全部」更新(契約率/解約率/口コミ)"
    /usr/bin/env python3 src/full_dashboard_updater.py --daily
    echo ""
    echo "👥 [6/6] 解約集計_スタッフ別 更新(月降順・店舗色分け)"
    /usr/bin/env python3 src/cancel_staff_aggregator.py
    echo ""
    # DM通知は別cron(22時 / scripts/run_dm_notify.sh)に分離(2026-05-04)
    echo ""
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
