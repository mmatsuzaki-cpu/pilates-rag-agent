#!/bin/bash
# Mac起動/ログイン時の catch-up
# - cron(10時 feedback / 22時 daily / 3時 backup)が
#   Macスリープ中で走らなかった場合に補完実行する
# - 既に当日のログが存在すればスキップ(冪等)

PROJECT="/Users/user/projects/pilates-rag-agent"
LOG_DIR="$PROJECT/output/logs"
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d)
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

    # === 前日分の補完(昨夜Macがスリープしてた場合) ===
    # 昨日の feedback / daily が走っていなければ、今送る(冪等性あり)
    if [ ! -f "$LOG_DIR/feedback_${YESTERDAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ 昨日のfeedback未実行 → 補完"
        bash "$PROJECT/scripts/run_feedback_sync.sh"
        # 補完したら今日のログも作られる(同じスクリプト)→ 当日分は別チェック
    fi
    # daily(実績進捗) は当日22時のみ送る方針(2026-05-09)
    # → 昨日分の補完は廃止(翌朝14時等に過去日付の通知が届く現象を防ぐ)
    # dm_notify は当日22時のみ送る方針(2026-05-09)
    # → 昨日分の補完は廃止。スリープ等で22時に走らなかった日は通知なし

    # === 当日分(時刻が来ていれば実行) ===
    # 10時を過ぎていて、今日のfeedbackログが無ければ実行
    if [ "$HOUR" -ge 10 ] && [ ! -f "$LOG_DIR/feedback_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ 当日feedback未実行 → catch-up"
        bash "$PROJECT/scripts/run_feedback_sync.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ 当日feedback OK ($HOUR時)"
    fi

    # 22時を過ぎていて、今日のdailyログが無ければ実行
    if [ "$HOUR" -ge 22 ] && [ ! -f "$LOG_DIR/daily_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ 当日daily未実行 → catch-up"
        bash "$PROJECT/scripts/run_daily.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ 当日daily OK ($HOUR時)"
    fi

    # 22時を過ぎていて、今日のdm_notify_logが無ければ実行(当日内なら遅れて補完OK・2026-05-09)
    # ※ 翌日0時超えたら諦め(昨日分の補完は廃止のまま=朝に届くのを防ぐ)
    if [ "$HOUR" -ge 22 ] && [ ! -f "$LOG_DIR/dm_notify_${TODAY}.log" ]; then
        echo "[$(date '+%H:%M:%S')] ⏰ 当日dm_notify未実行 → catch-up"
        bash "$PROJECT/scripts/run_dm_notify.sh"
    else
        echo "[$(date '+%H:%M:%S')] ✓ 当日dm_notify OK ($HOUR時)"
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
