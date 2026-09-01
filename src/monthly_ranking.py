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
import time
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
# 担当者の所属店舗を手動で上書きする設定 {"スタッフ名": "店舗名"}
# hacomono の担当者名に店舗が付いていない人だけに適用する。
# (hacomono 側で「所沢 MIYUU」のように店舗を付ければこの設定は不要)
STORE_OVERRIDE = PROJECT_ROOT / "data" / "staff_store_override.json"

# CSVのヘッダ判定に使うキーワード
NAME_KEYS = ("担当者", "インストラクター", "担当", "スタッフ", "講師", "staff", "instructor")
COUNT_KEYS = ("消化客数", "レッスン数", "本数", "回数", "コマ数", "実施数")
STORE_KEYS = ("店舗", "店名", "施設", "スタジオ", "shop", "store")


# ── レッスン数 (CSV) ────────────────────────────────────────
def _find_lesson_csv(year: int, month: int, explicit: str = None) -> Path:
    """レッスンCSVを探す (明示指定 → data/lessons/YYYY-MM.csv → Downloads)"""
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
    fixed = LESSON_DIR / f"{year}-{month:02d}.csv"
    if fixed.exists():
        return fixed
    dl = Path.home() / "Downloads"
    if dl.exists():
        cands = list(dl.glob("ss-*.csv")) + [
            p for p in dl.glob("*.csv")
            if any(k in p.name for k in ("lesson", "レッスン", "予約", "reserv"))]
        if cands:
            return max(cands, key=lambda p: p.stat().st_mtime)
    return None


def _read_rows(path: Path) -> list:
    """文字コードを判定して CSV を list[list] で返す"""
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, encoding=enc) as fh:
                return list(csv.reader(fh))
        except UnicodeDecodeError:
            continue
    return []


def _pick_idx(header: list, keys: tuple):
    """ヘッダから該当列のindexを返す(先に書いたキーワードほど優先)"""
    for k in keys:
        for i, h in enumerate(header):
            if h and k.lower() in str(h).lower():
                return i
    return None


def _take_with_ties(items: list, n: int) -> list:
    """上位n件を返す。n位と同値の人が続く場合はその全員を含める"""
    if len(items) <= n:
        return items
    edge = items[n - 1]["value"]
    return [x for x in items if x["value"] >= edge]


def _load_override() -> dict:
    try:
        if STORE_OVERRIDE.exists():
            d = json.loads(STORE_OVERRIDE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {str(k).strip(): str(v).strip() for k, v in d.items()}
    except Exception as e:
        print(f"  ⚠️ 店舗オーバーライド読込失敗(無視): {e}")
    return {}


def _split_store(label: str) -> tuple:
    """'神戸元町 SAYAKA' → ('神戸元町','SAYAKA') / 'MANAKA' → ('','MANAKA')"""
    lab = re.sub(r"^La pilates\s*", "", str(label)).strip()
    if " " in lab or "　" in lab:
        head, _, tail = lab.replace("　", " ").partition(" ")
        return head.replace("店", "").strip(), tail.strip()
    return "", lab


def load_staff_roster(year: int, month: int) -> dict:
    """各店舗のLTVシート見出しから {スタッフ名: [店舗名,...]} を作る"""
    from common import get_gspread_client
    from store_summary_reader import STORE_SUMMARIES, ltv_sheet_name, find_sheet, with_retry
    gc = get_gspread_client()
    roster = {}
    for i, st in enumerate(STORE_SUMMARIES):
        if i > 0:
            time.sleep(5)          # read クォータ(429)分散
        try:
            sh = with_retry(gc.open_by_key, st["ssid"])
            ws = find_sheet(sh, [ltv_sheet_name(year, month),
                                 f"R{ltv_sheet_name(year, month)[1:]} "])
            if ws is None:
                continue
            for i, v in enumerate(with_retry(ws.row_values, 2)):
                nm = str(v).strip()
                if i >= 9 and nm and not nm.startswith("スタッフ"):
                    _, nm = _split_store(nm)
                    roster.setdefault(nm, []).append(st["name"])
        except Exception as e:
            print(f"  ⚠️ 名簿取得失敗({st['name']}・無視): {e}")
    return roster


def load_lesson_ranking(year: int, month: int, explicit: str = None,
                        roster: dict = None) -> tuple:
    """レッスン数(消化客数)ランキング [{name, store, value}] と 注記 を返す

    hacomono の「担当者別 売上・客数」CSV(複数セクション)に対応。
    担当者名の店舗プレフィックスを使い、無い場合は集計表の名簿から補完する。
    """
    path = _find_lesson_csv(year, month, explicit)
    if not path:
        return [], f"※レッスン数CSV未連携(data/lessons/{year}-{month:02d}.csv を置くと集計されます)"
    rows = _read_rows(path)
    if not rows:
        return [], f"※CSVを読めませんでした({path.name})"

    # 「消化客数(レッスン数)」列を持つセクションのヘッダ行を探す
    h_idx = None
    for i, r in enumerate(rows):
        if r and _pick_idx(r, NAME_KEYS) is not None and _pick_idx(r, COUNT_KEYS) is not None:
            h_idx = i
            break
    if h_idx is None:
        return [], f"※CSVにレッスン数(消化客数)の列が見つかりません({path.name})"
    header = rows[h_idx]
    i_name = _pick_idx(header, NAME_KEYS)
    i_cnt = _pick_idx(header, COUNT_KEYS)
    i_store = _pick_idx(header, STORE_KEYS)

    raw = []
    for r in rows[h_idx + 1:]:
        if not r or not str(r[i_name]).strip():
            break                                   # 空行 = セクション終わり
        label = str(r[i_name]).strip()
        try:
            v = int(float(str(r[i_cnt]).replace(",", "").strip() or 0))
        except (ValueError, IndexError):
            v = 0
        store, name = _split_store(label)
        if not store and i_store is not None and i_store < len(r):
            store, _ = _split_store(str(r[i_store]))
        raw.append({"name": name, "store": store, "value": v})

    # 店舗名が無い人にだけ、手動オーバーライド設定を適用する
    override = _load_override()
    if override:
        for x in raw:
            if not x["store"] and x["name"] in override:
                x["store"] = override[x["name"]]

    # 店舗名が無い人を名簿から補完する。
    # hacomono の担当者名は「他店舗のスタッフにだけ店舗名が付く」運用のため、
    #   ① 同名が別店舗として明示済みなら、その店舗を候補から外す
    #   ② それでも決まらなければ「CSVに一度も出てこない店舗」に絞る
    # の2段階で一意化する。決まらない場合は店舗名なしで表示する。
    if roster:
        explicit_pairs = {(x["name"], x["store"]) for x in raw if x["store"]}
        explicit_stores = {x["store"] for x in raw if x["store"]}
        for x in raw:
            if x["store"]:
                continue
            cands = [s for s in roster.get(x["name"], [])
                     if (x["name"], s) not in explicit_pairs]
            if len(cands) > 1:
                narrowed = [s for s in cands if s not in explicit_stores]
                if narrowed:
                    cands = narrowed
            if len(cands) == 1:
                x["store"] = cands[0]

    items = [x for x in raw if x["value"] > 0]
    items.sort(key=lambda x: (-x["value"], x["name"]))
    return _take_with_ties(items, TOP_N), "※レッスン数 = 消化客数（hacomono）"


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
    return _take_with_ties(rows, TOP_N), note


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
    # 店舗名なしスタッフの補完用。CSVが無い月は余計なAPIを叩かない
    roster = load_staff_roster(year, month) if _find_lesson_csv(year, month, args.lessons) else {}
    lesson, l_note = load_lesson_ranking(year, month, args.lessons, roster)
    print(f"  レッスン数: {len(lesson)}件 / 契約率: {len(contract)}件")

    d = {
        "subtitle": f"月間ランキング　{year}年{month}月",
        "as_of": f"{month}月 確定",
        "lesson": lesson, "contract": contract, "top_n": TOP_N,
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
    # alert_sender(daily) と同じ流儀: --silent で @channel を抑制できる
    mention = "" if "--silent" in sys.argv else "<!channel>\n"
    head = (f"{mention}:trophy: *La pilates 月間ランキング* :trophy:\n"
            f"{year}年{month}月の確定値です(レッスン数 / 契約率)")
    ok = _slack_upload_png(ch, [out], head)
    if ok:
        _mark_sent(key)
        print("✅ 配信完了")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
