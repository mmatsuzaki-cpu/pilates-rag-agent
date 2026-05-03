"""sales_csv_loader.py

~/Downloads/ に置かれた店舗別売上CSV(Shift-JIS)を検出 →
⑦月次店舗実績シートの「当月 / 月中(1-15日)」行を作成・更新 →
処理後はalert_sender.pyを呼んでSlack #ピラティス_実績進捗 に速報送信。

CSV ファイル名規則:
- "MMDD{店舗名}.csv" (例: 0503川越.csv)
- "{店舗名}.csv"     (例: 神戸元町.csv)
店舗名: 川越/大宮/高崎/神戸元町/西宮北口

CSV内のデータは「月初〜CSV作成日まで」の累積値という前提。
処理後はファイル名を {YYYY-MM}/{元名} に移動して重複処理防止。

cron 5分間隔で実行 → CSV置けば最大5分以内に反映。
"""

import csv
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client, SPREADSHEET_ID

DOWNLOADS = Path.home() / "Downloads"
PROJECT_ROOT = Path(__file__).parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "sales" / "processed"

# CSV 店舗名 → store_id
STORE_MAP = {
    "川越":     "S001",
    "大宮":     "S002",
    "高崎":     "S003",
    "神戸元町": "S004",
    "西宮北口": "S005",
}

# CSV 店舗名一覧(ファイル名検出用)
STORE_NAMES = list(STORE_MAP.keys())


def detect_csv_files():
    """~/Downloads/ から対象CSVを抽出
    受付ルール:
    - 「{店舗名}.csv」または「MMDD{店舗名}.csv」(MMDDは4桁ちょうど)のみ採用
    - 「YYYYMM{店舗名}.csv」(6桁プレフィクス=過去年月)は **拒絶**
    - 同一店舗で複数該当する場合は mtime 最新を採用
    """
    found = {}  # store_jp -> (path, mtime)
    if not DOWNLOADS.exists():
        return []
    pat = re.compile(r"^(\d{0,4})(.+)\.csv$")
    for f in DOWNLOADS.glob("*.csv"):
        m = pat.match(f.name)
        if not m: continue
        prefix, body = m.group(1), m.group(2)
        # 5桁以上の数字プレフィクスは拒絶(202604川越.csv など)
        if prefix and len(prefix) > 4: continue
        # 店舗名検出
        for sname in STORE_NAMES:
            if sname in body:
                mt = f.stat().st_mtime
                if sname not in found or mt > found[sname][1]:
                    found[sname] = (f, mt)
                break
    return [(p, s) for s, (p, _) in found.items()]


def parse_int(s):
    if not s: return 0
    try:
        return int(str(s).replace(",", "").replace("¥", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return 0


def read_csv(path):
    """Shift-JIS CSVを読んで dict にする"""
    text = path.read_bytes().decode("cp932", errors="replace")
    reader = list(csv.reader(text.splitlines()))
    if len(reader) < 2:
        return None
    header = reader[0]
    row = reader[1]  # 1店舗1行
    return dict(zip(header, row))


def update_jisseki_sheet(sh, updates: dict, year_month: str, period: str):
    """⑦月次店舗実績シートの (year_month, period, store_id) 行を作成・更新

    updates: {store_id: {sales: int, customers: int, newcomers: int, ...}}
    """
    ws = sh.worksheet("⑦月次店舗実績")
    all_v = ws.get_all_values()
    header = all_v[0]
    COL = {h: i for i, h in enumerate(header)}

    n_changed = 0
    for store_id, d in updates.items():
        # 既存行を探す
        target_row_idx = None
        for i, row in enumerate(all_v[1:], start=2):
            if (len(row) > COL['店舗ID']
                    and row[COL['年月']] == year_month
                    and row[COL['期間']] == period
                    and row[COL['店舗ID']] == store_id):
                target_row_idx = i
                break

        store_name_jp = {
            "S001": "川越店", "S002": "大宮店", "S003": "高崎店",
            "S004": "神戸元町店", "S005": "西宮北口店",
        }[store_id]

        if target_row_idx is None:
            # 新規行を末尾に追加
            new_row = [""] * len(header)
            new_row[COL['年月']] = year_month
            new_row[COL['期間']] = period
            new_row[COL['店舗ID']] = store_id
            new_row[COL['店舗名']] = store_name_jp
            new_row[COL['売上(税抜)']] = d['sales_net']
            if '新規数' in COL: new_row[COL['新規数']] = d.get('newcomers', '')
            ws.append_row(new_row, value_input_option="USER_ENTERED")
            n_changed += 1
            print(f"  ➕ {year_month} {period} {store_name_jp}: 新規追加 売上(税抜)={d['sales_net']:,}")
        else:
            # 売上(税抜) + 新規数を更新(他列は保持)
            ws.update_cell(target_row_idx, COL['売上(税抜)'] + 1, d['sales_net'])
            if '新規数' in COL:
                ws.update_cell(target_row_idx, COL['新規数'] + 1, d.get('newcomers', 0))
            n_changed += 1
            print(f"  ✏️  {year_month} {period} {store_name_jp}: 更新 売上(税抜)={d['sales_net']:,}")
    return n_changed


def main():
    print(f"📥 CSVローダー開始: {datetime.now()}")
    csv_files = detect_csv_files()
    if not csv_files:
        print("ℹ️ ~/Downloads/ に対象CSVなし")
        return 0

    # 各CSVから店舗データ抽出
    now = datetime.now()
    year_month = now.strftime("%Y-%m")
    period = "月中(1-15日)" if now.day <= 15 else "月末(1-月末)"

    updates = {}
    processed_files = []
    for f, store_jp in csv_files:
        store_id = STORE_MAP[store_jp]
        d = read_csv(f)
        if not d:
            print(f"  ⚠️ 読込失敗: {f.name}")
            continue

        # 売上(税抜): 「役務売上」(レッスン売上)を採用
        # ※ ★総売上 = 役務売上 + 店販売上 + 施術売上 等の総合
        # ※ 役務売上 = レッスン提供分(税抜)
        sales_net = parse_int(d.get("役務売上", 0))
        newcomers = parse_int(d.get("新規", 0))
        customers = parse_int(d.get("客数", 0))

        updates[store_id] = {
            "sales_net": sales_net,
            "newcomers": newcomers,
            "customers": customers,
            "store_jp": store_jp,
        }
        processed_files.append(f)
        print(f"  📊 {store_jp}: 売上(税抜)={sales_net:,} 新規={newcomers} 客数={customers}")

    if not updates:
        print("ℹ️ 更新対象なし")
        return 0

    # スプシ更新
    print(f"\n💾 ⑦月次店舗実績シート更新 (年月={year_month}, 期間={period})")
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    n = update_jisseki_sheet(sh, updates, year_month, period)
    print(f"  ✅ {n}店舗 更新")

    # 処理済みCSVを移動
    processed_subdir = PROCESSED_DIR / year_month
    processed_subdir.mkdir(parents=True, exist_ok=True)
    for f in processed_files:
        dest = processed_subdir / f.name
        # 同名ファイルがあれば日時サフィックス付与
        if dest.exists():
            dest = processed_subdir / f"{f.stem}_{now.strftime('%H%M%S')}{f.suffix}"
        shutil.move(str(f), str(dest))
        print(f"  📦 移動: {f.name} → data/sales/processed/{year_month}/")

    # Slackに即時実績進捗を送信
    print(f"\n📡 Slackに実績速報を送信...")
    try:
        result = subprocess.run(
            ["/usr/bin/env", "python3", str(PROJECT_ROOT / "src" / "alert_sender.py")],
            capture_output=True, text=True, timeout=120
        )
        if "送信成功" in result.stdout:
            print("  ✅ Slack送信完了")
        else:
            print(f"  ⚠️ {result.stdout[-200:]}")
    except Exception as e:
        print(f"  ❌ alert_sender失敗: {e}")

    print(f"\n🎉 完了: {datetime.now()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
