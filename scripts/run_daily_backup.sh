#!/bin/bash
# Mac 22:00 JST daily 実績速報 (画像ダッシュボード)
#
# 主役は Mac の LaunchAgent。GitHub Actions(daily.yml) の schedule は遅延バックアップ。
# ⚠️ Mac が 22:00 にスリープから起きた直後は WiFi/DNS が復帰しきっておらず、
#    集計・送信が NameResolutionError で失敗することがある(2026-07-27 障害)。
#    → ネット疎通を待ってから実行し、caffeinate で実行中スリープを抑止する。
# ※ 22:00 に確実に起きるには pmset のスケジュール起動が別途必要:
#      sudo pmset repeat wake MTWRFSU 21:57:00   (毎日21:57に起動)
#      sudo pmset -a womp 1                        (ネットワークアクセスで起動)
#    かつ 夜間は電源接続しておくこと(バッテリー駆動だと起動しないことがある)。

cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
LOG="output/logs/daily_$(date +%Y-%m-%d).log"

{
    echo "===================================="
    echo "🌙 Mac daily起動: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="
    # ネット疎通待ち(最大120秒): slack.com が名前解決できる or 8.8.8.8 に到達するまで
    for i in $(seq 1 24); do
        if /usr/bin/nslookup slack.com >/dev/null 2>&1 || /sbin/ping -c1 -t3 8.8.8.8 >/dev/null 2>&1; then
            echo "[$(date '+%H:%M:%S')] ✅ ネット疎通OK (試行 $i)"
            break
        fi
        echo "[$(date '+%H:%M:%S')] ⏳ ネット未復帰、5秒待機 (試行 $i/24)"
        sleep 5
    done
    # caffeinate(-i)で実行中のアイドルスリープを抑止して daily を実行
    # ⚠️ 2026-10-22 夜に集計の途中(川越の読み込み)で固まり、72時間動きっぱなしになった。
    #    launchd は前の実行が終わるまで次を起動しないため 10/23〜25 が全部抜けた。
    #    → 30分で強制終了する(perl の alarm。macOS には timeout コマンドが無い)。
    /usr/bin/caffeinate -i /usr/bin/perl -e 'alarm shift; exec @ARGV or die' 1800 /usr/bin/env python3 -u src/alert_sender.py
    rc=$?
    [ $rc -eq 142 ] && echo "⏱️ 30分たっても終わらなかったので強制終了しました(次の起動でやり直し)"
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
