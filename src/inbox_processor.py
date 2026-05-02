"""inbox_processor.py

Notion 受信箱DB(LINE/個別FB貼付け用)から「処理待ち」を取得し、
店舗・カテゴリを自動分類して振り返りDBに転記する。
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import notion_headers
from slack_fetcher import detect_stores, detect_categories

NOTION_API = "https://api.notion.com/v1"


def fetch_pending(inbox_db_id):
    payload = {"filter": {"property": "処理状態", "select": {"equals": "🟡 処理待ち"}}, "page_size": 100}
    r = requests.post(f"{NOTION_API}/databases/{inbox_db_id}/query",
                      headers=notion_headers(), json=payload, timeout=30)
    return r.json().get("results", [])


def fetch_page_text(page_id):
    r = requests.get(f"{NOTION_API}/blocks/{page_id}/children?page_size=100",
                     headers=notion_headers(), timeout=20)
    parts = []
    for b in r.json().get("results", []):
        bt = b.get("type")
        rt = b.get(bt, {}).get("rich_text", [])
        text = "".join([t.get("plain_text", "") for t in rt])
        if text: parts.append(text)
    return "\n".join(parts)


def get_props(entry):
    p = entry.get("properties", {})
    title_blocks = p.get("タイトル", {}).get("title", [])
    title = "".join([t.get("plain_text", "") for t in title_blocks]) or "(無題)"
    auth_blocks = p.get("投稿者", {}).get("rich_text", [])
    author = "".join([t.get("plain_text", "") for t in auth_blocks]) or "(unknown)"
    date_obj = p.get("日付", {}).get("date") or {}
    date_str = date_obj.get("start") or datetime.now().date().isoformat()
    return {"title": title, "author": author, "date": date_str}


def add_to_archive(meta, content, stores, categories):
    archive_db_id = os.environ["NOTION_DATABASE_ID"]
    body_preview = re.sub(r"\s+", " ", content)[:50]
    title_text = f"📥 [{meta['date'][:10]}] {meta['author']}: {body_preview}"
    properties = {
        "タイトル": {"title": [{"type": "text", "text": {"content": title_text[:200]}}]},
        "日付": {"date": {"start": meta["date"]}},
        "店舗": {"multi_select": [{"name": s} for s in stores]},
        "カテゴリ": {"multi_select": [{"name": c} for c in categories]},
        "投稿者": {"rich_text": [{"type": "text", "text": {"content": meta["author"]}}]},
        "種別": {"select": {"name": "親メッセージ"}},
    }
    children = []
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)] or [""]
    for c in chunks:
        children.append({"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}})
    payload = {"parent": {"database_id": archive_db_id}, "properties": properties, "children": children}
    r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(), json=payload, timeout=20)
    return "id" in r.json()


def mark_processed(page_id, stores, categories):
    payload = {"properties": {
        "処理状態": {"select": {"name": "✅ 処理済み"}},
        "検出店舗": {"multi_select": [{"name": s} for s in stores if s != "その他"]},
        "検出カテゴリ": {"multi_select": [{"name": c} for c in categories]},
    }}
    r = requests.patch(f"{NOTION_API}/pages/{page_id}",
                       headers=notion_headers(), json=payload, timeout=20)
    return r.status_code == 200


def main():
    inbox_db = os.environ.get("NOTION_INBOX_DB_ID")
    if not inbox_db:
        print("❌ NOTION_INBOX_DB_ID未設定"); return 1

    pending = fetch_pending(inbox_db)
    if not pending:
        print("ℹ️ 処理待ちなし"); return 0

    print(f"📥 処理待ち: {len(pending)}件")
    success = 0
    for entry in pending:
        meta = get_props(entry)
        page_id = entry["id"]
        content = fetch_page_text(page_id)
        if not content.strip():
            print(f"  ⚠️ 本文なし: {meta['title']}")
            continue
        stores = detect_stores(content)
        categories = detect_categories(content)
        if add_to_archive(meta, content, stores, categories):
            if mark_processed(page_id, stores, categories):
                success += 1
                print(f"  ✅ {meta['title'][:50]} → {stores}/{categories}")
    print(f"\n✅ 完了: {success}/{len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
