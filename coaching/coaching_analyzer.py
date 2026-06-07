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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 既存モジュール流用(リーダーFB事例・ノウハウ集の参照)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 並列文字起こしの設定
CHUNK_MINUTES = 5  # 1チャンクの長さ(分)
MAX_PARALLEL_WORKERS = 5  # 同時並列リクエスト数
SINGLE_FILE_SIZE_LIMIT_MB = 20  # この値以下は分割せず一発処理

# 環境変数読み込み(Streamlit Cloud では st.secrets、ローカルでは .env)
try:
    import streamlit as st
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = st.secrets.get("NOTION_LEADER_FB_DB_ID", "")
    NOTION_FB_HISTORY_DB_ID = st.secrets.get("NOTION_FB_HISTORY_DB_ID", "")
    SLACK_BOT_TOKEN = st.secrets.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = st.secrets.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B0L805YKT")
    SLACK_OWNER_USER_ID = st.secrets.get("SLACK_OWNER_USER_ID", "")
except Exception:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
    NOTION_LEADER_FB_DB_ID = os.environ.get("NOTION_LEADER_FB_DB_ID", "")
    NOTION_FB_HISTORY_DB_ID = os.environ.get("NOTION_FB_HISTORY_DB_ID", "")
    SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_FEEDBACK_CHANNEL_ID = os.environ.get("SLACK_FEEDBACK_CHANNEL_ID", "C0B0L805YKT")
    SLACK_OWNER_USER_ID = os.environ.get("SLACK_OWNER_USER_ID", "")


# ── 1. AI評価 + FB生成(Gemini Flash 音声入力ネイティブ) ──

EVAL_PROMPT_TEMPLATE = """あなたはピラティススタジオ「KOSHIKI × La pilates」の教育担当として、
添付された新人スタッフのカウンセリング録音を直接聴いて評価します。

【店舗】 {store}
【スタッフ名】 {staff_name}
【セッション日】 {session_date}
【契約結果】 {contract_status}
【コース】 {course_label}

【お客様情報】
- 年齢: {customer_age}
- 仕事: {customer_job}
- 悩み: {customer_concerns}
- 既往歴: {customer_history}

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

【処理手順】
1. 添付の音声ファイルを最初から最後まで聴いて、日本語で文字起こし
2. その文字起こしに基づいて評価項目4軸を採点
3. 振り返り要約・良かった点・改善点を生成
4. 全てを下記JSONで一度に出力

【出力形式(JSON厳守)】
{{
  "transcript": "<音声全体を日本語で正確に文字起こし(発話者の区別不要・段落分け推奨)>",
  "scores": {{"hearing": <int>, "proposal": <int>, "closing": <int>, "tone": <int>}},
  "session_summary": "<カウンセリング録音の要約(お客様の年齢/職業/主訴/提案内容/お客様の反応の流れを箇条書きで200〜400字程度・マークダウン)>",
  "good_points": "<良かったポイントを具体的に3つ箇条書き(マークダウン)>",
  "improvements": "<改善点を具体的に2つ箇条書き(マークダウン)>"
}}

JSONのみ出力。コメントや説明は不要。
"""


def fetch_leader_fb_examples(n: int = 3) -> str:
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


# ── 並列文字起こし用ヘルパー ──────────────────────

TRANSCRIBE_PROMPT = """添付の音声を日本語で正確に文字起こししてください。
発話者の区別は不要、自然な改行・段落分けを推奨。
文字起こしのみを返してください(他の説明・タイムコード・話者ラベルは不要)。"""


def _gemini_call_with_retry(model, contents, generation_config=None, timeout=600, max_retries=5):
    """Gemini API呼び出し共通関数: 429リトライ対応"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return model.generate_content(
                contents,
                generation_config=generation_config or {},
                request_options={"timeout": timeout},
            )
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "ResourceExhausted" in err_str:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Gemini APIレート制限が続いています💦 数分後にもう一度試してね\n"
                        f"継続するなら Google AI Studio で Tier 1 にアップグレード推奨\n"
                        f"詳細: {err_str[:200]}"
                    )
                wait_match = re.search(r"retry[_\s]*delay[^\d]*(\d+)", err_str)
                wait = int(wait_match.group(1)) + 10 if wait_match else 70
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Gemini呼び出し失敗: {last_error}")


def split_audio_to_chunks(audio_path: str, chunk_minutes: int = CHUNK_MINUTES) -> list:
    """音声ファイルを指定分数ごとのチャンクに分割
    pydub + ffmpeg を使用(packages.txt で ffmpeg をインストール)
    """
    from pydub import AudioSegment
    audio = AudioSegment.from_file(audio_path)
    chunk_ms = chunk_minutes * 60 * 1000
    chunks = []
    suffix = Path(audio_path).suffix.lstrip(".") or "m4a"
    export_format = "ipod" if suffix in ("m4a", "mp4", "aac") else suffix
    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = f"{audio_path}.chunk_{i // chunk_ms:03d}.{suffix}"
        chunk.export(chunk_path, format=export_format)
        chunks.append(chunk_path)
    return chunks


def transcribe_single_chunk(chunk_path: str, chunk_index: int = 0) -> str:
    """単一チャンクを Gemini Audio で文字起こし(並列実行される)"""
    import google.generativeai as genai
    uploaded = genai.upload_file(path=chunk_path)
    for _ in range(60):
        if uploaded.state.name == "ACTIVE":
            break
        if uploaded.state.name == "FAILED":
            raise RuntimeError(f"チャンク{chunk_index}: ファイルアップロード失敗")
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    else:
        raise RuntimeError(f"チャンク{chunk_index}: アップロード タイムアウト")

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = _gemini_call_with_retry(
        model,
        [uploaded, TRANSCRIBE_PROMPT],
        generation_config={"temperature": 0.1},
        timeout=300,
    )

    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    return response.text.strip()


def transcribe_audio_parallel(audio_path: str) -> str:
    """音声を分割→並列文字起こし→結合"""
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    chunks = split_audio_to_chunks(audio_path)
    chunk_count = len(chunks)
    try:
        transcripts = [""] * chunk_count
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            future_to_idx = {
                executor.submit(transcribe_single_chunk, chunk, i): i
                for i, chunk in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                transcripts[idx] = future.result()
        return "\n\n".join(t for t in transcripts if t)
    finally:
        for chunk in chunks:
            try:
                os.unlink(chunk)
            except OSError:
                pass


def evaluate_from_transcript(transcript: str, staff_name: str, session_date,
                              customer_info: dict = None,
                              contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """文字起こしから評価 + FB を生成(音声不要)"""
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

    customer_info = customer_info or {}
    leader_fb = fetch_leader_fb_examples()
    contract_status = "🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if (contract == "あり" and course not in ("", "—", None)) else "(契約なし)"

    audio_prompt = EVAL_PROMPT_TEMPLATE.format(
        store=store or "(未指定)",
        staff_name=staff_name,
        session_date=session_date,
        contract_status=contract_status,
        course_label=course_label,
        customer_age=customer_info.get("age", "(未入力)"),
        customer_job=customer_info.get("job", "(未入力)"),
        customer_concerns=customer_info.get("concerns", "(未入力)"),
        customer_history=customer_info.get("history", "(未入力)"),
        leader_fb_examples=leader_fb,
    )
    text_prompt = audio_prompt.replace(
        "添付された新人スタッフのカウンセリング録音を直接聴いて評価します。",
        "新人スタッフのカウンセリング文字起こしを評価します。"
    )
    text_prompt += f"\n\n【カウンセリング文字起こし】\n{transcript[:200000]}\n"

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = _gemini_call_with_retry(
        model,
        [text_prompt],
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
        timeout=600,
    )

    text = response.text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini JSON parse失敗: {e}\nresponse: {text[:500]}")


# ── メイン Gemini Audio 呼び出し ──────────────────

def call_gemini_with_audio(audio_path: str, staff_name: str, session_date,
                           customer_info: dict = None,
                           contract: str = "なし", course: str = "—", store: str = "") -> dict:
    """Gemini Flash 2.5 に音声ファイルを直接渡して、
    文字起こし + 評価 + FB生成 を1リクエストで完結する。
    faster-whisper を介さないので大幅高速化。
    """
    import google.generativeai as genai
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    genai.configure(api_key=GEMINI_API_KEY)

    # ── ① 音声ファイルを Gemini File API にアップロード ──
    uploaded = genai.upload_file(path=audio_path)
    # ファイルが ACTIVE になるまで待機(通常 数秒)
    for _ in range(60):
        if uploaded.state.name == "ACTIVE":
            break
        if uploaded.state.name == "FAILED":
            raise RuntimeError("Gemini File アップロード失敗")
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    else:
        raise RuntimeError("Gemini File アップロード タイムアウト(120秒)")

    # ── ② プロンプト組み立て ──
    customer_info = customer_info or {}
    leader_fb = fetch_leader_fb_examples()
    contract_status = f"🎉 契約獲得" if contract == "あり" else "🥲 契約なし(失注)"
    course_label = course if (contract == "あり" and course not in ("", "—", None)) else "(契約なし)"
    prompt = EVAL_PROMPT_TEMPLATE.format(
        store=store or "(未指定)",
        staff_name=staff_name,
        session_date=session_date,
        contract_status=contract_status,
        course_label=course_label,
        customer_age=customer_info.get("age", "(未入力)"),
        customer_job=customer_info.get("job", "(未入力)"),
        customer_concerns=customer_info.get("concerns", "(未入力)"),
        customer_history=customer_info.get("history", "(未入力)"),
        leader_fb_examples=leader_fb,
    )

    # ── ③ Gemini 呼び出し(音声 + プロンプト) - 429リトライ対応 ──
    # gemini-2.0-flash: 無料枠 10 RPM (gemini-2.5-flash の倍)
    model = genai.GenerativeModel("gemini-2.0-flash")
    last_error = None
    response = None
    for attempt in range(6):
        try:
            response = model.generate_content(
                [uploaded, prompt],
                generation_config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                },
                request_options={"timeout": 600},  # 10分タイムアウト
            )
            break
        except Exception as e:
            last_error = e
            err_str = str(e)
            # 429 quota error は自動リトライ(最大5回)
            if "429" in err_str or "quota" in err_str.lower() or "ResourceExhausted" in err_str:
                if attempt >= 5:
                    raise RuntimeError(
                        f"Gemini APIレート制限が続いています💦 数分後にもう一度試してね\n"
                        f"継続するなら Google AI Studio で Tier 1 にアップグレード推奨(無料)\n"
                        f"詳細: {err_str[:200]}"
                    )
                # retry_delay秒数を抽出(なければ70秒)
                wait_match = re.search(r"retry[_\s]*delay[^\d]*(\d+)", err_str)
                wait = int(wait_match.group(1)) + 10 if wait_match else 70
                time.sleep(wait)
                continue
            # その他のエラーは即fail
            raise
    if response is None:
        raise RuntimeError(f"Gemini呼び出し失敗: {last_error}")

    # ── ④ ファイル削除(個人情報保護: Gemini側にも残さない) ──
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass

    # ── ⑤ JSON パース ──
    text = response.text.strip()
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
    course = result.get("course", "—")
    if contract == "あり" and course not in ("", "—", None):
        contract_line = f"🎉 *契約獲得* ({course})"
    elif contract == "あり":
        contract_line = "🎉 *契約獲得*"
    else:
        contract_line = "🥲 契約なし"

    session_summary = result.get("session_summary", "(要約なし)")

    # ② チャンネル投稿(振り返り内容 + FB が1つにまとまった形)
    store = result.get("store", "")
    store_line = f"🏠 {store}店  " if store else ""
    questions = (result.get("questions") or "").strip()
    questions_block = (
        f"\n\n━━━━━━━━━━━━━━\n"
        f"❓ *リーダー/研修担当への疑問点*\n{questions}"
        if questions else ""
    )
    channel_msg = (
        f"🎤 *新規カウンセリング振り返り*\n"
        f"{store_line}👤 {staff_name} さん  📅 {session_date}\n"
        f"{contract_line}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📝 *振り返り内容*\n"
        f"{session_summary}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 *評価*  平均★{avg:.1f}/5\n"
        f"{star_line}\n\n"
        f"💎 *良かった点*\n{result.get('good_points', '')}\n\n"
        f"🎯 *改善点*\n{result.get('improvements', '')}"
        f"{questions_block}"
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


# ── 4. Notion 蓄積 ────────────────────────────────

def _rich_text(content: str, max_len: int = 2000) -> list:
    """Notion rich_text 形式に変換(2000文字制限あり)"""
    if not content:
        return []
    return [{"type": "text", "text": {"content": str(content)[:max_len]}}]


def save_to_notion(staff_name: str, session_date, result: dict) -> str:
    """評価結果を Notion DB「📊 ピラティス育成FB履歴」に保存
    返り値: 作成したページURL(失敗時は空文字)
    """
    if not NOTION_TOKEN or not NOTION_FB_HISTORY_DB_ID:
        return ""

    import requests
    H = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    scores = result.get("scores", {})
    hearing = int(scores.get("hearing", 0))
    proposal = int(scores.get("proposal", 0))
    closing = int(scores.get("closing", 0))
    tone = int(scores.get("tone", 0))
    avg = round((hearing + proposal + closing + tone) / 4, 2) if any([hearing, proposal, closing, tone]) else 0

    customer_info = result.get("customer_info") or {}
    age = customer_info.get("age", "—")
    job = customer_info.get("job", "")
    concerns = customer_info.get("concerns", "")
    history = customer_info.get("history", "")

    contract = result.get("contract", "なし")
    course = result.get("course", "—") or "—"
    store = result.get("store", "")
    questions = result.get("questions", "")
    transcript = result.get("transcript", "")
    summary = result.get("session_summary", "")
    good_points = result.get("good_points", "")
    improvements = result.get("improvements", "")

    # セッション日: date(YYYY-MM-DD) に変換
    if hasattr(session_date, "isoformat"):
        date_str = session_date.isoformat()
    else:
        date_str = str(session_date)

    properties = {
        "スタッフ名": {"title": [{"type": "text", "text": {"content": staff_name}}]},
        "セッション日": {"date": {"start": date_str}},
        "ヒアリング★": {"number": hearing},
        "提案★": {"number": proposal},
        "クロージング★": {"number": closing},
        "トーン★": {"number": tone},
        "平均★": {"number": avg},
        "仕事": {"rich_text": _rich_text(job)},
        "悩み": {"rich_text": _rich_text(concerns)},
        "既往歴": {"rich_text": _rich_text(history)},
        "振り返り要約": {"rich_text": _rich_text(summary)},
        "良かった点": {"rich_text": _rich_text(good_points)},
        "改善点": {"rich_text": _rich_text(improvements)},
        "疑問点": {"rich_text": _rich_text(questions)},
        "文字起こし全文": {"rich_text": _rich_text(transcript)},
    }

    # セレクト系: 値があるときだけ設定(空だとAPIエラー)
    if store:
        properties["店舗"] = {"select": {"name": store}}
    if contract:
        properties["契約結果"] = {"select": {"name": contract}}
    if course and course != "":
        properties["コース"] = {"select": {"name": course}}
    if age and age != "":
        properties["年齢"] = {"select": {"name": age}}

    payload = {
        "parent": {"database_id": NOTION_FB_HISTORY_DB_ID},
        "properties": properties,
    }

    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=H, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json().get("url", "")
        else:
            # 失敗してもメインフローは止めない
            print(f"[Notion保存失敗] {r.status_code}: {r.text[:300]}")
            return ""
    except Exception as e:
        print(f"[Notion保存例外] {e}")
        return ""


# ── メイン関数 ────────────────────────────────────

def analyze_session(audio_file, staff_name: str, session_date,
                    customer_info: dict = None,
                    contract: str = "なし", course: str = "—", store: str = "",
                    questions: str = "") -> dict:
    """Streamlit から呼ばれるメインエントリ
    audio_file: streamlit UploadedFile
    customer_info: お客様情報 dict (age / job / concerns / history)
    contract: 契約結果("あり" / "なし")
    course: コース名(サブスク月X / 年払い月X / 整体なし月X / トライアル2回 / —)
    store: 店舗(川越/大宮/高崎/神戸元町/西宮北口/所沢/浦和)
    questions: スタッフからの疑問点(任意・リーダー/研修担当に共有)
    """
    # 1. 一時ファイル保存
    suffix = "." + audio_file.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_file.read())
        tmp_path = tmp.name

    try:
        # 2. ファイルサイズに応じて単一処理 or 分割並列処理を自動振り分け
        size_mb = os.path.getsize(tmp_path) / 1024 / 1024
        if size_mb <= SINGLE_FILE_SIZE_LIMIT_MB:
            # 小〜中ファイル: 一発処理(文字起こし+評価を1リクエスト)
            result = call_gemini_with_audio(tmp_path, staff_name, session_date,
                                            customer_info=customer_info,
                                            contract=contract, course=course, store=store)
        else:
            # 大ファイル: 分割並列文字起こし → 評価生成
            print(f"[Chunked] {size_mb:.1f}MB → {CHUNK_MINUTES}分ごとに分割、{MAX_PARALLEL_WORKERS}並列で処理")
            transcript = transcribe_audio_parallel(tmp_path)
            result = evaluate_from_transcript(transcript, staff_name, session_date,
                                              customer_info=customer_info,
                                              contract=contract, course=course, store=store)
            # transcript フィールドを上書き(並列文字起こしの方を採用)
            result["transcript"] = transcript

        # transcript は Gemini が JSON で返してくる(キー名は "transcript")
        result["contract"] = contract
        result["course"] = course
        result["store"] = store
        result["questions"] = questions
        result["customer_info"] = customer_info or {}

        # 4. Slack通知
        send_slack_notifications(staff_name, session_date, result)

        # 5. Notion 蓄積(失敗してもメインは止めない)
        notion_url = save_to_notion(staff_name, session_date, result)
        if notion_url:
            result["notion_url"] = notion_url

        return result
    finally:
        # 5. 個人情報保護: 音声ファイル即削除
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
