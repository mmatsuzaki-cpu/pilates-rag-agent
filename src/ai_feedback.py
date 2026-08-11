"""ai_feedback.py - 振り返り投稿への松崎メソッドAIフィードバック生成(ピラティス版)

Slack #ピラティス_新規振り返り のテキスト投稿に対して、Gemini で
松崎メソッド(7つの感/危機感/3ヶ月提案 等)に沿ったパーソナライズFBを生成する。

- 参考事例: Notion「💎 リーダーFB事例集」(leader_fb_extractor.py が毎日蓄積)を
  振り返りのキーワード・契約結果でスコアリングして上位を渡す
- 生成失敗時は None を返し、呼び出し側(qa_bot)がテンプレFBにフォールバックする
"""

import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import notion_headers

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def _brand() -> str:
    return os.environ.get("BRAND_NAME", "ラピラティス")


# ── 松崎メソッド(評価軸・ピラティス版) ────────────────

MATSUZAKI_PHILOSOPHY = """■ 根本思想
新規対応で大事なのは「入会＝信頼感」。お客様は効果ではなく
「この人なら任せてもいい」「自分の悩みを理解してくれている」
「このまま放置したらまずいから、ちゃんと始めよう」と思えた時に入会する。
体験レッスンは運動の時間ではなく「お客様に信頼してもらうための時間」。

■ 7つの感(信頼感を作るフレームワーク)
1.清潔感(身だしなみ・スタジオ環境) 2.安心感(声のトーン・運動初心者への配慮)
3.親近感(「この人わかってくれる」共感) 4.爽快感(レッスン後の体の軽さを一緒に言語化)
5.満足感(期待値超え) 6.達成感(できなかった動きができた体験)
7.危機感(最重要):「このまま何もしなかったら悪くなる」「今から何か始めた方がいい」

■ 危機感の伝え方(順番厳守)
悩みを聞く → 原因を一緒に考える → 体の仕組みを説明 →
放置した場合の未来を伝える → 「何かしら始めた方がいい」と伝える

■ 「{brand}じゃなくてもいい」テク(営業感を消す)
危機感とセットで「{brand}じゃなくても大丈夫」「整体やジムでもいい」
「何かしら始めた方がいい」と伝える → 売りたいだけじゃないと感じてもらう

■ 悩み+目的を聞く
悩みだけでなく「その悩みが改善されたら、その先どうなりたいか」の目的まで聞く。

■ 3ヶ月提案(クロージング鉄板)
「合うか合わないかは今日1回では判断できないので、一度3ヶ月だけ続けてみるのが良い。
3ヶ月続けて効果が微妙なら無理に続けなくて大丈夫。
まずは3ヶ月だけ、僕(私)に任せてもらえませんか?」

■ 入会特典の伝え方
最初から押さない。「やりたい」「任せたい」と思ってもらってから
最後にお得情報(入会キャンペーン等)として伝える。

■ 最低限意識すべき3つ
1.悩みの原因まで説明する 2.放置した場合の危機感を伝える
3.「{brand}じゃなくてもいいので何かしら始めた方がいい」と伝える"""


# ── リーダーFB事例の取得 ──────────────────────────────

def _clean_slack_noise(text: str) -> str:
    """Slack由来のノイズ(<@U...>メンション・:emoji:コード)を除去"""
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    text = re.sub(r":[a-z0-9_+-]+:", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plain(props: dict, name: str) -> str:
    p = props.get(name, {}) or {}
    if "rich_text" in p:
        return "".join(t.get("plain_text", "") for t in p.get("rich_text", []))
    if "title" in p:
        return "".join(t.get("plain_text", "") for t in p.get("title", []))
    if "select" in p:
        return (p.get("select") or {}).get("name", "")
    return ""


def fetch_leader_fb_examples(leader_fb_db: str, keywords: list,
                             contract: str = "", n: int = 4) -> str:
    """💎リーダーFB事例集から、振り返りキーワード一致 + 同じ契約結果を
    優先して上位 n 件を返す"""
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{leader_fb_db.replace('-', '')}/query",
            headers=notion_headers(),
            json={"page_size": 60,
                  "sorts": [{"timestamp": "created_time", "direction": "descending"}]},
            timeout=45,
        )
        if r.status_code != 200:
            return ""
        pages = r.json().get("results", [])
    except Exception:
        return ""

    entries = []
    for p in pages:
        props = p.get("properties", {})
        fb = _clean_slack_noise(_plain(props, "FB本文"))
        if not fb or len(fb) < 60:
            continue
        situation = _plain(props, "状況")
        tags = [t.get("name", "") for t in props.get("タグ", {}).get("multi_select", [])]
        c = _plain(props, "契約結果")
        # キーワード一致スコア(状況+タグに対して)
        haystack = situation + " ".join(tags)
        s = sum(1 for kw in (keywords or []) if kw and kw in haystack)
        entries.append({"score": s, "contract": c, "situation": situation, "fb": fb})

    # 並び順: キーワード一致 > 同じ契約結果 > 新しい順(取得順)
    same = 1 if contract in ("あり", "なし") else 0
    entries.sort(key=lambda e: (-e["score"], 0 if (same and e["contract"] == contract) else 1))

    blocks = []
    seen = set()
    for e in entries:
        key = e["fb"][:120]
        if key in seen:
            continue
        seen.add(key)
        head = f"契約結果={e['contract'] or '不明'}"
        if e["situation"]:
            head += f" / 状況={e['situation'][:80]}"
        blocks.append(f"◆ {head}\n  リーダーFB: {e['fb'][:400]}")
        if len(blocks) >= n:
            break
    return "\n\n".join(blocks)


# ── プロンプト ────────────────────────────────────────

FB_PROMPT_TEMPLATE = """あなたはピラティススタジオ「{brand}」の教育担当リーダー(松崎)として、
新人スタッフがSlackに投稿した新規体験レッスンの振り返りにフィードバックします。

【スタッフ名】{staff_name}
【契約結果】{contract_status}

【スタッフの振り返り投稿(原文)】
{reflection}

【リーダー(松崎・店舗リーダー)の過去FB事例】
{examples}

※ 事例の使い方: 今回の振り返りの悩み・検討理由・結果に近い事例だけを自分で選んで参考にし、
その着眼点・言い回しをFBに反映する(関係ない事例は無視、丸写しはしない)。

━━━━━━━━━━━━━━━━━━━━━━
【{brand}の新規対応哲学(評価の基準)】
{philosophy}
━━━━━━━━━━━━━━━━━━━━━━

【FBの書き方ルール(厳守)】
1. 出力はSlack投稿用のプレーンテキスト。見出しは *太字* (アスタリスク1個)、絵文字は適度に。
2. 構成は必ず次の3ブロックのみ:
   ✨ *良かった点*
   → 振り返りに書かれた実際の記述を「 」で1つ以上引用し、7つの感のどれが機能していたかを添えて2〜3行。
   🎯 *最重要改善ポイント(1つだけ)*
   → 今回一番効果が大きい改善を1つだけ選び、
     ▼今回の対応:「(振り返りの記述を引用)」
     ▼松崎メソッドならこう:「(お客様に実際に言うセリフ例)」
     の形で具体的に。危機感トーク/「{brand}じゃなくてもいい」/3ヶ月提案/悩みの目的深掘り/入会特典のタイミングのうち、不足していたものをここで扱う。
   📝 *次回に向けて*
   → その他の改善を最大2つ、各1行で簡潔に。
3. 引用は振り返りに実際に書かれている記述のみ。書かれていないことを引用として捏造しない。
   該当の記述がなければ「(振り返りに記載なし)」と書く。
4. 全体で400〜700字程度。あれもこれも指摘して総花的にしない。
5. 【契約結果】が「あり」の場合は、🎯ブロックは改善指摘ではなく必ず定着サポート視点
   (次回予約の固定化・目標設定・体験の感動が冷めないうちの継続導線)に切り替える。
   「なし」の場合のみ失注分析として改善ポイントを扱う。
6. 冒頭に「{staff_name}さん、新規対応お疲れ様でした!」等の労い1行はOK。
   それ以外の前置きや「以下がFBです」などの説明文は書かず、すぐ✨ブロックに入る。"""


# ── 生成本体 ──────────────────────────────────────────

def build_ai_feedback(reflection_text: str, staff_name: str,
                      keywords: list, leader_fb_db: str,
                      contract: str = "") -> str:
    """松崎メソッドAI FBを生成。失敗時は None(呼び出し側でテンプレFBへフォールバック)"""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not reflection_text:
        return None

    examples = ""
    if leader_fb_db:
        examples = fetch_leader_fb_examples(leader_fb_db, keywords, contract)
    if not examples:
        examples = "(事例なし: 哲学のみを基準にFBする)"

    brand = _brand()
    contract_status = contract if contract in ("あり", "なし") else "不明(投稿から読み取る)"
    prompt = FB_PROMPT_TEMPLATE.format(
        brand=brand,
        staff_name=staff_name,
        contract_status=contract_status,
        reflection=reflection_text[:6000],
        examples=examples[:4000],
        philosophy=MATSUZAKI_PHILOSOPHY.format(brand=brand),
    )

    r = requests.post(
        f"{GEMINI_URL}?key={api_key}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 4096,
                # gemini-2.5系は思考トークンが出力枠を消費するため無効化(出力切れ防止)
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=120,
    )
    if r.status_code != 200:
        print(f"  ⚠️ Gemini API {r.status_code}: {r.text[:200]}")
        return None
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        return None

    # ── 品質チェック(形式が崩れていたらテンプレFBに任せる) ──
    if len(text) < 100 or len(text) > 4000:
        return None
    if "🎯" not in text:
        return None
    # マークダウン**をSlack mrkdwn *に矯正
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    return text
