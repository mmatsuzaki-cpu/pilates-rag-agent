"""store_summary_reader.py

各店舗の集計表スプシから当月実績データを取得するモジュール。
これが正解値ソース(daily更新される)。

取得項目:
- LTVシート: 新規数 / 契約数 / 契約率
- 解約報告: 当月解約数
- 紹介報告: 当月紹介数(紹介元店舗が自店舗)
- 契約者リスト: 現役会員数(解約/休会/他店舗を除く)
"""

import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client

# 店舗マスタ + 集計表ID
STORE_SUMMARIES = [
    {"id": "S001", "name": "川越",     "ssid": "1rxz9nX9MU-e-lEHgv0GR9EdHR9bfikgPnQ0PGZ_dQWs",
     "name_in_referral": "川越"},
    {"id": "S002", "name": "大宮",     "ssid": "1nBDuZjma5GBbvLpM76dT1rhOjLbUiIOewXopBCuqTJk",
     "name_in_referral": "大宮"},
    {"id": "S003", "name": "高崎",     "ssid": "1KIe4m-PlWvPSFICw-dIp9UCumhzRF5qZWSIKPujr_aY",
     "name_in_referral": "高崎"},
    {"id": "S004", "name": "神戸元町", "ssid": "1z96p7RUZxlYqyQ-vDa1ChocuBwUydBKlqXXVVKnYANc",
     "name_in_referral": "神戸元町"},
    {"id": "S005", "name": "西宮北口", "ssid": "11MIOxDEPAI8YUpXpPAHFRzDcl1npQtXrhtcX72bmEQM",
     "name_in_referral": "西宮北口"},
]

# 現役会員から除外するコースキーワード(2026-05-04 松崎さん確定)
# E列(コース)に以下のいずれかを含む行は会員数からカウントしない
INACTIVE_COURSE_KEYWORDS = ["休会", "解約", "他店舗", "他店舗移動", "店舗移動"]


def reiwa_year(year: int) -> int:
    """西暦→令和年(令和元年=2019)"""
    return year - 2018


def ltv_sheet_name(year: int, month: int) -> str:
    """R{n}.{月}LTV 形式"""
    return f"R{reiwa_year(year)}.{month}月LTV"


def safe_int(s):
    if not s: return 0
    try:
        return int(str(s).replace(",", "").replace("¥", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return 0


def safe_pct(s):
    """'36%' → 0.36"""
    if not s: return 0.0
    try:
        return float(str(s).replace("%", "").strip()) / 100
    except ValueError:
        return 0.0


def parse_ymd(s):
    """'2024/09/25' → date object"""
    if not s: return None
    s = str(s).strip()
    for sep in ["/", "-", "."]:
        try:
            parts = s.split(sep)
            if len(parts) == 3:
                y, m, d = parts
                if len(y) == 2: y = "20" + y
                return date(int(y), int(m), int(d))
        except ValueError: continue
    return None


def find_sheet(sh, candidates: list):
    """シート名候補リストから最初に見つかったシートを返す"""
    titles = [ws.title for ws in sh.worksheets()]
    for c in candidates:
        for t in titles:
            if t.strip() == c.strip():
                return sh.worksheet(t)
    # 部分一致
    for c in candidates:
        for t in titles:
            if c.replace(" ", "") in t.replace(" ", ""):
                return sh.worksheet(t)
    return None


def get_store_summary(gc, store: dict, year: int, month: int) -> dict:
    """1店舗の指定月実績を取得"""
    sh = gc.open_by_key(store["ssid"])
    target_label = f"{year}年{month}月"

    result = {
        "store_id": store["id"], "name": store["name"],
        "year": year, "month": month, "year_month": f"{year}-{month:02d}",
        "newcomers": 0, "contracts": 0, "contract_rate": 0.0,
        "cancels": 0, "referrals": 0, "members": 0,
    }

    # 1. LTVシート
    ltv = find_sheet(sh, [ltv_sheet_name(year, month), f"R{reiwa_year(year)}.{month}月LTV "])
    if ltv:
        try:
            vals = ltv.batch_get(["D4", "G4", "H4"])
            result["newcomers"] = safe_int(vals[0][0][0]) if vals[0] else 0
            result["contracts"] = safe_int(vals[1][0][0]) if vals[1] else 0
            result["contract_rate"] = safe_pct(vals[2][0][0]) if vals[2] else 0.0
        except Exception as e:
            print(f"    ⚠️ LTV取得失敗: {e}")

    # 2. 解約報告 → 当月解約数(最終支払い日が前月の人)
    # 例: 4月の解約数 = 最終支払い日が3月の人
    kaiyaku = find_sheet(sh, ["解約報告"])
    if kaiyaku:
        try:
            prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
            v = kaiyaku.get_all_values()
            cnt = 0
            for row in v[1:]:
                if len(row) < 4 or not row[3]: continue
                d = parse_ymd(row[3])
                if d and d.year == prev_year and d.month == prev_month:
                    cnt += 1
            result["cancels"] = cnt
        except Exception as e:
            print(f"    ⚠️ 解約取得失敗: {e}")

    # 3. 紹介報告 → 当月紹介数(紹介元店舗 = 自店舗) D列(index=3)
    shoukai = find_sheet(sh, ["紹介報告"])
    if shoukai:
        try:
            v = shoukai.get_all_values()
            cnt = 0
            for row in v[1:]:
                if len(row) < 4 or not row[0]: continue
                d = parse_ymd(row[0])  # 入会日
                if d and d.year == year and d.month == month:
                    if row[3] and store["name_in_referral"] in row[3]:  # 紹介元店舗(D列)
                        cnt += 1
            result["referrals"] = cnt
        except Exception as e:
            print(f"    ⚠️ 紹介取得失敗: {e}")

    # 4. 契約者リスト → 現役会員数
    contract_list = find_sheet(sh, ["契約者リスト"])
    if contract_list:
        try:
            v = contract_list.get_all_values()
            cnt = 0
            for row in v[1:]:
                if len(row) < 5: continue
                course = row[4]  # E列=コース
                if not course: continue
                if any(kw in course for kw in INACTIVE_COURSE_KEYWORDS): continue
                cnt += 1
            result["members"] = cnt
        except Exception as e:
            print(f"    ⚠️ 会員数取得失敗: {e}")

    return result


def get_all_stores_summary(year: int = None, month: int = None) -> dict:
    """全店舗の指定月(デフォルト前月末確定値→なければ当月)実績取得"""
    gc = get_gspread_client()

    # デフォルトは前月末(確定値)
    if year is None or month is None:
        now = datetime.now()
        # 月の前半(1-15日)は前月の確定値、後半は当月の途中値
        if now.day <= 15:
            target_year, target_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        else:
            target_year, target_month = now.year, now.month
    else:
        target_year, target_month = year, month

    print(f"📥 集計表から取得: {target_year}年{target_month}月")
    result = {}
    for store in STORE_SUMMARIES:
        print(f"  {store['name']}...")
        try:
            data = get_store_summary(gc, store, target_year, target_month)
            result[store["id"]] = data
            print(f"    新規{data['newcomers']} 契約{data['contracts']} {data['contract_rate']*100:.0f}% "
                  f"解約{data['cancels']} 紹介{data['referrals']} 会員{data['members']}")
        except Exception as e:
            print(f"    ❌ {e}")
    return result


if __name__ == "__main__":
    # 2026年4月を取得
    data = get_all_stores_summary(2026, 4)
    print("\n=== 結果 ===")
    for sid, d in data.items():
        print(d)
