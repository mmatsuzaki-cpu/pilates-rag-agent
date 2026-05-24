"""leader_fb_extractor.py

Slack #ピラティス_新規振り返り から「親メッセージ(振り返り) + スレッド返信(リーダーFB)」
ペアを抽出し、Notion「💎 リーダーFB事例集」DBに蓄積。

【設計方針】
- リーダー判定はしない:「親投稿者じゃない返信」を全てFB候補とみなす
- 親 = is_reflection(振り返り) を満たす投稿
- 返信 = 親投稿者と異なるユーザー / bot ID無し / 100文字以上 のもの
- 重複防止: data/leader_fb_state.json に処理済みtsを保存

【cron運用】
- 毎日10時の run_feedback_sync.sh から呼ばれる(slack_fetcher と並んで)
- 過去14日 lookback で漏れキャッチ
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
from common import slack_bot_token, notion_headers, PROJECT_ROOT
from qa_bot import is_reflection
from feedback_builder import (
    classify_barrier,
    extract_tags,
    extract_contract,
    extract_age,
    extract_job,
    extract_concerns,
    extract_staff_name,
)

SLACK_API = "https://slack.com/api"
NOTION_API = "https://api.notion.com/v1"

STATE_PATH = PROJECT_ROOT / "data" / "leader_fb_state.json"

# barrier コード → 日本語タグ名
BARRIER_TAG = {
    "other_store_compare": "他店比較",
    "take_home": "持ち帰り",
    "price_concern": "価格懸念",
    "time_concern": "時間懸念",
    "trial_only": "体験のみ",
}
TAG_TAG = {
    "housewife": "主婦",
    "postpartum": "産後",
    "desk_work": "デスクワーク",
    "standing_work": "立ち仕事",
    "chronic": "慢性悩み",
}

USER_CACHE = {}


def slack_get(method, params):
    r = requests.get(f"{SLACK_API}/{method}",
                     headers={"Authorization": f"Bearer {slack_bot_token()}"},
                     params=params, timeout=20)
    return r.json()


def fetch_user_name(user_id):
    if not user_id:
        return "(unknown)"
    if user_id in USER_CACHE:
        return USER_CACHE[user_id]
    d = slack_get("users.info", {"user": user_id})
    name = "(unknown)"
    if d.get("ok"):
        u = d["user"]
        name = u.get("real_name") or u.get("profile", {}).get("display_name") or u.get("name") or "(unknown)"
    USER_CACHE[user_id] = name
    return name


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"processed_ts": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_permalink(channel, ts):
    d = slack_get("chat.getPermalink", {"channel": channel, "message_ts": ts})
    return d.get("permalink") if d.get("ok") else None


def make_tags(parent_text):
    """親メッセージから barrier + 属性タグを抽出して Notion multi_select 用に変換"""
    tags = []
    b = classify_barrier(parent_text)
    if b in BARRIER_TAG:
        tags.append(BARRIER_TAG[b])
    for t in extract_tags(parent_text):
        if t in TAG_TAG:
            tags.append(TAG_TAG[t])
    return tags


def make_title(parent_text, dt):
    """タイトル: [MM/DD] スタッフ - 年齢/職業要約"""
    staff = extract_staff_name(parent_text) or "?"
    age = extract_age(parent_text)
    job = (extract_job(parent_text) or "")[:15]
    parts = []
    if age: parts.append(f"{age}歳")
    if job: parts.append(job)
    summary = " / ".join(parts) if parts else "情報少"
    return f"[{dt.strftime('%m/%d')}] {staff} - {summary}"


def add_to_notion(db_id, parent_text, reply_text, parent_dt, leader_name, staff_name, permalink, ts):
    """1件の リーダーFB を Notion DB に追加"""
    tags = make_tags(parent_text)
    title = make_title(parent_text, parent_dt)
    contract = extract_contract(parent_text)
    age = extract_age(parent_text)
    job = extract_job(parent_text) or ""
    concerns = extract_concerns(parent_text) or ""

    # 状況サマリー
    situation_parts = []
    if age: situation_parts.append(f"{age}歳")
    if job: situation_parts.append(job)
    if concerns: situation_parts.append(f"悩み: {concerns}")
    situation_text = " / ".join(situation_parts)[:1900]

    properties = {
        "タイトル": {"title": [{"text": {"content": title[:200]}}]},
        "タグ": {"multi_select": [{"name": t} for t in tags]},
        "状況": {"rich_text": [{"text": {"content": situation_text}}]},
        "FB本文": {"rich_text": [{"text": {"content": reply_text[:1900]}}]},
        "リーダー名": {"rich_text": [{"text": {"content": leader_name[:50]}}]},
        "スタッフ名": {"rich_text": [{"text": {"content": staff_name[:50]}}]},
        "契約結果": {"select": {"name": contract if contract in ("あり", "なし") else "不明"}},
        "日付": {"date": {"start": parent_dt.date().isoformat()}},
        "ts": {"rich_text": [{"text": {"content": ts}}]},
    }
    if permalink:
        properties["Slack_permalink"] = {"url": permalink}

    # 本文に FB全文 を入れる(rich_text 2000字制限超え対策)
    children = [{
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "📝"},
            "rich_text": [{"type": "text", "text": {"content": "【お客様の状況】"}}],
        }
    }]
    for chunk in [parent_text[i:i+1900] for i in range(0, len(parent_text), 1900)]:
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
        })
    children.append({
        "object": "block", "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💎"},
            "rich_text": [{"type": "text", "text": {"content": f"【{leader_name}さんのFB】"}}],
        }
    })
    for chunk in [reply_text[i:i+1900] for i in range(0, len(reply_text), 1900)]:
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}
        })

    payload = {"parent": {"database_id": db_id}, "properties": properties, "children": children}
    r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(), json=payload, timeout=20)
    return "id" in r.json()


def main():
    channel = os.environ["SLACK_FEEDBACK_CHANNEL_ID"]
    db_id = os.environ.get("NOTION_LEADER_FB_DB_ID")
    if not db_id:
        print("❌ NOTION_LEADER_FB_DB_ID 未設定")
        return 1

    state = load_state()
    processed = set(state.get("processed_ts", []))

    lookback_days = 14
    oldest = str(int(time.time() - lookback_days * 86400))  # 整数化必須(2026-05-24教訓)
    print(f"📥 Slack取得(過去{lookback_days}日 / 既処理={len(processed)})")

    # 親メッセージ取得
    data = slack_get("conversations.history",
                     {"channel": channel, "limit": 200, "oldest": oldest})
    if not data.get("ok"):
        print(f"❌ history: {data.get('error')}")
        return 1

    # 振り返り親のみ
    reflections = []
    for m in data.get("messages", []):
        if not m.get("user") or m.get("bot_id"):
            continue
        if m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
            continue
        if is_reflection(m.get("text", "")):
            reflections.append(m)

    print(f"  振り返り親: {len(reflections)}件")

    added = 0
    failed_ts = set()
    skipped = 0

    for parent in reflections:
        parent_ts = parent["ts"]
        parent_user = parent.get("user", "")
        parent_text = parent.get("text", "")
        parent_dt = datetime.fromtimestamp(float(parent_ts))

        # スレッド返信無ければスキップ
        if parent.get("reply_count", 0) < 1:
            continue

        # スレッド取得
        time.sleep(0.5)
        rep = slack_get("conversations.replies",
                        {"channel": channel, "ts": parent_ts, "limit": 200})
        if not rep.get("ok"):
            continue

        staff_name = fetch_user_name(parent_user)

        for r in rep.get("messages", []):
            r_ts = r.get("ts")
            r_user = r.get("user", "")
            r_text = (r.get("text") or "").strip()
            # 親本人 or bot or 親メッセージ自体 はスキップ
            if r_ts == parent_ts: continue
            if not r_user or r.get("bot_id"): continue
            if r_user == parent_user: continue  # 親本人の追記はFBじゃない
            # 短すぎる返信はスキップ(スタンプリプライ等)
            if len(r_text) < 30:
                skipped += 1
                continue
            # 既処理スキップ
            if r_ts in processed:
                continue

            time.sleep(0.5)
            leader_name = fetch_user_name(r_user)
            permalink = get_permalink(channel, r_ts)

            if add_to_notion(db_id, parent_text, r_text, parent_dt,
                             leader_name, staff_name, permalink, r_ts):
                added += 1
                processed.add(r_ts)
                print(f"  ✅ [{parent_dt.strftime('%m/%d')}] {staff_name} 振り返り ← {leader_name} FB ({len(r_text)}字)")
            else:
                failed_ts.add(r_ts)
                print(f"  ❌ Notion追加失敗: ts={r_ts}")
            time.sleep(0.3)

    state["processed_ts"] = list(processed)
    save_state(state)

    print(f"\n📊 結果: 追加={added}件 / 短い返信スキップ={skipped}件 / 失敗={len(failed_ts)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
