#!/bin/bash
# Mac起動/ログイン時の catch-up(2026-05-25 縮小: GitHub Actions移行後)
# - daily / feedback / dm_notify / monthly は GitHub Actions が確実に動かす(catch-upしない)
# - backup と qa_bot だけ Mac local 継続(catch-up対象)

PROJECT="/Users/user/projects/pilates-rag-agent"
LOG_DIR="$PROJECT/output/logs"
TODAY=$(date +%Y-%m-%d)
HOUR=$(date +%H)
NOW=$(date '+%Y-%m-%d %H:%M:%S')

mkdir -p "$LOG_DIR"
CATCHUP_LOG="$LOG_DIR/startup_catchup.log"

{
    echo "===================================="
    echo "🔄 catch-up起動: $NOW"
    echo "===================================="

    # 起動直後はネットワーク等が落ち着くまで少し待つ
    sleep 30

    # === daily / feedback / dm_notify / monthly は GitHub Actions に移行 (2026-05-25) ===
    # → Mac起動状態に関係なく確実に動くので catch-up 不要
    echo "[$(date '+%H:%M:%S')] ℹ️ daily / feedback / dm_notify / monthly は GitHub Actions が処理"

    # 3時を過ぎていて、今日のbackupログが無ければ実行
    if [ "$HOUR" -ge 3 ] && [ ! -f "$LOG_DIR/backup_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ backup未実行 → catch-up"
        bash "$PROJECT/scripts/backup.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ backup OK"
    fi

    # qa_bot 起動直後に1回(スリープ中に投稿された振り返りに即時反応)
    echo "[$(date '+%H:%M:%S')] 🤖 qa_bot 起動時実行(振り返り即時キャッチ)"
    bash "$PROJECT/scripts/run_qa_bot.sh"

    echo "[$(date '+%H:%M:%S')] catch-up 完了"
    echo ""
} >> "$CATCHUP_LOG" 2>&1
