#!/bin/bash
# Mac起動/ログイン時の catch-up
# - cron(10時 feedback / 22時 daily / 3時 backup)が
#   Macスリープ中で走らなかった場合に補完実行する
# - 既に当日のログが存在すればスキップ(冪等)

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

    # 10時を過ぎていて、今日のfeedbackログが無ければ実行
    if [ "$HOUR" -ge 10 ] && [ ! -f "$LOG_DIR/feedback_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ feedback未実行 → catch-up"
        bash "$PROJECT/scripts/run_feedback_sync.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ feedback OK ($HOUR時)"
    fi

    # 22時を過ぎていて、今日のdailyログが無ければ実行
    if [ "$HOUR" -ge 22 ] && [ ! -f "$LOG_DIR/daily_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ daily未実行 → catch-up"
        bash "$PROJECT/scripts/run_daily.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ daily OK ($HOUR時)"
    fi

    # 3時を過ぎていて、今日のbackupログが無ければ実行(任意)
    if [ "$HOUR" -ge 3 ] && [ ! -f "$LOG_DIR/backup_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ backup未実行 → catch-up"
        bash "$PROJECT/scripts/backup.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ backup OK"
    fi

    # qa_bot は5分ごとなのでcronで通常走るが、起動直後に1回走らせて
    # スリープ中に投稿された振り返りに即時反応させる
    echo "[$(date '+%H:%M:%S')] 🤖 qa_bot 起動時実行(振り返り即時キャッチ)"
    bash "$PROJECT/scripts/run_qa_bot.sh"

    echo "[$(date '+%H:%M:%S')] catch-up 完了"
    echo ""
} >> "$CATCHUP_LOG" 2>&1
