"""success_detector.py

振り返りDBから成功事例を検出して成功事例集DBに転記。
"""

import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import notion_headers

NOTION_API = "https://api.notion.com/v1"

SUCCESS_KW_CONTRACT = [
    r"契約[:：]\s*月\d+", r"契約[:：]\s*年\d+", r"月\d+\s*契約", r"年払い",
    r"年\d+\s*契約", r"トライアル\s*契約", r"ナイス契約", r"契約取れ", r"契約獲得",
    r"入会しました", r"戻り入会", r"カムバック",
]
SUCCESS_KW_GOOD = [r"今回の良かったこと", r"良かった事", r"良かった点",
                   r"BAで.*変化", r"効果出せ", r"喜んで"]
SUCCESS_KW_REFERRAL = [r"紹介で", r"ご紹介", r"友人.*体験"]


def fetch_archive_recent(days):
    archive_db_id = os.environ["NOTION_DATABASE_ID"]
    cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
    payload = {"filter": {"property": "日付", "date": {"on_or_after": cutoff}}, "page_size": 100}
    results = []
    cursor = None
    while True:
        if cursor: payload["start_cursor"] = cursor
        r = requests.post(f"{NOTION_API}/databases/{archive_db_id}/query",
                          headers=notion_headers(), json=payload, timeout=30)
        d = r.json()
        results.extend(d.get("results", []))
        if not d.get("has_more"): break
        cursor = d.get("next_cursor")
    return results


def get_existing_titles():
    success_db = os.environ["NOTION_SUCCESS_DB_ID"]
    titles = set()
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor: payload["start_cursor"] = cursor
        r = requests.post(f"{NOTION_API}/databases/{success_db}/query",
                          headers=notion_headers(), json=payload, timeout=30)
        d = r.json()
        for e in d.get("results", []):
            t = e.get("properties", {}).get("タイトル", {}).get("title", [])
            titles.add("".join([x.get("plain_text", "") for x in t]))
        if not d.get("has_more"): break
        cursor = d.get("next_cursor")
    return titles


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


def detect_types(text):
    types = []
    if any(re.search(p, text) for p in SUCCESS_KW_CONTRACT):
        types.append("クロージング成功")
    if "年払い" in text: types.append("年払い獲得")
    if "戻り入会" in text or "カムバック" in text: types.append("戻り入会")
    if any(re.search(p, text) for p in SUCCESS_KW_REFERRAL):
        types.append("紹介獲得")
    if "BA" in text and ("変化" in text or "効果" in text):
        types.append("体感出し成功")
    if "寄り添" in text: types.append("寄り添い成功")
    if any(k in text for k in ["他店比較", "比較"]) and "契約" in text:
        types.append("比較対応成功")
    return types or ["その他"]


def detect_course(text):
    for pat, label in [(r"年12", "年12"), (r"年6", "年6"), (r"年払い", "年払い"),
                       (r"月8", "月8"), (r"月4", "月4"), (r"月3", "月3"),
                       (r"月2", "月2"), (r"月1", "月1"), (r"トライアル", "トライアル")]:
        if re.search(pat, text):
            return label
    return ""


def add_success(archive_entry, content):
    success_db = os.environ["NOTION_SUCCESS_DB_ID"]
    p = archive_entry.get("properties", {})
    title = "".join([t.get("plain_text", "") for t in p.get("タイトル", {}).get("title", [])])
    url = archive_entry.get("url", "")
    date = p.get("日付", {}).get("date", {}).get("start") or datetime.now().date().isoformat()
    author = "".join([t.get("plain_text", "") for t in p.get("投稿者", {}).get("rich_text", [])])
    stores = [s["name"] for s in p.get("店舗", {}).get("multi_select", []) if s["name"] != "その他"]

    types = detect_types(content)
    course = detect_course(content)

    new_title = f"✨ {title[:80]}"
    properties = {
        "タイトル": {"title": [{"type": "text", "text": {"content": new_title}}]},
        "日付": {"date": {"start": date}},
        "店舗": {"multi_select": [{"name": s} for s in stores]},
        "成功タイプ": {"multi_select": [{"name": t} for t in types]},
        "担当者": {"rich_text": [{"type": "text", "text": {"content": author}}]},
    }
    if course:
        properties["契約コース"] = {"select": {"name": course}}
    if url:
        properties["元情報リンク"] = {"url": url}

    children = []
    chunks = [content[i:i+1900] for i in range(0, len(content), 1900)] or [""]
    for c in chunks:
        children.append({"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}})
    payload = {"parent": {"database_id": success_db}, "properties": properties, "children": children}
    r = requests.post(f"{NOTION_API}/pages", headers=notion_headers(), json=payload, timeout=20)
    return "id" in r.json()


def main():
    days = 7
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])

    print(f"🔍 過去{days}日の振り返りから成功事例検出")
    entries = fetch_archive_recent(days)
    print(f"  対象: {len(entries)}件")
    existing = get_existing_titles()
    print(f"  既存成功事例: {len(existing)}件")

    success = 0
    for entry in entries:
        p = entry.get("properties", {})
        title = "".join([t.get("plain_text", "") for t in p.get("タイトル", {}).get("title", [])])
        candidate = f"✨ {title[:80]}"
        if candidate in existing:
            continue
        seibetsu = p.get("種別", {}).get("select", {}) or {}
        if seibetsu.get("name") == "スレッド返信":
            continue
        content = fetch_page_text(entry["id"])
        if not content.strip(): continue

        has_success = (any(re.search(pp, content) for pp in SUCCESS_KW_CONTRACT) or
                       any(re.search(pp, content) for pp in SUCCESS_KW_GOOD) or
                       any(re.search(pp, content) for pp in SUCCESS_KW_REFERRAL))
        if not has_success: continue

        if add_success(entry, content):
            success += 1
            print(f"  ✅ {title[:50]}")

    print(f"\n✨ 成功事例追加: {success}件")
    print(success)
    return 0


if __name__ == "__main__":
    sys.exit(main())
