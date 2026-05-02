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

    # 完全一致のみ("5月"のような短縮ラベルにはマッチさせない=過去年破壊防止)
    row_idx = None
    for i, row in enumerate(all_v[2:], start=3):
        if row and row[0] == target_label:
            row_idx = i; break
    if not row_idx:
        # 月行は「平均」行の上に挿入(平均は1行下にずれる)
        # 平均行が無ければ末尾に追加
        avg_row = None
        for i, row in enumerate(all_v[2:], start=3):
            if row and row[0].strip() == "平均":
                avg_row = i; break
        sheet_id = ws.id
        if avg_row:
            # A列をTEXTフォーマットにしてラベルを文字列として保持
            sh.batch_update({"requests": [{
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": avg_row - 1, "endRowIndex": avg_row,
                              "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                    "fields": "userEnteredFormat.numberFormat"
                }
            }]})
            ws.insert_row([target_label] + [""] * 15, avg_row, value_input_option="RAW")
            row_idx = avg_row
            # 直前の月行(avg_row - 1 が新規行になったので、その上= avg_row - 1 - 1)からフォーマットコピー
            src = avg_row - 2  # 0-indexed の直前月行
            sh.batch_update({"requests": [{
                "copyPaste": {
                    "source": {"sheetId": sheet_id, "startRowIndex": src, "endRowIndex": src + 1,
                               "startColumnIndex": 0, "endColumnIndex": 16},
                    "destination": {"sheetId": sheet_id, "startRowIndex": row_idx - 1, "endRowIndex": row_idx,
                                    "startColumnIndex": 0, "endColumnIndex": 16},
                    "pasteType": "PASTE_FORMAT"
                }
            }]})
            print(f"  ➕ 契約率 {target_label}行 新規挿入(平均行の上, 罫線継承)")
        else:
            ws.append_row([target_label] + [""] * 15, value_input_option="USER_ENTERED")
            row_idx = len(ws.get_all_values())
            print(f"  ➕ 契約率 {target_label}行 末尾追加")

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
        # 末尾追加 + 直前行(前月)のフォーマットをコピー(罫線継承)
        prev_row_idx = len(all_v)  # ヘッダ込みの最終行(=直前月行)
        ws.append_row([target_label] + [""] * 20, value_input_option="USER_ENTERED")
        row_idx = len(ws.get_all_values())
        sheet_id = ws.id
        sh.batch_update({"requests": [{
            "copyPaste": {
                "source": {"sheetId": sheet_id, "startRowIndex": prev_row_idx - 1, "endRowIndex": prev_row_idx,
                           "startColumnIndex": 0, "endColumnIndex": 21},
                "destination": {"sheetId": sheet_id, "startRowIndex": row_idx - 1, "endRowIndex": row_idx,
                                "startColumnIndex": 0, "endColumnIndex": 21},
                "pasteType": "PASTE_FORMAT"
            }
        }]})
        print(f"  ➕ 解約率 {target_label}行 新規追加(罫線継承)")

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

    # 現在月のラベル(年プレフィックス必須=過去年「5月」誤マッチ防止)
    now = datetime.now()
    year, month = now.year, now.month
    target_label = f"{year}年{month}月"

    # 列を探す(完全一致のみ・最初に見つかったもの)
    col_idx = None
    for i, h in enumerate(header):
        if h == target_label:
            col_idx = i + 1; break
    if not col_idx:
        # 「前月比」の前に列追加(罫線・幅は左列継承)
        zenmonth_idx = None
        for i, h in enumerate(header):
            if h == "前月比":
                zenmonth_idx = i; break
        if zenmonth_idx is not None:
            sheet_id = ws.id
            sh.batch_update({"requests": [{
                "insertDimension": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                              "startIndex": zenmonth_idx, "endIndex": zenmonth_idx + 1},
                    "inheritFromBefore": True
                }
            }]})
            col_idx = zenmonth_idx + 1  # 1-indexed
            ws.update_cell(1, col_idx, target_label)
            print(f"  ➕ 口コミ '{target_label}'列 新規追加(列{col_idx}, 前月比の左)")
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
    # Google: 行2-6 / HPB: 行7-11 / 合計(Google+HPB): 行12-16
    google_rows = {"S001": 2, "S002": 3, "S003": 4, "S004": 5, "S005": 6}
    hpb_rows = {"S001": 7, "S002": 8, "S003": 9, "S004": 10, "S005": 11}
    total_rows = {"S001": 12, "S002": 13, "S003": 14, "S004": 15, "S005": 16}
    for sid in ["S001", "S002", "S003", "S004", "S005"]:
        g = counts[sid]["google"]
        h = counts[sid]["hpb"]
        if g is not None:
            ws.update_cell(google_rows[sid], col_idx, g)
        if h is not None:
            ws.update_cell(hpb_rows[sid], col_idx, h)
        if g is not None or h is not None:
            ws.update_cell(total_rows[sid], col_idx, (g or 0) + (h or 0))
    print(f"  ✅ 口コミ '{target_label}'列 更新完了(Google+HPB+合計)")


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
        # 常に当月のデータを取得(月が変わったら新規行/列を自動追加)
        now = datetime.now()
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

        # 月初(1-3日)は念のため前月の確定値も再更新(集計表が後から更新される可能性)
        # API quota切れになっても全体は落とさない(翌日の実行でリカバーされる)
        if now.day <= 3:
            prev_year, prev_month = (target_year, target_month - 1) if target_month > 1 else (target_year - 1, 12)
            print(f"\n📥 月初なので前月({prev_year}年{prev_month}月)の確定値も再更新")
            try:
                prev_summary = get_all_stores_summary(prev_year, prev_month)
                if prev_summary:
                    update_contract_rate(sh, prev_summary)
                    update_cancel_rate(sh, prev_summary)
            except Exception as e:
                print(f"⚠️ 前月再更新スキップ ({e})")

    print("\n🎉 完了!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
