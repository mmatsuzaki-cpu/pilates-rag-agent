"""qa_bot.py

Slack #ピラティス_新規振り返り にて:
1. メンション質問 (@ピラティス振り返りBot 〜) に返信
2. 振り返り投稿(年齢/悩み/契約 etc) を自動検知して先回り提示

Notionノウハウ集をキーワード検索 → 推奨アプローチを返信。
"""

import json
import os
import re
import sys
import time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import PROJECT_ROOT, slack_bot_token, slack_post_message, notion_headers

SLACK_API = "https://slack.com/api"
NOTION_API = "https://api.notion.com/v1"

STOPWORDS = {
    "の","に","を","は","が","と","で","も","や","から","まで","より","へ",
    "です","ます","した","して","する","される","ない","なし","ある","いる",
    "なる","こと","もの","ため","よう","そう","どう","この","その","あの",
    "対応","教えて","ください","お願い",
}


def is_reflection(text):
    if len(text) < 100: return False
    return "年齢" in text and ("悩み" in text or "契約" in text)


def split_text(text):
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    splitter = re.compile(
        r"(?:[\s、。,.\!\?！？「」『』【】()()・…\-=:;:;]+|"
        r"が|を|に|で|と|は|も|や|の|から|まで|より|へ|って|けど|ので|のに|たら|でも|ても|"
        r"します|です|ます|した|して|する|できる|なる|なった|ない|"
        r"どう|どの|なに|なん|対応|やり方|方法|教えて|お願い|ください)"
    )
    out = []
    seen = set()
    for t in splitter.split(text):
        if not t: continue
        t = t.strip()
        if not t or len(t) < 2 or t in STOPWORDS or t.isdigit() or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:10]


def extract_concerns(text):
    """振り返り投稿から悩みキーワード抽出"""
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    keywords = []
    seen = set()
    patterns = [r"悩み[\s::]*([^\n]+)", r"検討理由[\s::]*([^\n]+)",
                r"仕事[\s::]*([^\n]+)", r"理想[\s::]*([^\n]+)",
                r"既往歴[\s::]*([^\n]+)", r"次の新規で意識すること[\s::]*([^\n]+)"]
    splitter = re.compile(
        r"(?:[\s、。,.\!\?！？「」『』【】()()・…\-=:;:;]+|"
        r"が|を|に|で|と|は|も|や|の|から|まで|より|へ|って|けど|ので|のに|"
        r"します|です|ます|した|して|する|できる|なる|なった|ない|"
        r"どう|どの|なに|なん|対応|方法|教えて|お願い|ください)"
    )
    for pat in patterns:
        for m in re.finditer(pat, text):
            for t in splitter.split(m.group(1)):
                if not t: continue
                t = t.strip()
                if not t or len(t) < 2 or t in STOPWORDS or t.isdigit() or t in seen:
                    continue
                seen.add(t)
                keywords.append(t)
    return keywords[:8]


def query_db(db_id):
    results = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor: payload["start_cursor"] = cursor
        r = requests.post(f"{NOTION_API}/databases/{db_id}/query",
                          headers=notion_headers(), json=payload, timeout=30)
        d = r.json()
        if "results" not in d: break
        results.extend(d["results"])
        if not d.get("has_more"): break
        cursor = d.get("next_cursor")
    return results


def page_title(p):
    t = p.get("properties", {}).get("タイトル", {}).get("title", [])
    return "".join([x.get("plain_text", "") for x in t])


def page_keywords(p):
    pp = p.get("properties", {})
    kws = pp.get("キーワード", {}).get("multi_select", [])
    cats = pp.get("カテゴリ", {}).get("multi_select", [])
    return [k["name"] for k in kws] + [c["name"] for c in cats]


def score(p, keywords):
    title = page_title(p).lower()
    pkws = [k.lower() for k in page_keywords(p)]
    s = 0
    for kw in keywords:
        kl = kw.lower()
        if kl in title: s += 5
        for pk in pkws:
            if kl in pk or pk in kl:
                s += 3; break
    return s


def fetch_blocks(page_id):
    r = requests.get(f"{NOTION_API}/blocks/{page_id}/children?page_size=100",
                     headers=notion_headers(), timeout=15)
    return r.json().get("results", [])


def block_text(b):
    bt = b.get("type")
    rt = b.get(bt, {}).get("rich_text", [])
    return "".join([t.get("plain_text", "") for t in rt])


def extract_summary(page_id, max_bullets=3):
    blocks = fetch_blocks(page_id)
    situation = None
    approaches = []
    talk_example = None
    in_approach = False
    for b in blocks:
        bt = b.get("type")
        text = block_text(b)
        if bt == "callout" and situation is None:
            situation = text
        elif bt == "heading_2":
            in_approach = "推奨アプローチ" in text or "💡" in text
        elif bt == "bulleted_list_item" and in_approach and len(approaches) < max_bullets:
            approaches.append(text)
        elif bt == "quote" and talk_example is None:
            talk_example = text
    return {"situation": situation, "approaches": approaches, "talk_example": talk_example}


def search(db_id, keywords, top_n=3):
    pages = query_db(db_id)
    scored = [(score(p, keywords), p) for p in pages]
    scored = [(s, p) for s, p in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:top_n]]


def build_mention_reply(keywords, hits):
    lines = []
    lines.append(f"🔎 *キーワード*")
    lines.append(f"　{', '.join(keywords[:5]) if keywords else '(検出なし)'}")
    lines.append("")
    lines.append("")
    if hits:
        lines.append("━━━━━━━━━━━━━━")
        lines.append("📚 *ノウハウ集*")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("")
        for i, p in enumerate(hits, 1):
            title = page_title(p)
            url = p.get("url", "")
            lines.append(f"*{i}. {title}*")
            lines.append("")
            try:
                summary = extract_summary(p["id"], 3)
                if summary["situation"]:
                    lines.append("📌 *状況*")
                    lines.append(f"　_{summary['situation'][:140]}_")
                    lines.append("")
                if summary["approaches"]:
                    lines.append("💡 *推奨アプローチ*")
                    lines.append("")
                    for a in summary["approaches"]:
                        lines.append(f"　▸ {a[:140]}")
                        lines.append("")
                if summary["talk_example"]:
                    lines.append("🎯 *トーク例*")
                    lines.append(f"　「{summary['talk_example'][:140]}」")
                    lines.append("")
            except Exception:
                pass
            lines.append(f"<{url}|→ Notionで詳細を見る>")
            lines.append("")
            lines.append("")
    else:
        lines.append("⚠️ マッチする情報が見つかりませんでした。")
    return "\n".join(lines)


def build_auto_reply(keywords, hits):
    """振り返り検知時の自動返信
    方針: キーワード抽出 + 関連ノウハウへのリンク案内のみ
    (改善策の具体提示は廃止 → Notionのノウハウ集で確認してもらう)
    """
    lines = []
    lines.append("📝 *振り返りお疲れさまです!*")
    lines.append("")
    lines.append(f"🔎 *検出キーワード*")
    lines.append(f"　{', '.join(keywords[:5])}")
    lines.append("")
    if hits:
        lines.append("📚 *関連ノウハウ*")
        lines.append("")
        for i, p in enumerate(hits, 1):
            title = page_title(p)
            url = p.get("url", "")
            lines.append(f"　{i}. <{url}|{title}>")
        lines.append("")
        lines.append("詳しい改善策やトーク例は、Notionのノウハウ集をご確認ください💡")
    else:
        lines.append("該当するノウハウは見つかりませんでした。")
        lines.append("Notionのノウハウ集を直接ご確認ください📚")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━")
    lines.append("💬 個別に聞きたい時は `@ピラティス振り返りBot` でメンションしてね!")
    return "\n".join(lines)


def slack_get(method, params):
    r = requests.get(f"{SLACK_API}/{method}",
                     headers={"Authorization": f"Bearer {slack_bot_token()}"},
                     params=params, timeout=20)
    return r.json()


def main():
    channel = os.environ["SLACK_FEEDBACK_CHANNEL_ID"]
    knowledge_db = os.environ["NOTION_KNOWLEDGE_DB_ID"]

    state_path = PROJECT_ROOT / "data" / "qa_bot_state.json"
    if "--reset" in sys.argv:
        state_path.unlink(missing_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    replied = set(state.get("replied_ts", []))

    # Bot ID
    auth = slack_get("auth.test", {})
    if not auth.get("ok"):
        print(f"❌ {auth}"); return 1
    bot_id = auth.get("user_id")
    print(f"🤖 Bot ID: {bot_id}")

    # メッセージ取得
    data = slack_get("conversations.history", {"channel": channel, "limit": 50})
    if not data.get("ok"):
        print(f"❌ {data}"); return 1
    messages = data.get("messages", [])

    mention_pat = f"<@{bot_id}>"
    questions = []; reflections = []
    for m in messages:
        text = m.get("text", "")
        ts = m.get("ts", "")
        if not m.get("user") or m.get("bot_id"): continue
        if ts in replied: continue
        if mention_pat in text: questions.append(m)
        elif is_reflection(text): reflections.append(m)
    print(f"❓ メンション質問: {len(questions)}  📝 振り返り検知: {len(reflections)}")

    if not questions and not reflections:
        return 0

    success = 0
    # メンション処理
    for q in questions:
        text = q.get("text", "")
        ts = q.get("ts", "")
        kw = split_text(text)
        if not kw:
            reply = "⚠️ キーワードを抽出できませんでした"
        else:
            hits = search(knowledge_db, kw, 3)
            reply = build_mention_reply(kw, hits)
        res = slack_post_message(channel, reply, thread_ts=ts)
        if res.get("ok"):
            replied.add(ts); success += 1
            print(f"  ✅ 質問返信: {kw}")
        time.sleep(1)

    # 振り返り処理(hits無しでもキーワードのみで返信→ノウハウ集案内)
    for r in reflections:
        text = r.get("text", "")
        ts = r.get("ts", "")
        kw = extract_concerns(text)
        if not kw:
            replied.add(ts); continue
        hits = search(knowledge_db, kw, 3)
        reply = build_auto_reply(kw, hits)
        res = slack_post_message(channel, reply, thread_ts=ts)
        if res.get("ok"):
            replied.add(ts); success += 1
            print(f"  ✅ 振り返り検知: {kw} (hits={len(hits)})")
        else:
            print(f"  ❌ 投稿失敗: ts={ts} {res.get('error')}")
        time.sleep(1)

    state["replied_ts"] = list(replied)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 完了: {success}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
