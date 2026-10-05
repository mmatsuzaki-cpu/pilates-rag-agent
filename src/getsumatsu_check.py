"""getsumatsu_check.py

ピラティス月末業務の照合（読み取り専用・スプシには書かない）。
集計表の契約者リスト／解約報告／LTVから対象月の数字を出し、
スタッフ入力（LTV C52:D54）とのズレ・解約報告のチェック漏れを一覧にする。

ルール（2026-10-04 松崎さん確定）:
- 退会月 = 最終支払日の翌月（8/15最終引落 → 9月退会）
- 年払い人数 = コース名に「年」が付いている在籍者
- 解約報告のチェック: 通常は3つ（申請フォーム/引落停止/カード削除）必須、年払いは申請フォームのみ
  （解約報告のコース欄が「月1」でもメモに「年払い」とある人は年払い扱い）

使い方:
    python3 src/getsumatsu_check.py                 # 前月分・神戸元町
    python3 src/getsumatsu_check.py --month 2026-10 --store 神戸元町
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client
from store_summary_reader import (STORE_SUMMARIES, INACTIVE_COURSE_KEYWORDS,
                                  ltv_sheet_name, parse_ymd, safe_int, with_retry)

CHECK_NAMES = ["解約申請フォーム", "引落停止処理", "カード削除依頼"]


def prev_month(y, m):
    return (y, m - 1) if m > 1 else (y - 1, 12)


def next_month(y, m):
    return (y, m + 1) if m < 12 else (y + 1, 1)


def ym_label(y, m):
    """契約者リスト「来店 年/月」の表記 (例: 26/10)"""
    return f"{y % 100}/{m}"


def check_store(gc, store, y, m):
    sh = gc.open_by_key(store["ssid"])
    ny, nm = next_month(y, m)
    py, pm = prev_month(y, m)

    # 契約者リスト: 月末会員数・年払い・入会数
    cl = with_retry(sh.worksheet("契約者リスト").get_all_values)
    hdr = [h.strip() for h in cl[0]]
    i_visit = hdr.index("来店 年/月")
    members = nenbarai = joins = 0
    for r in cl[1:]:
        if len(r) <= i_visit or not r[4].strip():
            continue
        course, visit = r[4].strip(), r[i_visit].strip()
        if visit == ym_label(y, m):
            joins += 1
        if any(k in course for k in INACTIVE_COURSE_KEYWORDS):
            continue
        if visit == ym_label(ny, nm):  # 翌月入会は月末時点の会員に入れない
            continue
        members += 1
        if "年" in course:
            nenbarai += 1

    # 解約報告: 当月退会（最終支払が前月）とチェック漏れ
    kv = with_retry(sh.worksheet("解約報告").get_all_values)
    taikai, misses, no_date = [], [], []
    last = max((i for i, r in enumerate(kv, 1) if len(r) > 2 and r[2].strip()), default=0)
    for i, r in enumerate(kv[1:], 2):
        if len(r) < 8 or not r[2].strip():
            continue
        d = parse_ymd(r[3])
        memo = r[8] if len(r) > 8 else ""
        is_nen = "年" in r[4] or "年払" in memo
        if d and (d.year, d.month) == (py, pm):
            taikai.append(i)
            miss = [n for n, v in zip(CHECK_NAMES, r[5:8]) if v != "TRUE"]
            if is_nen:
                miss = [x for x in miss if x == "解約申請フォーム"]
            if miss:
                misses.append(f"行{i} {r[1]} {r[2]}（最終支払{r[3]}・{r[4]}）→ {'・'.join(miss)} 未チェック")
        elif not d and is_nen and i > last - 20:
            no_date.append(f"行{i} {r[1]} {r[2]}（{r[4]}・最終支払日なし）{memo[:30]}")

    # LTV: スタッフ入力値と契約数
    ltv = sh.worksheet(ltv_sheet_name(y, m))
    vals = with_retry(ltv.get, "D52:D54")
    staff = [safe_int(v[0]) if v else None for v in vals] + [None] * (3 - len(vals))
    contracts = safe_int((with_retry(ltv.get, "G4") or [[0]])[0][0])
    prev_members = None
    try:
        pv = with_retry(sh.worksheet(ltv_sheet_name(py, pm)).get, "D52")
        prev_members = safe_int(pv[0][0]) if pv and pv[0] else None
    except Exception:
        pass

    return dict(store=store["name"], y=y, m=m, members=members, taikai=len(taikai),
                nenbarai=nenbarai, joins=joins, contracts=contracts, staff=staff,
                prev_members=prev_members, misses=misses, no_date=no_date)


def report(d):
    y, m = d["y"], d["m"]
    lines = [f"■ {d['store']} {y}年{m}月 月末照合"]
    labels = ["月末時点の会員数", "今月の退会数", "年払い人数"]
    calc = [d["members"], d["taikai"], d["nenbarai"]]
    ok = True
    for lab, c, s in zip(labels, calc, d["staff"]):
        if s is None:
            lines.append(f"  {lab}: 計算 {c} / スタッフ入力 なし")
        else:
            mark = "一致" if s == c else f"ズレ {s - c:+d}"
            ok &= s == c
            lines.append(f"  {lab}: 計算 {c} / スタッフ入力 {s} → {mark}")
    lines.append(f"  入会数: 契約者リスト {d['joins']} / LTV契約数 {d['contracts']}"
                 + ("" if d["joins"] == d["contracts"] else " → ズレ"))
    if d["prev_members"] is not None:
        flow = d["prev_members"] + d["joins"] - d["taikai"]
        lines.append(f"  増減チェック: 前月末{d['prev_members']} + 入会{d['joins']} − 退会{d['taikai']}"
                     f" = {flow}（計算の会員数 {d['members']}、差 {d['members'] - flow:+d}）")
    lines.append(f"  チェック漏れ（当月退会者）: {len(d['misses'])}件")
    lines += [f"    {x}" for x in d["misses"]]
    if d["no_date"]:
        lines.append("  最終支払日が空欄の年払い（退会月の確認が必要）:")
        lines += [f"    {x}" for x in d["no_date"]]
    rate = d["taikai"] / d["members"] * 100 if d["members"] else 0
    lines += ["", "--- トークノート下書き（【月末業務】入退会報告用）---",
              f"【{d['store']}店】", "_______________________", "",
              f"{m}月入会数：{d['joins']}名", f"{m}月退会数：{d['taikai']}名",
              f"{m}月末会員数：{d['members']}名",
              f"{m}月退会率(=退会数/会員数×100)：{rate:.1f}%", "",
              "〈年払い会員〉", "途中返金：名", "更新済：名", "　└（月　名）（年　名）", "卒業：名", "",
              "＜チェックリスト＞", "未回収リスト確認：", "翌月分の集計表シートの更新：",
              "LTVシートに会員数・退会数追加：", f"退会者の対応：{'◎' if not d['misses'] else '×'}",
              "入会者の会員ランク・住所・反響入力：", "_______________________"]
    return "\n".join(lines), ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM（省略時は前月）")
    ap.add_argument("--store", default="神戸元町")
    a = ap.parse_args()
    if a.month:
        y, m = map(int, a.month.split("-"))
    else:
        t = date.today()
        y, m = prev_month(t.year, t.month)
    store = next(s for s in STORE_SUMMARIES if s["name"] == a.store)
    text, _ = report(check_store(get_gspread_client(), store, y, m))
    print(text)


if __name__ == "__main__":
    main()
