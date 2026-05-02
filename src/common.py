"""共通モジュール - スプシアクセス、Slack送信、Notion API"""

import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# pilates-mikomiのvenvからgspreadなど借用
sys.path.insert(0, '/Users/user/projects/pilates-mikomi/.venv/lib/python3.9/site-packages')

PROJECT_ROOT = Path(__file__).parent.parent
SPREADSHEET_ID = "1W3OUR8sxb_MhBgPJoHnsY9thfDQOdUdzEYErUVutrw4"

# 店舗マスタ
STORES = [
    {"id": "S001", "name": "川越店",     "machines": 6, "staff": 4,
     "sales_target": 4_000_000, "profit_target": 1_000_000},
    {"id": "S002", "name": "大宮店",     "machines": 8, "staff": 6,
     "sales_target": 6_000_000, "profit_target": 2_500_000},
    {"id": "S003", "name": "高崎店",     "machines": 6, "staff": 3,
     "sales_target": 3_000_000, "profit_target": 1_500_000},
    {"id": "S004", "name": "神戸元町店", "machines": 6, "staff": 5,
     "sales_target": 5_000_000, "profit_target": 1_500_000},
    {"id": "S005", "name": "西宮北口店", "machines": 6, "staff": 3,
     "sales_target": 3_000_000, "profit_target": 1_000_000},
]


def get_gspread_client():
    """gspreadクライアント取得"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = PROJECT_ROOT / "config" / "credentials.json"
    creds = Credentials.from_service_account_file(
        str(creds_path),
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return gspread.authorize(creds)


def load_env():
    """.env読み込み"""
    env_path = PROJECT_ROOT / "config" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def slack_webhook_send(text: str, link_names: bool = True) -> bool:
    """Webhook送信"""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        webhook = (PROJECT_ROOT / "config" / "slack_webhook.txt").read_text().strip()
    for attempt in range(3):
        try:
            r = requests.post(
                webhook,
                json={"text": text, "link_names": link_names},
                timeout=30,
            )
            if r.status_code == 200:
                return True
            print(f"  ⚠️ HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ⚠️ 試行{attempt+1}失敗: {e}")
            time.sleep(3)
    return False


def slack_bot_token() -> str:
    """Bot Token取得"""
    return (PROJECT_ROOT / "config" / "slack_bot_token.txt").read_text().strip()


def slack_post_message(channel: str, text: str, thread_ts: Optional[str] = None) -> dict:
    """chat.postMessage"""
    payload = {
        "channel": channel, "text": text, "link_names": True,
        "unfurl_links": False, "unfurl_media": False,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {slack_bot_token()}",
                 "Content-Type": "application/json; charset=utf-8"},
        json=payload, timeout=30,
    )
    return r.json()


def slack_dm(user_id: str, text: str) -> bool:
    """松崎さん個人DM"""
    r = requests.post(
        "https://slack.com/api/conversations.open",
        headers={"Authorization": f"Bearer {slack_bot_token()}"},
        json={"users": user_id}, timeout=30,
    )
    res = r.json()
    if not res.get("ok"):
        return False
    channel_id = res["channel"]["id"]
    res = slack_post_message(channel_id, text)
    return res.get("ok", False)


def notion_headers():
    return {
        "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def get_jisseki_data(period: Optional[str] = None) -> dict:
    """⑦月次店舗実績から最新の有効データを取得
    period: '月末(1-月末)' or '月中(1-15日)' or None(自動: 月末優先→月中)
    """
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("⑦月次店舗実績")
    all_values = ws.get_all_values()
    header = all_values[0]
    COL = {h: i for i, h in enumerate(header)}

    result = {}
    for store in STORES:
        store_id = store["id"]
        store_rows = [r for r in all_values[1:]
                      if len(r) > COL['店舗ID'] and r[COL['店舗ID']] == store_id]
        store_rows.sort(key=lambda r: r[COL['年月']], reverse=True)

        latest = None
        if period == '月中(1-15日)':
            for r in store_rows:
                if r[COL['期間']] == '月中(1-15日)' and r[COL['売上(税抜)']]:
                    latest = r; break
        elif period == '月末(1-月末)':
            for r in store_rows:
                if r[COL['期間']] == '月末(1-月末)' and r[COL['売上(税抜)']]:
                    latest = r; break
        else:
            for r in store_rows:
                if r[COL['期間']] == '月末(1-月末)' and r[COL['売上(税抜)']]:
                    latest = r; break
            if not latest:
                for r in store_rows:
                    if r[COL['期間']] == '月中(1-15日)' and r[COL['売上(税抜)']]:
                        latest = r; break
        if not latest:
            continue

        def get_int(col):
            v = latest[COL[col]] if COL[col] < len(latest) else ""
            try: return int(v) if v else 0
            except ValueError: return 0
        def get_float(col):
            v = latest[COL[col]] if COL[col] < len(latest) else ""
            try: return float(v) if v else 0.0
            except ValueError: return 0.0

        result[store_id] = {
            "name": store["name"],
            "year_month": latest[COL['年月']],
            "period": latest[COL['期間']],
            "sales_target": store["sales_target"],
            "profit_target": store["profit_target"],
            "sales": get_int('売上(税抜)'),
            "profit": get_int('利益(税抜)'),
            "members": get_int('会員数'),
            "contract_rate": get_float('契約率'),
            "contracts": get_int('契約数'),
            "newcomers": get_int('新規数'),
            "cancels": get_int('解約数'),
            "referrals": get_int('紹介数'),
            "google_review": get_int('Google口コミ'),
            "hpb_review": get_int('HPB口コミ'),
        }
    return result


def format_money(yen: int) -> str:
    if yen is None: return "—"
    if abs(yen) >= 10000:
        return f"{yen/10000:,.1f}万"
    return f"{yen:,}"


def status_emoji(achievement: float) -> str:
    if achievement is None: return "⚪"
    if achievement >= 1.0: return "🟢"
    if achievement >= 0.85: return "🟡"
    return "🔴"


def contract_status(rate: float) -> str:
    if rate is None or rate == 0: return "⚪"
    if rate >= 0.5: return "🟢"
    if rate >= 0.4: return "🟡"
    return "🔴"


# .env を import 時に自動ロード
load_env()
