"""coaching_analyzer.py - 録音 → 文字起こし → AI評価 → FB生成

【処理フロー】
1. アップロードされた音声を一時保存
2. faster-whisper でローカル文字起こし(オープンソース・無料)
3. Gemini Flash で4項目評価(ヒアリング/提案/クロージング/トーン)+ LINE文面生成
4. Slack(本人DM + チャンネル + 松崎完了通知)+ Notion保存
5. 一時音声ファイルを削除(個人情報保護)

【依存ライブラリ】
- faster-whisper: 軽量Whisper(モデル "tiny" or "base")
- google-generativeai: Gemini Flash API
"""

import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 既存モジュール流用(リーダーFB事例・ノウハウ集の参照)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 環境変数読み込み(Streamlit Cloud では st.secrets、ローカルでは .env)
try:
    import streamlit as st
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = st.secrets.get("NOTION_LEADER_FB_DB_ID", "")
    SLACK_BOT_TOKEN = st.secrets.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = st.secrets.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B0L805YKT")
    SLACK_OWNER_USER_ID = st.secrets.get("SLACK_OWNER_USER_ID", "")
except Exception:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = os.environ.get("NOTION_LEADER_FB_DB_ID", "")
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = os.environ.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B0L805YKT")
    SLACK_OWNER_USER_ID = os.environ.get("SLACK_OWNER_USER_ID", "")


# ── 1. 文字起こし(faster-whisper) ────────────────

def transcribe_audio(audio_path: str) -> str:
    """faster-whisper で音声を文字起こし
    モデルは "base"(74MB、日本語OK、Streamlit Cloud 1GBメモリで動く)
    """
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, language="ja", vad_filter=True)
    text = "".join(seg.text for seg in segments)
    return text.strip()


# ── 2. AI評価 + FB生成(Gemini Flash) ──────────────

EVAL_PROMPT_TEMPLATE = """あなたはピラティススタジオ「KOSHIKI × La pilates」の教育担当として、新人スタッフのカウンセリング録音を評価します。

【スタッフ名】 {staff_name}
【セッション日】 {session_date}
【契約結果】 {contract_status}
【コース】 {course_label}
【メモ】 {notes}

【カウンセリング録音(文字起こし)】
{transcript}

【参考にするリーダーFB事例集(過去類似ケース)】
{leader_fb_examples}

【評価項目(各1〜5の★スコア)】
1. ヒアリング: お客様のお悩み・背景を深掘りできているか
2. 提案: 姿勢分析・整体・パーソナルワークの価値訴求は的確か
3. クロージング: 契約決断のサポート、不安解消、期限提示
4. トーン: 寄り添い方、話し方、聞きやすさ

【FB視点の使い分け】
- 契約「あり」の場合 → 「定着サポート視点」(継続モチベ・次回ゴール・効果実感の引き出し方)
- 契約「なし」の場合 → 「失注分析視点」(何が決め手にならなかったか、次回どう改善するか)

【出力形式(JSON厳守)】
{{
  "scores": {{"hearing": <int>, "proposal": <int>, "closing": <int>, "tone": <int>}},
  "good_points": "<良かったポイントを具体的に3つ箇条書き(マークダウン)>",
  "improvements": "<改善点を具体的に2つ箇条書き(マークダウン)>",
  "line_message": "<スタッフ本人に送るLINE文面。冒頭「○○さんお疲れさまです😊」で始める。契約あり=入会お祝い+定着サポート視点、契約なし=次に活かす視点で励ます。300字程度>"
}}

JSONのみ出力。コメントや説明は不要。
"""


def fetch_leader_fb_examples(transcript: str, n: int = 3) -> str:
    """Notion リーダーFB事例集から類似ケースを取得して要約"""
    if not NOTION_TOKEN or not NOTION_LEADER_FB_DB_ID:
        return "(リーダーFB事例なし)"
    try:
        import requests
        H = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_LEADER_FB_DB_ID.replace('-', '')}/query",
            headers=H,
            json={"page_size": n, "sorts": [{"timestamp": "created_time", "direction": "descending"}]},
        )
        examples = []
        for p in r.json().get("results", [])[:n]:
            props = p.get("properties", {})
            situation = "".join([t.get("plain_text", "") for t in props.get("状況", {}).get("rich_text", [])])
            fb = "".join([t.get("plain_text", "") for t in props.get("FB本文", {}).get("rich_text", [])])
            if situation or fb:
                examples.append(f"・状況: {situation[:100]}\n  FB: {fb[:200]}")
        return "\n\n".join(examples) if examples else "(類似事例なし)"
    except Exception as e:
        return f"(取得失敗: {e})"


def call_gemini(transcript: str, staff_name: str, session_date, notes: str,
                contract: str = "なし", course: str = "未契約") -> dict:
    """Gemini Flash で評価生成"""
    import google.generativeai as genai
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    leader_fb = fetch_leader_fb_examples(transcript)
    contract_status = f"🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if contract == "あり" else "(未契約)"
    prompt = EVAL_PROMPT_TEMPLATE.format(
        staff_name=staff_name,
        session_date=session_date,
        contract_status=contract_status,
        course_label=course_label,
        notes=notes or "(なし)",
        transcript=transcript[:8000],  # 長すぎる場合カット
        leader_fb_examples=leader_fb,
    )

    response = model.generate_content(prompt)
    text = response.text.strip()
    # ```json ... ``` で囲まれている場合は外す
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini JSON parse失敗: {e}\nresponse: {text[:500]}")


# ── 3. Slack通知 ──────────────────────────────────

def send_slack_notifications(staff_name: str, session_date, result: dict):
    """Slack に3種類の通知:
    ① 本人DM(スタッフ名から探す or 松崎さんDMにフォワード)
    ② #ピラティス_新規振り返り チャンネル投稿(全員見れる)
    ③ 松崎さん完了通知DM
    """
    import requests
    if not SLACK_BOT_TOKEN:
        return
    H = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json; charset=utf-8"}

    scores = result.get("scores", {})
    avg = sum(scores.values()) / max(len(scores), 1)
    star_line = f"ヒアリング★{scores.get('hearing',0)} / 提案★{scores.get('proposal',0)} / クロージング★{scores.get('closing',0)} / トーン★{scores.get('tone',0)}"

    # 契約結果の表示
    contract = result.get("contract", "なし")
    course = result.get("course", "未契約")
    if contract == "あり":
        contract_line = f"🎉 *契約獲得* ({course})"
    else:
        contract_line = "🥲 契約なし"

    # ② チャンネル投稿
    channel_msg = (
        f"🎤 *育成FB完了*: {staff_name} さん({session_date})\n"
        f"{contract_line}\n\n"
        f"📊 平均★{avg:.1f}/5\n"
        f"{star_line}\n\n"
        f"💎 *良かった点*\n{result.get('good_points', '')}\n\n"
        f"🎯 *改善点*\n{result.get('improvements', '')}"
    )
    requests.post("https://slack.com/api/chat.postMessage", headers=H,
                  json={"channel": SLACK_FEEDBACK_CHANNEL_ID, "text": channel_msg})

    # ③ 松崎さん完了DM
    if SLACK_OWNER_USER_ID:
        dm_open = requests.post("https://slack.com/api/conversations.open",
                                headers=H, json={"users": SLACK_OWNER_USER_ID}).json()
        if dm_open.get("ok"):
            dm_id = dm_open["channel"]["id"]
            requests.post("https://slack.com/api/chat.postMessage", headers=H,
                          json={"channel": dm_id,
                                "text": f"✅ *育成FB処理完了*\n{staff_name} さん({session_date})の評価が #ピラティス_新規振り返り に投稿されました📩"})


# ── メイン関数 ────────────────────────────────────

def analyze_session(audio_file, staff_name: str, session_date, notes: str = "",
                    contract: str = "なし", course: str = "未契約") -> dict:
    """Streamlit から呼ばれるメインエントリ
    audio_file: streamlit UploadedFile
    contract: 契約結果("あり" / "なし")
    course: コース名(月3, 月4, 月8, 月12, 年払い, その他, 未契約)
    """
    # 1. 一時ファイル保存
    suffix = "." + audio_file.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_file.read())
        tmp_path = tmp.name

    try:
        # 2. 文字起こし
        transcript = transcribe_audio(tmp_path)

        # 3. Gemini で評価(契約状況含む)
        result = call_gemini(transcript, staff_name, session_date, notes, contract, course)
        result["transcript"] = transcript
        result["contract"] = contract
        result["course"] = course

        # 4. Slack通知
        send_slack_notifications(staff_name, session_date, result)

        return result
    finally:
        # 5. 個人情報保護: 音声ファイル即削除
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
