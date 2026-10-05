"""create_next_month_tabs.py

ピラティス7店舗の集計表に、翌月分の月次シート（R{令和}.{月}月問い合わせ数 / R{令和}.{月}月LTV）を自動作成する。

- launchd で毎日起動 → 27日以降で翌月シートが無ければ作成（冪等。既にあればスキップ）
  - 27日〜月末にMacが寝ていた場合の救済として、1〜3日は「当月シート」が無ければ作成する
- 複製元は前月のシート（例: 11月分を作るときは R8.10月〜）。複製なので書式・数式・プルダウン・条件付き書式は維持
  - 保護範囲は duplicateSheet で複製されないので、スクリプトでコピーする
- クリアするもの:
  - LTV: 「日付」見出し行より下の手入力（数式は残す）。スタッフ名(2行目)は引き継ぐ
  - 問い合わせ数: 2行目以降・E列以降の数値の手入力（数式・文字は残す）
- 書き換えるもの:
  - LTV の数式内の「R*.*月問い合わせ数」参照 → 新しい月の問い合わせ数シート
  - 問い合わせ数 E1 の月ラベル（「10月」など）→ 新しい月
- 環境変数: FORCE=1(日付に関係なく翌月分を作成) / ONLY_STORE=店舗名 / FAKE_TODAY=YYYY-MM-DD /
            CHECK=1(ドライラン) / NAME_PREFIX=テスト用のシート名接頭辞
"""

import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client
from store_summary_reader import STORE_SUMMARIES, reiwa_year, with_retry
from gspread.utils import rowcol_to_a1

JST = timezone(timedelta(hours=9))
START_DAY = 27          # この日以降に翌月分を作る
CATCHUP_UNTIL_DAY = 3   # 1〜3日は当月分が無ければ作る
KINDS = ["問い合わせ数", "LTV"]   # 問い合わせ数を先に作り、LTVの参照先にする
INQ_REF = re.compile(r"'?R\d+\.\d+月問い合わせ数\s*'?!")
NUMERIC = re.compile(r"^[\s\d０-９,.¥%\-]+$")


def log(*a):
    print(datetime.now(JST).strftime("[%Y-%m-%d %H:%M]"), *a, flush=True)


def tab_name(year, month, kind):
    return f"R{reiwa_year(year)}.{month}月{kind}"


def prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def target_month(today):
    """作成対象の年月。対象外の日は None"""
    if today.day >= START_DAY or os.environ.get("FORCE") == "1":
        return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    if today.day <= CATCHUP_UNTIL_DAY:
        return today.year, today.month
    return None


def find_title(titles, name):
    """末尾スペース付きの既存シート名にも当てる"""
    for t in titles:
        if t.strip() == name:
            return t
    return None


def is_formula(c):
    return isinstance(c, str) and c.startswith("=")


def copy_protection(sh, prots, dst_id):
    reqs = []
    for pr in prots:
        npr = {"range": dict(pr.get("range", {}), sheetId=dst_id),
               "warningOnly": pr.get("warningOnly", False)}
        if pr.get("description"):
            npr["description"] = pr["description"]
        if pr.get("editors") and not npr["warningOnly"]:
            npr["editors"] = {"users": pr["editors"].get("users", []),
                              "groups": pr["editors"].get("groups", [])}
        if pr.get("unprotectedRanges"):
            npr["unprotectedRanges"] = [dict(u, sheetId=dst_id) for u in pr["unprotectedRanges"]]
        reqs.append({"addProtectedRange": {"protectedRange": npr}})
    if reqs:
        with_retry(sh.batch_update, {"requests": reqs})
    return len(reqs)


def build_updates_ltv(values, inq_title):
    """LTV: 日付見出しより下の手入力をクリア＋問い合わせ数参照を差し替え"""
    start = 36  # 0始まり。見つからなければ37行目から
    for i, r in enumerate(values[:60]):
        if any(str(c).strip() == "日付" for c in r):
            start = i + 1
            break
    ups = []
    for i, r in enumerate(values):
        for j, c in enumerate(r):
            if c == "":
                continue
            a1 = rowcol_to_a1(i + 1, j + 1)
            if is_formula(c):
                if INQ_REF.search(c):
                    ups.append({"range": a1, "values": [[INQ_REF.sub(f"'{inq_title}'!", c)]]})
            elif i >= start:
                ups.append({"range": a1, "values": [[""]]})
    return ups


def build_updates_inq(values, month):
    """問い合わせ数: 月ラベル差し替え＋E列以降の数値入力をクリア"""
    ups = []
    for i, r in enumerate(values):
        for j, c in enumerate(r):
            if c == "" or is_formula(c):
                continue
            a1 = rowcol_to_a1(i + 1, j + 1)
            if i == 0:
                if re.fullmatch(r"\s*\d*月\s*", str(c)):
                    ups.append({"range": a1, "values": [[f"{month}月"]]})
            elif j >= 4 and (isinstance(c, (int, float)) or NUMERIC.match(str(c))):
                ups.append({"range": a1, "values": [[""]]})
    return ups


def process_store(gc, store, ty, tm, dry, prefix):
    sh = gc.open_by_key(store["ssid"])
    meta = with_retry(sh.fetch_sheet_metadata, {
        "fields": "sheets(properties(sheetId,title,index),"
                  "protectedRanges(range,description,warningOnly,editors,unprotectedRanges))"})
    sheets = {s["properties"]["title"]: s for s in meta["sheets"]}
    titles = list(sheets)
    py, pm = prev_month(ty, tm)
    created = {}
    for kind in KINDS:
        new = prefix + tab_name(ty, tm, kind)
        if find_title(titles, new):
            log(f"  {store['name']}: {new} は作成済み → スキップ")
            created[kind] = find_title(titles, new)
            continue
        src = find_title(titles, tab_name(py, pm, kind))
        if not src:
            log(f"  ⚠️ {store['name']}: 複製元 {tab_name(py, pm, kind)} が見つからない → スキップ")
            continue
        sp = sheets[src]["properties"]
        if dry:
            log(f"  [CHECK] {store['name']}: {src.strip()} → {new}")
            created[kind] = new
            continue
        res = with_retry(sh.batch_update, {"requests": [{"duplicateSheet": {
            "sourceSheetId": sp["sheetId"], "insertSheetIndex": sp["index"],
            "newSheetName": new}}]})
        new_id = res["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
        ws = sh.get_worksheet_by_id(new_id)
        values = with_retry(ws.get, value_render_option="FORMULA")
        if kind == "LTV":
            inq = created.get("問い合わせ数") or find_title(titles, prefix + tab_name(ty, tm, "問い合わせ数"))
            ups = build_updates_ltv(values, inq or new.replace("LTV", "問い合わせ数"))
        else:
            ups = build_updates_inq(values, tm)
        if ups:
            with_retry(ws.batch_update, ups, value_input_option="USER_ENTERED")
        # 保護は書き込みの後に付ける（先に付けると編集者外のセルに書けないため）
        try:
            np_ = copy_protection(sh, sheets[src].get("protectedRanges", []), new_id)
        except Exception as e:
            np_ = f"失敗({e})"
        log(f"  ✅ {store['name']}: {src.strip()} → {new}（更新{len(ups)}セル・保護{np_}件）")
        created[kind] = new
        time.sleep(2)
    return created


def main():
    ft = os.environ.get("FAKE_TODAY")
    today = date.fromisoformat(ft) if ft else datetime.now(JST).date()
    tgt = target_month(today)
    if not tgt:
        log(f"{today}: 作成日ではないのでスキップ（{START_DAY}日〜月末・1〜{CATCHUP_UNTIL_DAY}日が対象）")
        return 0
    ty, tm = tgt
    dry = os.environ.get("CHECK") == "1"
    only = os.environ.get("ONLY_STORE")
    prefix = os.environ.get("NAME_PREFIX", "")
    log(f"=== {ty}年{tm}月分の集計表シート作成 {'(CHECK)' if dry else ''}")
    gc = get_gspread_client()
    errors = 0
    for store in STORE_SUMMARIES:
        if only and store["name"] != only:
            continue
        try:
            process_store(gc, store, ty, tm, dry, prefix)
        except Exception as e:
            errors += 1
            log(f"  ❌ {store['name']}: {e}")
    log(f"=== 完了（エラー{errors}店舗）")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
