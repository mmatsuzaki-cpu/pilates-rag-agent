"""cancel_staff_aggregator.py

各店舗の集計表「解約報告」シートから、スタッフ別×月別の解約数を集計。
「ピラティス実績全部」スプシの「解約集計_スタッフ別」シートに書き込み + 整形。

【ルール】
- スタッフ判定: B列「担当」
- 解約月: 最終支払い日(D列)の翌月(例: 4月最終支払 → 5月解約)
- 表記揺れ正規化: NAME_NORMALIZE
- 並び順: 月降順(C列が最新月、右に行くほど過去)
- 店舗順: 川越 → 大宮 → 高崎 → 神戸元町 → 西宮北口
- 整形: 店舗別背景色 + ヘッダ太字 + 全セル境界線 + フリーズ

毎日10時の cron で full_dashboard_updater 経由から呼ばれる。
"""

import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client
from store_summary_reader import STORE_SUMMARIES, parse_ymd, with_retry

DASHBOARD_SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"
SHEET_TITLE = "解約集計_スタッフ別"

# スタッフ名の表記揺れ正規化(2026-05-14 松崎さん確定)
# - SAYKA → SAYAKA (神戸元町タイポ)
# - 菅野奈・菅野菜 は別人なのでそのまま
# - 菅野 は単独で残す(どちらか不明)
NAME_NORMALIZE = {
    "SAYKA": "SAYAKA",
}

# 店舗別の背景色(薄め)
STORE_COLORS = {
    "川越":     {"red": 0.87, "green": 0.94, "blue": 1.00},  # 薄水色
    "大宮":     {"red": 0.87, "green": 1.00, "blue": 0.91},  # 薄ミント
    "高崎":     {"red": 1.00, "green": 0.95, "blue": 0.85},  # 薄オレンジ
    "神戸元町": {"red": 1.00, "green": 0.87, "blue": 0.92},  # 薄ピンク
    "西宮北口": {"red": 0.93, "green": 0.87, "blue": 1.00},  # 薄パープル
}


def aggregate(gc):
    """5店舗の解約報告を読んで集計"""
    agg = defaultdict(int)
    all_months = set()
    all_staff_by_store = defaultdict(set)

    for store in STORE_SUMMARIES:
        print(f"  📥 {store['name']} 解約報告 ...", end=" ")
        ssh = gc.open_by_key(store["ssid"])
        ws = ssh.worksheet("解約報告")
        v = with_retry(ws.get_all_values)
        n = 0
        for row in v[1:]:
            if len(row) < 4:
                continue
            staff = (row[1] or "").strip()
            staff = NAME_NORMALIZE.get(staff, staff)
            pay_date_str = (row[3] or "").strip()
            if not staff or not pay_date_str:
                continue
            d = parse_ymd(pay_date_str)
            if not d:
                continue
            # 解約月 = 最終支払月+1
            cy, cm = d.year, d.month + 1
            if cm > 12:
                cy += 1
                cm = 1
            ym = f"{cy}-{cm:02d}"
            agg[(store["name"], staff, ym)] += 1
            all_months.add(ym)
            all_staff_by_store[store["name"]].add(staff)
            n += 1
        print(f"{n}件")

    return agg, all_months, all_staff_by_store


def col_letter(n):
    """1-indexed の列番号 → A1記法のアルファベット (1=A, 27=AA)"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_to_sheet(sh, agg, all_months, all_staff_by_store):
    """スプシに書き込み + 整形"""
    # シート取得 or 作成
    try:
        ws = sh.worksheet(SHEET_TITLE)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=SHEET_TITLE, rows=200, cols=40)
        print(f"  📋 シート新規作成: {SHEET_TITLE}")

    # 月降順(最新が一番左)
    months = sorted(all_months, reverse=True)
    STORE_ORDER = [s["name"] for s in STORE_SUMMARIES]
    header = ["店舗", "スタッフ"] + months + ["合計"]
    rows = [header]
    store_row_ranges = {}  # {store_name: (start_row_1indexed, end_row_1indexed)}

    for store_name in STORE_ORDER:
        staffs = sorted(all_staff_by_store[store_name])
        if not staffs:
            continue
        start = len(rows) + 1
        for staff in staffs:
            cnts = [agg.get((store_name, staff, m), 0) for m in months]
            total = sum(cnts)
            if total == 0:
                continue
            rows.append([store_name, staff] + cnts + [total])
        end = len(rows)
        if end >= start:
            store_row_ranges[store_name] = (start, end)

    n_cols = len(header)
    last_col = col_letter(n_cols)
    ws.update(values=rows, range_name=f"A1:{last_col}{len(rows)}", value_input_option="USER_ENTERED")
    print(f"  ✅ {len(rows)-1}行 × {n_cols}列 書き込み完了")

    # === 整形 ===
    sheet_id = ws.id
    requests = []

    # 1. ヘッダ行: 濃色背景・白文字・太字・サイズ12
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.27, "green": 0.31, "blue": 0.38},
                    "textFormat": {
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        "bold": True,
                        "fontSize": 12,
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }
    })

    # 2. 店舗ごとの背景色 + フォントサイズ11 + 太字
    for store_name, (start, end) in store_row_ranges.items():
        color = STORE_COLORS.get(store_name)
        if not color:
            continue
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": start - 1, "endRowIndex": end,
                          "startColumnIndex": 0, "endColumnIndex": n_cols},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {"fontSize": 11, "bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })

    # 3. 全セル境界線
    border = {"style": "SOLID",
              "colorStyle": {"rgbColor": {"red": 0.55, "green": 0.55, "blue": 0.55}}}
    requests.append({
        "updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(rows),
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "top": border, "bottom": border, "left": border, "right": border,
            "innerHorizontal": border, "innerVertical": border,
        }
    })

    # 4. フリーズ(1行目 + A・B列)
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    })

    # 5. 列幅自動
    requests.append({
        "autoResizeDimensions": {
            "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": n_cols},
        }
    })

    sh.batch_update({"requests": requests})
    print(f"  🎨 整形完了(色分け/境界線/フリーズ/列幅)")


def main():
    print("📊 解約集計_スタッフ別 更新開始")
    gc = get_gspread_client()
    agg, all_months, all_staff_by_store = aggregate(gc)
    print(f"  集計: {len(all_months)}ヶ月 / 計{sum(agg.values())}件\n")

    # quota待ち(集計表大量read後の書き込み前)
    print("  ⏱️ quota 待ち 65秒...")
    time.sleep(65)

    dash = gc.open_by_key(DASHBOARD_SSID)
    write_to_sheet(dash, agg, all_months, all_staff_by_store)

    print("\n🎉 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
