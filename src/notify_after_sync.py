"""notify_after_sync.py - 振り返り蓄積完了通知

【2026-05-07 変更】 松崎さん個人DM → #ピラティス_新規振り返り (C0B0L805YKT) チャンネル投稿に切替
- 環境変数 NOTIFY_AFTER_SYNC_CHANNEL_ID で送信先を上書き可能
- なければ SLACK_FEEDBACK_CHANNEL_ID(振り返り投稿チャンネル)に送信
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import slack_post_message

PROJECT_ROOT = Path(__file__).parent.parent

# デフォルト通知先 = #ピラティス_新規振り返り
DEFAULT_NOTIFY_CHANNEL = "C0B0L805YKT"


def parse_log(log_path):
    if not log_path.exists():
        return {"slack": 0, "inbox": 0, "success": 0}
    content = log_path.read_text(encoding="utf-8")
    slack = 0
    m = re.search(r"追加:\s*(\d+)/", content)
    if m: slack = int(m.group(1))
    inbox = 0
    m = re.search(r"処理待ち:\s*(\d+)件", content)
    if m: inbox = int(m.group(1))
    success = 0
    m = re.search(r"成功事例追加:\s*(\d+)件", content)
    if m: success = int(m.group(1))
    return {"slack": slack, "inbox": inbox, "success": success}


def main():
    # 通知先チャンネル(環境変数で上書き可能)
    channel = os.environ.get("NOTIFY_AFTER_SYNC_CHANNEL_ID") or DEFAULT_NOTIFY_CHANNEL

    today = datetime.now().date().isoformat()
    log = PROJECT_ROOT / "output" / "logs" / f"feedback_{today}.log"
    counts = parse_log(log)

    archive_id = os.environ.get("NOTION_DATABASE_ID", "").replace("-", "")
    success_id = os.environ.get("NOTION_SUCCESS_DB_ID", "").replace("-", "")
    script_id = os.environ.get("NOTION_SCRIPT_DB_ID", "").replace("-", "")

    total = counts["slack"] + counts["inbox"] + counts["success"]

    lines = [
        "📩 *振り返り蓄積完了*",
        f"_{today} {datetime.now().strftime('%H:%M')}_",
        "",
    ]
    if total == 0:
        lines.append("ℹ️ 本日の新規取り込みはありませんでした")
    else:
        lines.append(f"✅ Slack振り返り取得: *{counts['slack']}件*")
        lines.append(f"✅ LINE/個別FB処理: *{counts['inbox']}件*")
        lines.append(f"✨ 成功事例検出: *{counts['success']}件*")
    lines.append("")
    lines.append("━━━━━━━━━━")
    lines.append(f"📊 <https://www.notion.so/{archive_id}|振り返りDB(全件)を見る>")
    lines.append(f"✨ <https://www.notion.so/{success_id}|成功事例集を見る>")
    lines.append(f"💬 <https://www.notion.so/{script_id}|トークスクリプト集を見る>")

    res = slack_post_message(channel, "\n".join(lines))
    if res.get("ok"):
        print(f"✅ チャンネル送信OK ({channel}) slack={counts['slack']} inbox={counts['inbox']} success={counts['success']}")
        return 0
    print(f"❌ チャンネル送信失敗: {res.get('error', res)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
