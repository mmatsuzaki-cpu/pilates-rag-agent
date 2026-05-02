"""full_dashboard_updater.py

新スプシ「ピラティス実績全部」の以下4シートを更新:
- 売上(2026年度): CSV共有時のみ手動実行 (--sales フラグ)
- 契約率: 毎日更新
- 解約率: 毎日更新
- 口コミ: 毎日更新(Google + HPB件数)

データソース:
- 売上/契約率/解約率: 既存スプシ「店舗事業_課題発見RAG」の ⑦月次店舗実績(最新月の月末/月中)
- 口コミ: Google Places API + HPB scrape (リアルタイム取得)

使い方:
    python3 src/full_dashboard_updater.py --daily       # 契約率/解約率/口コミ
    python3 src/full_dashboard_updater.py --sales       # 売上のみ(CSV共有時)
    python3 src/full_dashboard_updater.py --all         # 全部
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client, get_jisseki_data, PROJECT_ROOT
from store_summary_reader import get_all_stores_summary

DASHBOARD_SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"  # ピラティス実績全部
TAX_RATE = 1.10  # 税込→税抜 で /1.1

# 店舗マスタ(画面の表示順:川越/大宮/神戸元町/高崎/西宮北口)
STORE_ORDER = [
    ("S001", "川越"),
    ("S002", "大宮"),
    ("S004", "神戸元町"),
    ("S003", "高崎"),
    ("S005", "西宮北口"),
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# ============================================
# 売上更新
# ============================================
def update_sales(sh, jisseki: dict):
    """売上(2026年度) シートの最新月行を更新
    列構造:
      A: 月ラベル(売上税込)   B-F: 5店舗 G: 合計
      I: 月ラベル(売上税抜)   J-N: 5店舗 O: 合計
      Q: 月ラベル(利益)      R-V: 5店舗 W: 合計
    """
    ws = sh.worksheet("売上(2026年度)")
    all_v = ws.get_all_values()
    # 最新月(jisseki の year_month が最も多い月)
    if not jisseki: return
    sample = next(iter(jisseki.values()))
    ym = sample["year_month"]  # "2026-04"
    year, month = ym.split("-")
    target_label = f"{int(year)}年{int(month)}月"

    # 該当行を探す
    row_idx = None
    for i, row in enumerate(all_v[1:], start=2):
        if row and row[0] == target_label:
            row_idx = i; break
    if not row_idx:
        print(f"  ⚠️ 売上 {target_label}行が見つからない")
        return

    # 売上税込のみ更新(税抜・利益・合計は保護=数式)
    updates = []
    for col_idx, (sid, _) in enumerate(STORE_ORDER, start=2):  # B-F (税込)
        if sid in jisseki:
            net = jisseki[sid]["sales"]  # 税抜
            gross = round(net * TAX_RATE)  # 税込
            updates.append((col_idx, gross))

    for col, val in updates:
        ws.update_cell(row_idx, col, val)

    print(f"  ✅ 売上 {target_label}行 税込列を更新({len(updates)}セル)/ 税抜・利益は数式で自動計算")


# ============================================
# 契約率更新
# ============================================
def update_contract_rate(sh, summary: dict):
    """契約率シート 月行を更新(集計表ソース)"""
    ws = sh.worksheet("契約率")
    all_v = ws.get_all_values()
    if not summary: return
    sample = next(iter(summary.values()))
    target_label = f"{sample['year']}年{sample['month']}月"
    short_label = f"{sample['month']}月"

    row_idx = None
    for i, row in enumerate(all_v[2:], start=3):
        if row and (row[0] == target_label or row[0] == short_label):
            row_idx = i; break
    if not row_idx:
        ws.append_row([target_label] + [""] * 15, value_input_option="USER_ENTERED")
        row_idx = len(ws.get_all_values())
        print(f"  ➕ 契約率 {target_label}行 新規追加")

    col_map = {"S001": 2, "S002": 5, "S004": 8, "S003": 11, "S005": 14}
    for sid, base_col in col_map.items():
        if sid not in summary: continue
        d = summary[sid]
        ws.update_cell(row_idx, base_col, d["newcomers"])
        ws.update_cell(row_idx, base_col + 1, d["contracts"])
        rate = d["contract_rate"] * 100 if d["contract_rate"] else 0
        ws.update_cell(row_idx, base_col + 2, f"{rate:.0f}%")
    print(f"  ✅ 契約率 {target_label}行 更新完了(集計表ベース)")


def update_cancel_rate(sh, summary: dict):
    """解約率シート 月行を更新(集計表ソース)"""
    ws = sh.worksheet("解約率")
    all_v = ws.get_all_values()
    if not summary: return
    sample = next(iter(summary.values()))
    target_label = f"{sample['year']}年{sample['month']}月"

    row_idx = None
    for i, row in enumerate(all_v[2:], start=3):
        if row and row[0] == target_label:
            row_idx = i; break
    if not row_idx:
        ws.append_row([target_label] + [""] * 20, value_input_option="USER_ENTERED")
        row_idx = len(ws.get_all_values())
        print(f"  ➕ 解約率 {target_label}行 新規追加")

    # 入会:B-F / 解約:G-K / 会員:L-P / 解約率:Q-U
    # 順序: 川越/大宮/神戸元町/高崎/西宮北口
    order = [("S001", 0), ("S002", 1), ("S004", 2), ("S003", 3), ("S005", 4)]
    for sid, idx in order:
        if sid not in summary: continue
        d = summary[sid]
        ws.update_cell(row_idx, 2 + idx, d["contracts"])
        ws.update_cell(row_idx, 7 + idx, d["cancels"])
        ws.update_cell(row_idx, 12 + idx, d["members"])
        rate = (d["cancels"] / d["members"] * 100) if d["members"] else 0
        ws.update_cell(row_idx, 17 + idx, f"{rate:.1f}%")
    print(f"  ✅ 解約率 {target_label}行 更新完了(集計表ベース)")


# ============================================
# 口コミ更新
# ============================================
def fetch_google_count(place_id: str) -> int:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/place/details/json",
                         params={"place_id": place_id, "language": "ja",
                                 "fields": "user_ratings_total", "key": api_key},
                         timeout=20)
        if r.json().get("status") == "OK":
            return r.json()["result"].get("user_ratings_total", 0)
    except: pass
    return None


def fetch_hpb_count(url: str) -> int:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        m = re.search(r'slnHeaderKuchikomiCount[^>]*>[^（(]*[（(]\s*(\d[\d,]*)\s*件', r.text)
        if m:
            return int(m.group(1).replace(",", ""))
    except: pass
    return None


HPB_URLS = {
    "S001": "https://beauty.hotpepper.jp/kr/slnH000743149/",
    "S002": "https://beauty.hotpepper.jp/kr/slnH000745957/",
    "S003": "https://beauty.hotpepper.jp/kr/slnH000774690/",
    "S004": "https://beauty.hotpepper.jp/kr/slnH000740308/",
    "S005": "https://beauty.hotpepper.jp/kr/slnH000777989/",
}


def update_reviews(sh):
    """口コミシート 月列を更新
    列構造:
      A: グループ(Google/HPB)
      B: 店舗名
      C: 目標
      D-: 月別(12月、2025年1月、...、最新月、前月比)
    行2-6: Google × 5店舗 / 行7-11: HPB × 5店舗
    """
    ws = sh.worksheet("口コミ")
    all_v = ws.get_all_values()
    header = all_v[0]

    # 現在月のラベル
    now = datetime.now()
    year, month = now.year, now.month
    if year == 2025:
        target_label = f"{month}月" if month != 1 else "2025年1月"
    elif year == 2026:
        target_label = f"{month}月" if month != 1 else "2026年1月"
    else:
        target_label = f"{year}年{month}月"

    # 列を探す(完全一致 or 数字のみ)
    col_idx = None
    for i, h in enumerate(header):
        if h == target_label or h == f"{month}月":
            col_idx = i + 1; continue
    if not col_idx:
        # 「前月比」の前に列追加
        zenmonth_idx = None
        for i, h in enumerate(header):
            if h == "前月比":
                zenmonth_idx = i; break
        if zenmonth_idx:
            ws.insert_cols([[target_label]], col=zenmonth_idx + 1)
            col_idx = zenmonth_idx + 1
            print(f"  ➕ 口コミ '{target_label}'列 新規追加(列{col_idx})")
        else:
            print(f"  ⚠️ 口コミ '{target_label}'列を追加できない")
            return

    # 件数取得
    place_ids = json.loads((PROJECT_ROOT / "config" / "place_ids.json").read_text())
    counts = {}
    for sid, info in place_ids.items():
        counts[sid] = {
            "google": fetch_google_count(info["place_id"]),
            "hpb": fetch_hpb_count(HPB_URLS.get(sid)),
        }
        print(f"  📊 {info['name']:10s}: G={counts[sid]['google']} H={counts[sid]['hpb']}")

    # シートに反映
    # Google: 行2-6 (川越/大宮/高崎/神戸元町/西宮北口)
    # HPB: 行7-11
    google_rows = {"S001": 2, "S002": 3, "S003": 4, "S004": 5, "S005": 6}
    hpb_rows = {"S001": 7, "S002": 8, "S003": 9, "S004": 10, "S005": 11}
    for sid in ["S001", "S002", "S003", "S004", "S005"]:
        if counts[sid]["google"] is not None:
            ws.update_cell(google_rows[sid], col_idx, counts[sid]["google"])
        if counts[sid]["hpb"] is not None:
            ws.update_cell(hpb_rows[sid], col_idx, counts[sid]["hpb"])
    print(f"  ✅ 口コミ '{target_label}'列 更新完了")


# ============================================
# メイン
# ============================================
def main():
    do_sales = "--sales" in sys.argv or "--all" in sys.argv
    do_daily = "--daily" in sys.argv or "--all" in sys.argv
    if not do_sales and not do_daily:
        print("使い方: python3 full_dashboard_updater.py [--daily | --sales | --all]")
        return 1

    print(f"📊 ダッシュボード更新開始: {datetime.now()}")
    gc = get_gspread_client()
    sh = gc.open_by_key(DASHBOARD_SSID)

    # 売上は⑦月次店舗実績から、契約率/解約率は集計表(各店舗スプシ)から
    if do_sales:
        print("\n📥 売上元データ取得(⑦月次店舗実績)")
        jisseki = get_jisseki_data()
        if not jisseki:
            print("❌ データ取得失敗"); return 1
        print("\n💰 売上更新")
        update_sales(sh, jisseki)

    if do_daily:
        # 月の前半は前月末確定値、後半は当月途中値
        now = datetime.now()
        if now.day <= 15:
            target_year = now.year if now.month > 1 else now.year - 1
            target_month = now.month - 1 if now.month > 1 else 12
        else:
            target_year, target_month = now.year, now.month
        print(f"\n📥 集計表からデータ取得 ({target_year}年{target_month}月)")
        summary = get_all_stores_summary(target_year, target_month)
        if not summary:
            print("❌ 集計表取得失敗"); return 1
        print("\n📈 契約率更新")
        update_contract_rate(sh, summary)
        print("\n📉 解約率更新")
        update_cancel_rate(sh, summary)
        print("\n⭐ 口コミ更新")
        update_reviews(sh)

    print("\n🎉 完了!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
