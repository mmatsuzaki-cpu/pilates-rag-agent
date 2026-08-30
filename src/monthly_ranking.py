"""monthly_ranking.py

月間ランキング(レッスン数 / 契約率)を画像化して Slack #ピラティス_実績進捗 に配信。
毎月1日の朝9時に「前月分(確定値)」を配信する。

【データソース】
- 契約率 : 各店舗の集計表LTVシート(store_summary_reader) のスタッフ別 新規数/契約数
           → 全店横断。新規対応が MIN_DEN 件以上のスタッフのみ対象(母数1件の100%を弾く)
- レッスン数: hacomono 等からDLしたCSV
           data/lessons/YYYY-MM.csv を最優先で読む。無ければ ~/Downloads から
           当月ぶんらしきCSVを自動検出。列名は日本語ヘッダから自動判定。

使い方:
    python3 src/monthly_ranking.py                      # 前月分を配信
    python3 src/monthly_ranking.py --year 2026 --month 8
    python3 src/monthly_ranking.py --dry                # 送信せず内容表示
    python3 src/monthly_ranking.py --no-slack           # 画像生成のみ
    python3 src/monthly_ranking.py --lessons path.csv   # レッスンCSVを明示指定
    python3 src/monthly_ranking.py --auto               # 1-5日のみ実行(未配信なら)
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import PROJECT_ROOT, STORES
from store_summary_reader import get_all_stores_summary
from ranking_render import render_ranking_to_png

JST = timezone(timedelta(hours=9))

MIN_DEN = 5      # 契約率ランキングの対象: 新規対応がこの件数以上
TOP_N = 5        # 各ランキングの表示人数

STORE_NAME = {s["id"]: s["name"].replace("店", "") for s in STORES}
LESSON_DIR = PROJECT_ROOT / "data" / "lessons"
SENT_MARKER = PROJECT_ROOT / "data" / "ranking_sent.json"

# CSVのヘッダ判定に使うキーワード
NAME_KEYS = ("インストラクター", "担当", "スタッフ", "講師", "指導者", "staff", "instructor")
STORE_KEYS = ("店舗", "店名", "施設", "スタジオ", "shop", "store")
COUNT_KEYS = ("レッスン数", "本数", "回数", "コマ数", "実施数")


# ── レッスン数 (CSV) ────────────────────────────────────────
def _find_lesson_csv(year: int, month: int, explicit: str = None) -> Path:
    """レッスンCSVを探す (明示指定 → data/lessons/YYYY-MM.csv → Downloads)"""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    fixed = LESSON_DIR / f"{year}-{month:02d}.csv"
    if fixed.exists():
        return fixed
    dl = Path.home() / "Downloads"
    if dl.exists():
        pats = [f"{year}_{month:02d}", f"{year}-{month:02d}", f"{year}{month:02d}"]
        cands = [p for p in dl.glob("*.csv")
                 if any(k in p.name for k in ("lesson", "レッスン", "予約", "reserv"))
                 and any(t in p.name for t in pats)]
        if cands:
            return max(cands, key=lambda p: p.stat().st_mtime)
    return None


def _read_csv_rows(path: Path):
    """文字コードを判定して CSV を dict のリストで返す"""
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, encoding=enc) as fh:
                return list(csv.DictReader(fh)), enc
        except UnicodeDecodeError:
            continue
    return [], "unknown"


def _pick_col(header: list, keys: tuple) -> str:
    for h in header:
        if h and any(k in str(h).lower() for k in [k.lower() for k in keys]):
            return h
    return None


def load_lesson_ranking(year: int, month: int, explicit: str = None) -> tuple:
    """レッスン数ランキング [{name, store, value}] と 注記 を返す"""
    path = _find_lesson_csv(year, month, explicit)
    if not path:
        return [], "※レッスン数CSV未連携(data/lessons/{}-{:02d}.csv を置くと集計されます)".format(year, month)
    rows, enc = _read_csv_rows(path)
    if not rows:
        return [], f"※CSVを読めませんでした({path.name})"
    header = list(rows[0].keys())
    c_name = _pick_col(header, NAME_KEYS)
    c_store = _pick_col(header, STORE_KEYS)
    c_cnt = _pick_col(header, COUNT_KEYS)
    if not c_name:
        return [], f"※CSVに担当者の列が見つかりません({path.name})"

    agg = {}
    for r in rows:
        nm = str(r.get(c_name, "")).strip()
        if not nm:
            continue
        st = str(r.get(c_store, "")).strip() if c_store else ""
        st = re.sub(r"^La pilates\s*", "", st).replace("店", "")
        key = (nm, st)
        if c_cnt:
            try:
                v = float(str(r.get(c_cnt, 0)).replace(",", "").strip() or 0)
            except ValueError:
                v = 0
        else:
            v = 1          # 1行 = 1レッスン
        agg[key] = agg.get(key, 0) + v

    items = [{"name": k[0], "store": k[1], "value": int(v)} for k, v in agg.items()]
    items.sort(key=lambda x: -x["value"])
    return items[:TOP_N], f"※出典: {path.name}"


# ── 契約率 (集計表LTV) ─────────────────────────────────────
def load_contract_ranking(year: int, month: int) -> tuple:
    """契約率ランキング [{name, store, value, num, den}] と 注記 を返す"""
    summary = get_all_stores_summary(year, month)
    rows = []
    for sid, d in (summary or {}).items():
        for m in d.get("staff", []):
            den = m.get("newcomers", 0)
            num = m.get("contracts", 0)
            if den >= MIN_DEN:
                rows.append({"name": m["name"], "store": STORE_NAME.get(sid, sid),
                             "num": num, "den": den,
                             "value": round(num / den * 100) if den else 0})
    rows.sort(key=lambda x: (-x["value"], -x["den"]))
    note = f"※新規対応 {MIN_DEN}件以上のスタッフが対象"
    return rows[:TOP_N], note


# ── 配信済みマーカー ────────────────────────────────────────
def _load_sent() -> dict:
    try:
        if SENT_MARKER.exists():
            return json.loads(SENT_MARKER.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _mark_sent(key: str):
    try:
        d = _load_sent()
        d[key] = datetime.now(JST).isoformat(timespec="seconds")
        SENT_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SENT_MARKER.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  ⚠️ 配信マーカー保存失敗(無視): {e}")


def main():
    ap = argparse.ArgumentParser(description="月間ランキング配信")
    ap.add_argument("--year", type=int)
    ap.add_argument("--month", type=int)
    ap.add_argument("--lessons")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-slack", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--auto", action="store_true", help="1-5日のみ・未配信なら実行")
    args = ap.parse_args()

    now = datetime.now(JST)
    if args.year and args.month:
        year, month = args.year, args.month
    else:   # 既定は前月(確定値)
        year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    key = f"{year}-{month:02d}"

    if args.auto:
        if now.day > 5:
            print(f"⏭️ --auto: 本日{now.day}日は月初(1-5日)ではないためスキップ")
            return 0
        if key in _load_sent() and not args.force:
            print(f"⏭️ --auto: {key} は配信済み")
            return 0

    print(f"🏆 月間ランキング: {year}年{month}月")
    contract, c_note = load_contract_ranking(year, month)
    lesson, l_note = load_lesson_ranking(year, month, args.lessons)
    print(f"  レッスン数: {len(lesson)}件 / 契約率: {len(contract)}件")

    d = {
        "subtitle": f"月間ランキング　{year}年{month}月",
        "as_of": f"{month}月 確定",
        "lesson": lesson, "contract": contract,
        "lesson_note": l_note, "contract_note": c_note,
        "foot": f"集計期間 {year}/{month}/1〜月末　|　契約率 = 契約数 ÷ 新規対応数",
    }

    if args.dry:
        print("=" * 56)
        for t, items in (("レッスン数", lesson), ("契約率", contract)):
            print(f"[{t}]")
            for i, m in enumerate(items, 1):
                extra = f" ({m['num']}/{m['den']})" if "num" in m else "本"
                print(f"  {i}. {m['name']}({m['store']}) {m['value']}{extra}")
        print(f"注記: {l_note} / {c_note}")
        print("=" * 56)
        return 0

    out = PROJECT_ROOT / "output" / f"ranking_{key}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_ranking_to_png(d, out)

    if args.no_slack:
        print("📵 Slack送信スキップ(--no-slack)")
        return 0

    from alert_sender import _slack_upload_png, resolve_report_channel
    ch = resolve_report_channel()
    if not ch:
        print("❌ 実績進捗チャンネルID未解決")
        return 1
    head = (f":trophy: *La pilates 月間ランキング* :trophy:\n"
            f"{year}年{month}月の確定値です(レッスン数 / 契約率)")
    ok = _slack_upload_png(ch, [out], head)
    if ok:
        _mark_sent(key)
        print("✅ 配信完了")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
