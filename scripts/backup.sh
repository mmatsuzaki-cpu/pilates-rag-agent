#!/bin/bash
# 毎日3:00 自動バックアップ
# - git auto-commit (config除く)
# - iCloud Drive へ rsync (認証情報含む完全コピー)

set -e
PROJECT_DIR="/Users/user/projects/pilates-rag-agent"
ICLOUD_BACKUP="/Users/user/Library/Mobile Documents/com~apple~CloudDocs/AIフォルダ/pilates-rag-agent-backup"
LOG="$PROJECT_DIR/output/logs/backup_$(date +%Y-%m-%d).log"
mkdir -p "$PROJECT_DIR/output/logs"

{
    echo "===================================="
    echo "🛡️ バックアップ開始: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "===================================="

    # 1. git auto-commit
    cd "$PROJECT_DIR"
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git -c user.email="bot@pilates-rag-agent.local" \
            -c user.name="pilates-rag-agent" \
            commit -m "Auto backup: $(date +%Y-%m-%d)" || true
        echo "  ✅ git commit"
    else
        echo "  ℹ️ git: 変更なし"
    fi

    # 2. iCloud Drive rsync (config含む全部)
    rsync -av --delete \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.git/objects' \
        "$PROJECT_DIR/" "$ICLOUD_BACKUP/" 2>&1 | tail -5
    echo "  ✅ iCloud rsync"

    # 3. 古いバックアップ削除(日付別tarballは7日保持)
    cd "$ICLOUD_BACKUP"
    DATESTAMP=$(date +%Y-%m-%d)
    tar czf "snapshot_$DATESTAMP.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='snapshot_*.tar.gz' . 2>/dev/null
    # 8日前以上のスナップショット削除
    find . -name "snapshot_*.tar.gz" -mtime +7 -delete 2>/dev/null
    echo "  ✅ snapshot tarball"

    echo ""
    echo "完了: $(date '+%H:%M:%S')"
} >> "$LOG" 2>&1
