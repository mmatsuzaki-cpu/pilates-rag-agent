"""gemini_credit_watch.py - Gemini APIのクレジット切れを見張って松崎さんにDMする

前払い(プリペイド)で運用しているため、残高を使い切ると
AI FB（松崎メソッド）と音声FBが**エラーも出さずに静かに止まる**。
2026-09-06 に実際、9件の報告にFBが返らないまま数日気づけなかった。

通知は2種類:
  ① 予告   … 前回チャージから PREDICT_DAYS 日たったら「そろそろ切れるよ」
  ② 停止済 … 実際に 429(credits depleted) が返ったら「もう止まってるよ」

同じ通知を毎日送らないよう、状態を data/gemini_credit.json に記録する。

    python3 src/gemini_credit_watch.py            # 通常（cronから毎日）
    python3 src/gemini_credit_watch.py --topup    # チャージした日にこれを実行
    python3 src/gemini_credit_watch.py --status   # 送信せず状態だけ表示
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import PROJECT_ROOT, load_env, slack_bot_token

# 実績: 2026-06-06 に2,000円 → 2026-09-06 に残高マイナス。約3ヶ月＝月720円ペース。
# 切れる少し前に知らせたいので、75日たったら予告する。
PREDICT_DAYS = 75
STATE_PATH = Path(PROJECT_ROOT) / "data" / "gemini_credit.json"
BILLING_URL = "https://aistudio.google.com/billing"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check_gemini() -> tuple:
    """Geminiを1回だけ叩いて (状態, 詳細) を返す。
    状態: "ok" / "depleted"(クレジット切れ) / "error"(それ以外)
    出力トークンを絞ってあるので、この確認自体のコストはほぼゼロ。"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return "error", "GEMINI_API_KEY が未設定"
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": "ok"}]}],
                  "generationConfig": {"maxOutputTokens": 1}},
            timeout=30)
    except requests.RequestException as e:
        return "error", f"通信エラー: {e}"
    if r.status_code == 200:
        return "ok", ""
    msg = ""
    try:
        msg = r.json().get("error", {}).get("message", "")
    except Exception:
        msg = r.text[:200]
    if r.status_code == 429 and "credit" in msg.lower():
        return "depleted", msg
    return "error", f"HTTP {r.status_code}: {msg[:200]}"


def notify(text: str) -> bool:
    """松崎さんのDMへ送る"""
    user = os.environ.get("SLACK_OWNER_USER_ID", "")
    token = slack_bot_token()
    if not user or not token:
        print("⚠️ SLACK_OWNER_USER_ID / トークン未設定のため通知できません")
        return False
    r = requests.post("https://slack.com/api/chat.postMessage",
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json; charset=utf-8"},
                      json={"channel": user, "text": text}, timeout=30).json()
    if not r.get("ok"):
        print(f"⚠️ 通知失敗: {r.get('error')}")
    return bool(r.get("ok"))


def main() -> int:
    load_env()
    state = load_state()
    today = date.today()

    if "--topup" in sys.argv:
        state["last_topup"] = today.isoformat()
        state.pop("notified_predict", None)
        state.pop("notified_depleted", None)
        save_state(state)
        print(f"✅ チャージ日を {today} に記録しました（予告は{PREDICT_DAYS}日後）")
        return 0

    status, detail = check_gemini()
    last = state.get("last_topup")
    days = (today - date.fromisoformat(last)).days if last else None
    print(f"Gemini: {status} / 前回チャージ: {last or '未記録'}"
          + (f"（{days}日経過）" if days is not None else ""))
    if detail:
        print(f"  詳細: {detail[:150]}")

    if "--status" in sys.argv:
        return 0

    # ② すでに止まっている
    if status == "depleted":
        if state.get("notified_depleted") != today.isoformat():
            ok = notify(
                ":rotating_light: *Gemini APIのクレジットが切れました*\n"
                "AIフィードバック（松崎メソッド）と音声FBが止まっています。\n"
                "※テンプレFBは引き続き届きます\n\n"
                f"チャージはこちら → {BILLING_URL}\n"
                "チャージしたら `python3 src/gemini_credit_watch.py --topup` を実行してください。")
            if ok:
                state["notified_depleted"] = today.isoformat()
                save_state(state)
                print("📩 停止の通知を送りました")
        else:
            print("（本日分は通知済み）")
        return 0

    # ① そろそろ切れそう
    if status == "ok" and days is not None and days >= PREDICT_DAYS:
        if not state.get("notified_predict"):
            ok = notify(
                ":warning: *Gemini APIのクレジットがそろそろ切れます*\n"
                f"前回のチャージから {days}日たちました（目安は約90日）。\n"
                "切れるとAIフィードバックと音声FBが止まります。\n\n"
                f"チャージはこちら → {BILLING_URL}\n"
                "チャージしたら `python3 src/gemini_credit_watch.py --topup` を実行してください。")
            if ok:
                state["notified_predict"] = today.isoformat()
                save_state(state)
                print("📩 予告の通知を送りました")
        else:
            print("（予告は通知済み）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
