"""notify_after_sync.py - 振り返り蓄積完了通知

【2026-05-16 変更】 チャンネル投稿 → 松崎さん個人DM に戻す
- 送信先: SLACK_OWNER_USER_ID(松崎さん)宛のDM
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import slack_dm

PROJECT_ROOT = Path(__file__).parent.parent


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
    user_id = os.environ.get("SLACK_OWNER_USER_ID")
    if not user_id:
        print("❌ SLACK_OWNER_USER_ID が未設定")
        return 1

    today = datetime.now().date().isoformat()
    log = PROJECT_ROOT / "output" / "logs" / f"feedback_{today}.log"
    log_exists = log.exists()
    counts = parse_log(log)

    # ── Fail-safe: ログが無い場合は誤送信を防ぐため警告DMに切り替え ──
    # 過去バグ: GitHub Actionsのランナー間でファイル共有されず、ログが見つからず
    # 常に「本日の新規取り込みはありませんでした」を誤送信していた(〜2026-06-05)
    if not log_exists:
        warning = (
            "⚠️ *振り返り蓄積完了通知 - ログ取得失敗*\n"
            f"_{today} {datetime.now().strftime('%H:%M')}_\n\n"
            f"📁 期待したログ: `output/logs/feedback_{today}.log`\n"
            "🚨 ログファイルが見つからないため件数が確認できません。\n\n"
            "考えられる原因:\n"
            "・GitHub Actions の feedback.yml が失敗した\n"
            "・別ランナーで生成されたログが共有されていない\n"
            "・スクリプトのパス変更/権限問題\n\n"
            "→ feedback.yml のログ確認をお願いします。"
        )
        if slack_dm(user_id, warning):
            print(f"⚠️ ログ無し → 警告DM送信: log={log}")
            return 1
        print(f"❌ 警告DM送信も失敗: log={log}")
        return 1

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

    if slack_dm(user_id, "\n".join(lines)):
        print(f"✅ DM送信OK slack={counts['slack']} inbox={counts['inbox']} success={counts['success']}")
        return 0
    print("❌ DM送信失敗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
