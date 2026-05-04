"""sales_csv_loader.py

~/Documents/pilates_sales/ に置かれた店舗別売上CSV(Shift-JIS)を検出 →
⑦月次店舗実績シートの「当月 / 月中(1-15日)」行を作成・更新 →
処理後はalert_sender.pyを呼んでSlack #ピラティス_実績進捗 に速報送信。

【ファイル名は何でもOK】(2026-05-04)
- 店舗判別はCSV2行目1列目「La pilates 〜」から行う
- 例: acc-1777853917.csv / 0503川越.csv / etc.

CSV内のデータは「月初〜CSV作成日まで」の累積値という前提。
処理後はファイルを data/sales/processed/{YYYY-MM}/ に移動して重複処理防止。

cron 1時間間隔で実行 → CSV置けば最大1時間以内に反映。
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

# 売上CSV投入フォルダ(2026-05-04 ~/Downloads/ から専用フォルダに移行)
INBOX = Path.home() / "Documents" / "pilates_sales"
PROJECT_ROOT = Path(__file__).parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "sales" / "processed"

# CSV 店舗名(部分一致用) → store_id
# 例: CSV内「La pilates 川越」→「川越」マッチ → S001
STORE_MAP = {
    "川越":     "S001",
    "大宮":     "S002",
    "高崎":     "S003",
    "神戸元町": "S004",
    "西宮北口": "S005",
}

STORE_NAMES = list(STORE_MAP.keys())


def detect_store_from_csv(path):
    """CSV2行目の1列目「La pilates 〜」から店舗名(川越/大宮/高崎/神戸元町/西宮北口)を検出"""
    try:
        text = path.read_bytes().decode("cp932", errors="replace")
        reader = list(csv.reader(text.splitlines()))
        if len(reader) < 2: return None
        store_name_jp = reader[1][0] if reader[1] else ""  # 例: "La pilates 川越"
        for sname in STORE_NAMES:
            if sname in store_name_jp:
                return sname
    except Exception:
        return None
    return None


def detect_csv_files():
    """INBOX フォルダ内の全CSVを走査 → CSV内容から店舗判別
    - ファイル名は何でもOK(店舗判別はCSV中身の「La pilates 〜」から)
    - 同一店舗で複数該当する場合は mtime 最新を採用
    """
    found = {}  # store_jp -> (path, mtime)
    if not INBOX.exists():
        return []
    for f in INBOX.glob("*.csv"):
        store = detect_store_from_csv(f)
        if not store: continue
        mt = f.stat().st_mtime
        if store not in found or mt > found[store][1]:
            found[store] = (f, mt)
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


def update_jisseki_sheet(sh, updates: dict, year_month: str, period: str, summary: dict = None):
    """⑦月次店舗実績シートの (year_month, period, store_id) 行を作成・更新

    updates: {store_id: {sales_net, newcomers, customers, ...}} ← CSVから
    summary: {store_id: {newcomers, contracts, contract_rate, cancels, referrals, members}} ← 集計表から(任意)
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

        # 集計表データ(あれば使う)
        s = (summary or {}).get(store_id, {})

        # バッチ更新用: 1行分の値を組み立て
        # 列順: 年月,期間,店舗ID,店舗名,売上(税抜),利益(税抜),会員数,契約率,契約数,新規数,解約数,紹介数,Google口コミ,HPB口コミ,口コミ合計
        if target_row_idx is None:
            new_row = [""] * len(header)
            new_row[COL['年月']] = year_month
            new_row[COL['期間']] = period
            new_row[COL['店舗ID']] = store_id
            new_row[COL['店舗名']] = store_name_jp
            new_row[COL['売上(税抜)']] = d['sales_net']
            if s:
                new_row[COL['会員数']] = s.get('members', '')
                new_row[COL['契約率']] = s.get('contract_rate', '')
                new_row[COL['契約数']] = s.get('contracts', '')
                new_row[COL['新規数']] = s.get('newcomers', d.get('newcomers', ''))
                new_row[COL['解約数']] = s.get('cancels', '')
                new_row[COL['紹介数']] = s.get('referrals', '')
            else:
                new_row[COL['新規数']] = d.get('newcomers', '')
            ws.append_row(new_row, value_input_option="USER_ENTERED")
            n_changed += 1
            extra = (f" 会員={s.get('members')} 契約率={s.get('contract_rate', 0)*100:.0f}%" if s else "")
            print(f"  ➕ {year_month} {period} {store_name_jp}: 新規追加 売上={d['sales_net']:,}{extra}")
        else:
            # 1行一括更新(範囲指定でAPI呼び出しを最小化 → quota節約)
            row_values = list(all_v[target_row_idx - 1])  # 0-indexed
            # 必要な長さに揃える
            while len(row_values) < len(header):
                row_values.append("")
            row_values[COL['売上(税抜)']] = d['sales_net']
            if s:
                row_values[COL['会員数']] = s.get('members', 0)
                row_values[COL['契約率']] = s.get('contract_rate', 0)
                row_values[COL['契約数']] = s.get('contracts', 0)
                row_values[COL['新規数']] = s.get('newcomers', 0)
                row_values[COL['解約数']] = s.get('cancels', 0)
                row_values[COL['紹介数']] = s.get('referrals', 0)
            else:
                row_values[COL['新規数']] = d.get('newcomers', 0)
            # A列〜最終列まで一括更新
            last_col_letter = chr(ord('A') + len(header) - 1)
            range_name = f"A{target_row_idx}:{last_col_letter}{target_row_idx}"
            ws.update(values=[row_values], range_name=range_name, value_input_option="USER_ENTERED")
            n_changed += 1
            extra = (f" 会員={s.get('members')} 契約率={s.get('contract_rate', 0)*100:.0f}% 解約={s.get('cancels')}" if s else "")
            print(f"  ✏️  {year_month} {period} {store_name_jp}: 更新 売上={d['sales_net']:,}{extra}")
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

        # 売上(税込): 「★支払合計」から「売掛金」を引く(2026-05-04 松崎さん確定)
        # ※ ★支払合計 = 顧客から受け取った支払い手段の合計(現金/カード/サブスク/etc)
        # ※ 売掛金 = 当期未入金分(後日入金される分)
        #   → 引くことで「実入金ベースの売上」になる
        # ※ CSVは税込ベースで、スプシ側の関数で自動的に税抜・利益が計算される
        payments_total = parse_int(d.get("★支払い合計", 0))
        accounts_receivable = parse_int(d.get("売掛金", 0))
        sales_net = payments_total - accounts_receivable  # 売掛金分を控除
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

    # 集計表から契約率/会員数/解約数/紹介数を取得(可能なら)
    summary = None
    try:
        import time
        from store_summary_reader import get_all_stores_summary
        y, m = year_month.split("-")
        print(f"\n📥 集計表から契約率・会員数・解約数を取得 ({year_month})")
        summary = get_all_stores_summary(int(y), int(m))
        # 集計表取得で大量read消費 → ⑦シート更新前にquotaリセット待ち
        print("  ⏱️ Sheets API quota待ち 70秒...")
        time.sleep(70)
    except Exception as e:
        print(f"  ⚠️ 集計表取得失敗 (売上のみ更新): {e}")

    # スプシ更新
    print(f"\n💾 ⑦月次店舗実績シート更新 (年月={year_month}, 期間={period})")
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    n = update_jisseki_sheet(sh, updates, year_month, period, summary=summary)
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

    # Slack送信は22時の run_daily.sh に任せる(CSV処理ごとの@channelスパム防止)
    # 必要なら手動で `python3 src/alert_sender.py` 実行

    print(f"\n🎉 完了: {datetime.now()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
