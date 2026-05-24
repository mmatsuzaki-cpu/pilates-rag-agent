"""slack_fetcher.py

Slack #ピラティス_新規振り返り から新規メッセージ + スレッド返信を取得し、
Notion振り返りDBに追加する。
processed_ts による重複防止 + 過去14日のlookbackで追加FB漏れも捕捉。
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    PROJECT_ROOT, slack_bot_token, notion_headers,
)

SLACK_API = "https://slack.com/api"
NOTION_API = "https://api.notion.com/v1"

# 店舗・カテゴリ自動分類キーワード
STORE_KEYWORDS = {
    "川越": ["川越"],
    "大宮": ["大宮"],
    "高崎": ["高崎"],
    "神戸元町": ["神戸元町", "元町", "神戸"],
    "西宮北口": ["西宮北口", "西北", "西宮"],
}
CATEGORY_KEYWORDS = {
    "売上": ["売上", "売り上げ"],
    "利益": ["利益", "粗利"],
    "契約率": ["契約率", "成約", "クロージング", "新規契約", "契約", "入会", "月払い", "年払い",
            "提案", "押し", "目標", "現状", "問題点", "危機感", "後追い", "戻り入会"],
    "解約率": ["解約", "退会", "やめる", "辞めた", "離脱", "休会"],
    "集客": ["集客", "体験", "予約", "ご新規", "新規対応", "他店", "他店舗", "比較", "比較中",
           "グループ", "パーソナル", "ヨガ", "ジム", "通いやすさ", "金銭面", "料金", "高い"],
    "スタッフ": ["スタッフ", "ロープレ", "研修", "教育", "シフト", "面談", "FB", "フィードバック"],
    "口コミ": ["口コミ", "レビュー", "Google", "ホットペッパー", "HPB"],
}


def detect_stores(text):
    found = [k for k, kws in STORE_KEYWORDS.items() if any(kw in text for kw in kws)]
    return found if found else ["その他"]


def detect_categories(text):
    found = [k for k, kws in CATEGORY_KEYWORDS.items() if any(kw in text for kw in kws)]
    return found if found else ["その他"]


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def slack_get(method, params):
    r = requests.get(f"{SLACK_API}/{method}",
                     headers={"Authorization": f"Bearer {slack_bot_token()}"},
                     params=params, timeout=20)
    return r.json()


def fetch_user_name(user_id, cache):
    if user_id in cache:
        return cache[user_id]
    data = slack_get("users.info", {"user": user_id})
    if data.get("ok"):
        u = data.get("user", {})
        prof = u.get("profile", {})
        name = prof.get("display_name") or prof.get("real_name") or u.get("name") or user_id
        cache[user_id] = name
        return name
    cache[user_id] = user_id
    return user_id


def resolve_mentions(text, user_cache):
    if not text: return ""
    return re.sub(r"<@(U[A-Z0-9]+)>",
                  lambda m: f"@{fetch_user_name(m.group(1), user_cache)}",
                  text)


def add_to_notion(msg_dict):
    """振り返りDBにページ追加"""
    db_id = os.environ["NOTION_DATABASE_ID"]
    text = msg_dict["text"] or ""
    user_name = msg_dict["user_name"]
    dt_iso = msg_dict["datetime"]
    permalink = msg_dict.get("permalink")
    is_reply = msg_dict.get("is_reply", False)

    stores = detect_stores(text)
    categories = detect_categories(text)
    body_preview = re.sub(r"\s+", " ", text)[:50]
    # わかりやすいタイトル: 💭 悩み | 店舗 スタッフ | 日付 [結果]
    from title_builder import make_friendly_title
    if is_reply:
        title_text = f"🧵 {user_name}: {body_preview[:60]}"
    else:
        # 「悩み」「結果」抽出
        concern = ""
        m = re.search(r"悩み[:：\s]+([^\n]+)", text)
        if m: concern = m.group(1)[:60]
        result = ""
        m = re.search(r"(?:契約|結果)[:：\s]+([^\n]+)", text)
        if m:
            res_raw = m.group(1)[:20]
            if "あり" in res_raw: result = "契約あり"
            elif "なし" in res_raw: result = "契約なし"
            else: result = res_raw[:6]
        title_text = make_friendly_title(
            concern=concern,
            store=stores[0] if stores else "",
            staff=user_name,
            date=dt_iso[:10],
            result=result,
            fallback=body_preview,
        )

    properties = {
        "タイトル": {"title": [{"type": "text", "text": {"content": title_text[:200]}}]},
        "日付": {"date": {"start": dt_iso}},
        "店舗": {"multi_select": [{"name": s} for s in stores]},
        "カテゴリ": {"multi_select": [{"name": c} for c in categories]},
        "投稿者": {"rich_text": [{"type": "text", "text": {"content": user_name}}]},
        "種別": {"select": {"name": "スレッド返信" if is_reply else "親メッセージ"}},
    }
    if permalink:
        properties["Slackリンク"] = {"url": permalink}

    children = []
    if msg_dict.get("parent_text"):
        children.append({
            "object": "block", "type": "callout",
            "callout": {
                "icon": {"type": "emoji", "emoji": "🧵"},
                "rich_text": [{"type": "text", "text": {"content": f"親メッセージ: {msg_dict['parent_text']}"}}],
                "color": "gray_background",
            },
        })
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)] or [""]
    for chunk in chunks:
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })

    payload = {"parent": {"database_id": db_id}, "properties": properties, "children": children}
    r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(), json=payload, timeout=20)
    return "id" in r.json()


def main():
    channel = os.environ["SLACK_FEEDBACK_CHANNEL_ID"]
    state_path = PROJECT_ROOT / "data" / "slack_state.json"
    state = load_state(state_path)
    processed_ts = set(state.get("processed_ts", []))

    lookback_days = 14
    # ⚠️ Slack API は oldest が float(小数点付)だと 0件返す → 整数化必須
    # (2026-05-24 発覚: str(time.time()) の小数点でフィルタが効かなかった)
    oldest = str(int(time.time() - lookback_days * 86400))
    print(f"📥 Slack取得(過去{lookback_days}日 / 既処理={len(processed_ts)})")

    data = slack_get("conversations.history", {"channel": channel, "limit": 200, "oldest": oldest})
    if not data.get("ok"):
        print(f"❌ {data.get('error')}")
        return 1
    messages = [m for m in data.get("messages", [])
                if m.get("type") == "message" and not m.get("bot_id")
                and m.get("subtype") not in ("channel_join", "channel_leave", "bot_message")]
    print(f"  対象: {len(messages)}件(処理前)")

    user_cache = {}
    new_results = []

    for m in messages:
        ts = m.get("ts")
        # 親メッセージ
        if ts not in processed_ts:
            user_id = m.get("user", "")
            text = m.get("text", "")
            if text:
                dt = datetime.fromtimestamp(float(ts))
                permalink_data = slack_get("chat.getPermalink", {"channel": channel, "message_ts": ts})
                permalink = permalink_data.get("permalink") if permalink_data.get("ok") else None
                user_name = fetch_user_name(user_id, user_cache) if user_id else "(unknown)"
                msg = {
                    "ts": ts, "datetime": dt.isoformat(),
                    "datetime_str": dt.strftime("%Y-%m-%d %H:%M"),
                    "user_id": user_id, "user_name": user_name,
                    "text": resolve_mentions(text, user_cache),
                    "permalink": permalink, "thread_ts": m.get("thread_ts"),
                    "is_reply": False, "parent_text": None,
                }
                new_results.append(msg)
            processed_ts.add(ts)

        # スレッド返信(親が処理済みでも返信は新規可能性あり)
        if m.get("reply_count", 0) > 0:
            replies_data = slack_get("conversations.replies", {"channel": channel, "ts": ts, "limit": 200})
            if replies_data.get("ok"):
                parent_text_for_reply = resolve_mentions(m.get("text", "")[:100], user_cache)
                for r in replies_data.get("messages", []):
                    r_ts = r.get("ts")
                    if r_ts in processed_ts: continue
                    if r.get("bot_id"):
                        processed_ts.add(r_ts); continue
                    r_user = r.get("user", "")
                    r_text = r.get("text", "")
                    if not r_text: continue
                    r_dt = datetime.fromtimestamp(float(r_ts))
                    pl_data = slack_get("chat.getPermalink", {"channel": channel, "message_ts": r_ts})
                    r_permalink = pl_data.get("permalink") if pl_data.get("ok") else None
                    r_user_name = fetch_user_name(r_user, user_cache) if r_user else "(unknown)"
                    new_results.append({
                        "ts": r_ts, "datetime": r_dt.isoformat(),
                        "datetime_str": r_dt.strftime("%Y-%m-%d %H:%M"),
                        "user_id": r_user, "user_name": r_user_name,
                        "text": resolve_mentions(r_text, user_cache),
                        "permalink": r_permalink, "thread_ts": ts,
                        "is_reply": True, "parent_text": parent_text_for_reply,
                    })
                    processed_ts.add(r_ts)
                    time.sleep(0.3)
            time.sleep(0.3)

    if not new_results:
        print("ℹ️ 新規なし")
        save_state(state_path, {"processed_ts": list(processed_ts)})
        return 0

    print(f"  📝 Notion追加対象: {len(new_results)}件")
    success = 0
    failed_ts = set()
    for msg in new_results:
        if add_to_notion(msg):
            success += 1
        else:
            failed_ts.add(msg["ts"])
            print(f"    ⚠️ Notion追加失敗: ts={msg['ts']} ({msg.get('datetime_str')})")
        time.sleep(0.3)
    print(f"  ✅ 追加: {success}/{len(new_results)}件")

    # 失敗したtsはprocessed_tsから外す→次回再試行(冪等性確保)
    if failed_ts:
        processed_ts = processed_ts - failed_ts
        print(f"  🔄 失敗{len(failed_ts)}件をprocessed_tsから除外(次回再試行)")

    save_state(state_path, {"processed_ts": list(processed_ts)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
