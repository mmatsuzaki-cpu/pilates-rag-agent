"""personal_contract_updater.py

各店舗集計表のLTVシートからスタッフ個人の新規数(母数)・契約数を取得し、
「個別契約率」スプシの店舗別シートに月次で転記する。

対象スプシ: 個別契約率 (1dOktCbv1opoV_3CVtRoJcJ1Ux_h-PkrkMZH9l3ZUD-Y)
  - シート = 店舗名(川越/大宮/高崎/神戸元町/西宮北口)
  - 行1 = スタッフ名(3列ごとのブロック先頭) / 行2 = 新規数/入会数/契約率
  - A列 = 月ラベル("YYYY年M月") + "合計/平均" 行
  - 契約率セル・合計/平均行は既存の数式が入っているため触らない
    → 書き込むのは 新規数/入会数 の2セルのみ
  - LTVに居てシートに列が無いスタッフは右端に3列ブロックを自動追加
    (隣のブロックを PASTE_NORMAL でコピー → 月行の値だけクリア → 名前上書き)

実行:
  python src/personal_contract_updater.py                    # 前月分
  python src/personal_contract_updater.py --year 2026 --month 5
  python src/personal_contract_updater.py --auto             # JST 1-5日のみ前月分を実行
"""

import argparse
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client
from store_summary_reader import (
    STORE_SUMMARIES, with_retry, find_sheet, ltv_sheet_name, reiwa_year, safe_int,
)

TARGET_SSID = "1dOktCbv1opoV_3CVtRoJcJ1Ux_h-PkrkMZH9l3ZUD-Y"
JST = timezone(timedelta(hours=9))
MONTH_LABEL_RE = re.compile(r"^\d{4}年\d{1,2}月$")


def col_letter(n: int) -> str:
    """1-based 列番号 → A1形式の列文字"""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def fetch_staff_ltv(gc, store: dict, year: int, month: int):
    """集計表LTVシートからスタッフ別 [{name, newcomers, contracts}] を取得

    レイアウトは store_summary_reader.get_store_summary と同一
    (J列=index9 以降 8列刻み / row2=名前 / row3=項目 / row4=値)。
    LTVシートが未作成なら None を返す。
    """
    sh = with_retry(gc.open_by_key, store["ssid"])
    ltv = find_sheet(sh, [ltv_sheet_name(year, month),
                          f"R{reiwa_year(year)}.{month}月LTV "])
    if ltv is None:
        return None
    rows = with_retry(ltv.get, "A2:CK4")
    r2 = rows[0] if len(rows) > 0 else []
    r3 = rows[1] if len(rows) > 1 else []
    r4 = rows[2] if len(rows) > 2 else []
    staff = []
    c = 9
    while c < len(r3):
        name = r2[c].strip() if c < len(r2) else ""
        if name and not name.startswith("スタッフ"):
            hdr = [r3[c + k].strip() if c + k < len(r3) else "" for k in range(8)]
            val = [r4[c + k].strip() if c + k < len(r4) else "" for k in range(8)]
            nv = safe_int(val[hdr.index("新規数")]) if "新規数" in hdr else 0
            kv = safe_int(val[hdr.index("契約数")]) if "契約数" in hdr else 0
            if nv > 0 or kv > 0:
                staff.append({"name": name, "newcomers": nv, "contracts": kv})
        c += 8
    return staff


def add_staff_block(sh, ws, row1: list, col_a: list, name: str) -> int:
    """右端に3列のスタッフブロックを追加し、開始列(1-based)を返す

    隣接する最後のブロックを書式・数式ごとコピー(PASTE_NORMAL)し、
    月行の 新規数/入会数 の値だけクリアして名前を差し替える。
    """
    starts = [i + 1 for i, v in enumerate(row1) if i >= 1 and str(v).strip()]
    if not starts:
        raise RuntimeError(f"{ws.title}: 既存スタッフブロックが見つからない")
    last_start = max(starts)
    new_start = last_start + 3

    # グリッド幅の確保
    need_cols = new_start + 2
    if ws.col_count < need_cols:
        with_retry(ws.add_cols, need_cols - ws.col_count)

    # 隣のブロックを丸ごとコピー(数式の相対参照は自動で+3列シフトされる)
    n_rows = max(len(col_a), 3)
    with_retry(sh.batch_update, {"requests": [{
        "copyPaste": {
            "source": {
                "sheetId": ws.id,
                "startRowIndex": 0, "endRowIndex": n_rows,
                "startColumnIndex": last_start - 1, "endColumnIndex": last_start + 2,
            },
            "destination": {
                "sheetId": ws.id,
                "startRowIndex": 0, "endRowIndex": n_rows,
                "startColumnIndex": new_start - 1, "endColumnIndex": new_start + 2,
            },
            "pasteType": "PASTE_NORMAL",
        }
    }]})

    # 月行の値セル(新規数/入会数)をクリア + 行1に新スタッフ名
    l1, l2 = col_letter(new_start), col_letter(new_start + 1)
    updates = [{"range": f"{col_letter(new_start)}1", "values": [[name]]}]
    for i, label in enumerate(col_a):
        if MONTH_LABEL_RE.match(str(label).strip()):
            updates.append({"range": f"{l1}{i + 1}:{l2}{i + 1}", "values": [["", ""]]})
    with_retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    print(f"    ➕ 新スタッフ列追加: {name} ({col_letter(new_start)}列〜)")
    return new_start


def update_store_sheet(sh, store_name: str, staff: list, year: int, month: int) -> bool:
    """個別契約率スプシの1店舗シートに指定月のスタッフ別 新規数/入会数 を書き込む"""
    try:
        ws = sh.worksheet(store_name)
    except Exception:
        print(f"    ⚠️ シート「{store_name}」が無いためスキップ")
        return False

    label = f"{year}年{month}月"
    col_a = with_retry(ws.col_values, 1)
    row_idx = None
    for i, v in enumerate(col_a):
        if str(v).strip() == label:
            row_idx = i + 1
            break
    if row_idx is None:
        print(f"    ⚠️ {store_name}: 行「{label}」が見つからない(月行の追加が必要) → スキップ")
        return False

    row1 = with_retry(ws.row_values, 1)
    blocks = {str(v).strip(): i + 1 for i, v in enumerate(row1) if i >= 1 and str(v).strip()}

    # 1) 列が無い新スタッフのブロックを先に追加
    for s in staff:
        if s["name"] not in blocks:
            start = add_staff_block(sh, ws, row1, col_a, s["name"])
            blocks[s["name"]] = start
            # add_cols後のcol_count等キャッシュが古くなるためwsごと取り直す
            ws = with_retry(sh.worksheet, store_name)
            row1 = with_retry(ws.row_values, 1)

    # 2) 対象月行の既存数式を確認(契約率セルが空なら数式を補完するため)
    max_col = max(blocks.values()) + 2
    got = with_retry(ws.get, f"A{row_idx}:{col_letter(max_col)}{row_idx}",
                     value_render_option="FORMULA")
    row_f = got[0] if got else []

    # 3) 新規数/入会数 + (必要なら)契約率数式 を書き込み
    updates = []
    for s in staff:
        start = blocks[s["name"]]
        updates.append({
            "range": f"{col_letter(start)}{row_idx}:{col_letter(start + 1)}{row_idx}",
            "values": [[s["newcomers"], s["contracts"]]],
        })
        rate_col = start + 2
        rate_cell = str(row_f[rate_col - 1]).strip() if rate_col - 1 < len(row_f) else ""
        if not rate_cell:
            c1, c2 = col_letter(start), col_letter(start + 1)
            updates.append({
                "range": f"{col_letter(rate_col)}{row_idx}",
                "values": [[f"=IFERROR({c2}{row_idx}/{c1}{row_idx},0)"]],
            })
    if updates:
        with_retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    for s in staff:
        rate = s["contracts"] / s["newcomers"] * 100 if s["newcomers"] else 0
        print(f"    {s['name']}: 母数{s['newcomers']} 契約{s['contracts']} ({rate:.0f}%)")
    return True


def run(year: int, month: int) -> int:
    print(f"🧮 個別契約率 転記: {year}年{month}月")
    gc = get_gspread_client()
    target_sh = with_retry(gc.open_by_key, TARGET_SSID)

    errors = 0
    for i, store in enumerate(STORE_SUMMARIES):
        if i > 0:
            time.sleep(15)  # readクォータ分散(store_summary_reader と同じ)
        print(f"  {store['name']}...")
        try:
            staff = fetch_staff_ltv(gc, store, year, month)
            if staff is None:
                print(f"    ⚠️ LTVシート({ltv_sheet_name(year, month)})未作成 → スキップ")
                continue
            if not staff:
                print("    (実績のあるスタッフなし)")
                continue
            if not update_store_sheet(target_sh, store["name"], staff, year, month):
                errors += 1
        except Exception as e:
            print(f"    ❌ {e}")
            errors += 1
    return errors


def main():
    p = argparse.ArgumentParser(description="スタッフ個別契約率の月次転記")
    p.add_argument("--year", type=int)
    p.add_argument("--month", type=int)
    p.add_argument("--auto", action="store_true",
                   help="JST 1-5日のみ前月分を実行(それ以外は何もしない)")
    args = p.parse_args()

    now = datetime.now(JST)
    if args.auto and not (1 <= now.day <= 5):
        print(f"⏭️ --auto: 本日{now.day}日は月初(1-5日)ではないためスキップ")
        return 0

    if args.year and args.month:
        year, month = args.year, args.month
    else:
        # デフォルト: 前月(確定値)
        year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)

    errors = run(year, month)
    if errors:
        print(f"⚠️ {errors}店舗でエラー/スキップあり")
    else:
        print("✅ 完了")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
