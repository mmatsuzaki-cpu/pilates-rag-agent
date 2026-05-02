"""cleanup_bot_messages.py - Bot自身の返信を削除"""

import os
import sys
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import slack_bot_token

token = slack_bot_token()
channel = os.environ["SLACK_FEEDBACK_CHANNEL_ID"]

r = requests.post("https://slack.com/api/auth.test",
                  headers={"Authorization": f"Bearer {token}"}, timeout=10)
bot_id = r.json().get("user_id")
print(f"🤖 Bot ID: {bot_id}")

r = requests.get("https://slack.com/api/conversations.history",
                 headers={"Authorization": f"Bearer {token}"},
                 params={"channel": channel, "limit": 100}, timeout=15)
messages = r.json().get("messages", [])
deleted = 0
for m in messages:
    if m.get("user") == bot_id or m.get("bot_id"):
        d = requests.post("https://slack.com/api/chat.delete",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"channel": channel, "ts": m["ts"]}, timeout=10).json()
        if d.get("ok"): deleted += 1
        continue
    if m.get("reply_count", 0) > 0:
        rr = requests.get("https://slack.com/api/conversations.replies",
                          headers={"Authorization": f"Bearer {token}"},
                          params={"channel": channel, "ts": m["ts"]}, timeout=15)
        for rep in rr.json().get("messages", []):
            if rep.get("ts") == m["ts"]: continue
            if rep.get("user") == bot_id or rep.get("bot_id"):
                d = requests.post("https://slack.com/api/chat.delete",
                                  headers={"Authorization": f"Bearer {token}"},
                                  json={"channel": channel, "ts": rep["ts"]}, timeout=10).json()
                if d.get("ok"): deleted += 1
print(f"🧹 削除: {deleted}件")
