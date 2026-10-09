"""contract_rate_alert.py — 契約率50%未満スタッフの研修アラート(ピラティス版)

harinature-jisseki/contract_rate_alert.py のピラティス版(2026-09-13 松崎指示)。
当月累計で「新規5件以上 かつ 契約率(=契約数/新規数)50%未満」のスタッフを抽出し、
Slack #koshikiピラティス幹部(C0BQ7SYU3M1・【KOSHIKI】社内WS)へ通知する。
該当者がいない日は投稿しない。

データ: 各店舗集計表の当月 R{令和}.{月}LTV シートのスタッフ別ブロック
       複数店舗で勤務している人は全店舗の合計で判定する(2026-09-28 松崎指示)
       (store_summary_reader と同じ読み方。LTV シートだけ読むので軽い)

使い方:
    python3 src/contract_rate_alert.py              # ドライラン(当月・送信なし)
    python3 src/contract_rate_alert.py 2026-09      # 月指定ドライラン
    python3 src/contract_rate_alert.py --post       # 実際に投稿
    python3 src/contract_rate_alert.py --auto       # スケジュール実行用(当日マーカーで1日1回)
"""
import re
import signal
import socket
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Google API は IPv6 経路だと応答が返らずハングすることがあるため IPv4 に固定する
# (2026-09-20 高崎の取得後に4時間45分ハングし、当日分が未配信になった)
_orig_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h, *a, **k: [r for r in _orig_gai(h, *a, **k) if r[0] == socket.AF_INET]
# タイムアウト未指定の通信が永久に待たないようにする
socket.setdefaulttimeout(60)

# 万一どこかで固まっても launchd の次回起動を塞がないよう、全体を15分で打ち切る
HARD_TIMEOUT_SEC = 900


class HardTimeout(BaseException):
    """全体タイムアウト。店舗ごとの except Exception に握りつぶされないよう BaseException 派生にする
    (2026-09-28 ピラティス版で TimeoutError が店舗単位の except に吸われて打ち切りが効かず、
     9時の実行が11時22分まで続いて11時の起動を塞いだ)"""


def _on_timeout(signum, frame):
    raise HardTimeout(f"全体タイムアウト({HARD_TIMEOUT_SEC}秒)。処理を打ち切りました")


import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import PROJECT_ROOT, get_gspread_client, slack_bot_token
from store_summary_reader import (STORE_SUMMARIES, find_sheet, ltv_sheet_name,
                                  safe_int, with_retry)

CHANNEL = "C0BQ7SYU3M1"          # #koshikiピラティス幹部(【KOSHIKI】社内WS)
CHANNEL_LABEL = "#koshikiピラティス幹部"
USERNAME = "契約率アラート"
ICON = ":rotating_light:"

THRESHOLD_PCT = 50  # 契約率50%未満が対象(2026-09-13 松崎指示で40%以下→50%未満。ハリナチュレは30%未満)
MIN_NEW = 5        # 当月新規5件以上

# 同じ名前の別人がいる場合はここに入れると店舗ごとに分けて集計する(今は該当なし)
SEPARATE_BY_STORE_NAMES: set = set()
# ヘルプ枠の「浦和店 RIONA」「浦和店RIONA」のような店舗名つき表記を本人名にそろえる
_STORE_PREFIX_RE = re.compile(r"^\S+?店\s*")

LOG_DIR = PROJECT_ROOT / "output" / "logs"
MARKER = "contract_alert_{d}.done"


def now_jst() -> datetime:
    """Mac(JST)でも GitHub(UTC)でも JST の現在時刻"""
    return datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)


def collect_staff(gc, year: int, month: int) -> dict:
    """全店舗の当月スタッフ別 新規数/契約数 を返す。{(店舗, スタッフ): {"new", "contract"}}
    "スタッフN" 等のプレースホルダ名は除外。
    """
    agg = {}
    for i, store in enumerate(STORE_SUMMARIES):
        if i > 0:
            time.sleep(2)   # 60 reads/分 のquota分散
        # find_sheet(シート一覧の読み込み)も429になるので店舗単位でリトライする
        # (2026-10-08 所沢が429で抜けたまま投稿された)
        rows, missing = None, False
        for attempt in range(3):
            try:
                sh = with_retry(gc.open_by_key, store["ssid"])
                ltv = find_sheet(sh, [ltv_sheet_name(year, month)])
                if not ltv:
                    missing = True
                    break
                rows = with_retry(ltv.get, "A2:CK4")
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    print(f"    🔄 {store['name']} 429 quota → 65秒待機してリトライ ({attempt+1}/3)")
                    time.sleep(65)
                    continue
                print(f"  ⚠️ {store['name']} 取得失敗: {str(e)[:100]}")
                break
        if missing:
            print(f"  · {store['name']}: {ltv_sheet_name(year, month)} なし → スキップ")
            continue
        if rows is None:
            continue
        r2 = rows[0] if len(rows) > 0 else []
        r3 = rows[1] if len(rows) > 1 else []
        r4 = rows[2] if len(rows) > 2 else []
        c = 9   # スタッフ別ブロックは J列(index9)以降 8列刻み
        while c < len(r3):
            name = r2[c].strip() if c < len(r2) else ""
            if name and not name.startswith("スタッフ"):
                hdr = [r3[c + k].strip() if c + k < len(r3) else "" for k in range(8)]
                val = [r4[c + k].strip() if c + k < len(r4) else "" for k in range(8)]
                nv = safe_int(val[hdr.index("新規数")]) if "新規数" in hdr else 0
                kv = safe_int(val[hdr.index("契約数")]) if "契約数" in hdr else 0
                if nv > 0:
                    e = agg.setdefault((store["name"], name), {"new": 0, "contract": 0})
                    e["new"] += nv
                    e["contract"] += kv
            c += 8
    return agg


def flagged_staff(agg: dict) -> list:
    # 同じ人の複数店舗ぶんを1人にまとめる(同名の別人は店舗ごとのまま)
    people = defaultdict(list)
    for (store, staff), v in agg.items():
        name = _STORE_PREFIX_RE.sub("", staff).strip() or staff
        key = (name, store) if name in SEPARATE_BY_STORE_NAMES else (name, None)
        people[key].append((store, v["new"], v["contract"]))

    flagged = []
    for (staff, _), parts in people.items():
        # ヘルプ枠表記と本人名が同じ店舗に並ぶこともあるので店舗単位でまとめ直す
        by_store = defaultdict(lambda: [0, 0])
        for store, nv, kv in parts:
            by_store[store][0] += nv
            by_store[store][1] += kv
        n = sum(x[0] for x in by_store.values())
        k = sum(x[1] for x in by_store.values())
        # 整数で判定: 5/10=50% のようなちょうど境界が浮動小数の誤差でぶれないように(50%ちょうどは対象外)
        if n >= MIN_NEW and k * 100 < THRESHOLD_PCT * n:
            # 見出しに使う店舗は新規数の一番多い店舗
            stores = sorted(by_store, key=lambda st: -by_store[st][0])
            flagged.append({"store": stores[0], "stores": stores, "staff": staff, "new": n,
                            "contract": k, "rate": k / n, "pct": k * 100 // n})
    return flagged


def stores_note(f: dict) -> str:
    """複数店舗の合算なら「※所沢＋浦和の合計」を返す(1店舗なら空)"""
    if len(f.get("stores", [])) < 2:
        return ""
    return "※" + "＋".join(f["stores"]) + "の合計"


def build_message(month: int, flagged: list) -> str:
    today = now_jst().strftime("%-m月%-d日")
    L = [f":rotating_light: *契約率{THRESHOLD_PCT}%未満アラート*（当月累計・新規{MIN_NEW}件以上）",
         f"{month}月度　{today}時点", "", f"該当 *{len(flagged)}名*", ""]
    # 店舗ごとにまとめる。店舗は最も低い契約率順、店舗内も契約率の低い順
    by_store = defaultdict(list)
    for f in flagged:
        by_store[f["store"]].append(f)
    store_order = sorted(by_store,
                         key=lambda s: (min(x["rate"] for x in by_store[s]),
                                        -max(x["new"] for x in by_store[s])))
    for idx, st in enumerate(store_order):
        if idx > 0:
            L.append("")
        L.append(f"*{st}*")
        # 切り捨て表示(整数計算): 49.5%が四捨五入で「50%」になり“50%未満”と矛盾するのを防ぐ
        for i in sorted(by_store[st], key=lambda x: (x["rate"], -x["new"])):
            L.append(f"・{i['staff']} *{i['pct']}%*（{i['contract']}/{i['new']}）{stores_note(i)}")
    L.append("")
    L.append(f"_※ 新規{MIN_NEW}件以上・契約率{THRESHOLD_PCT}%未満のスタッフを自動抽出（契約数/新規数）。研修フォローの目安です（複数店舗で勤務している人は全店舗の合計）_")
    L.append("")
    L.append("━━━━━━━━━━━━━━")
    L.append(":fire: *対応アクション*")
    L.append("・*即アプローチ必須*（該当スタッフへすぐ声かけ）")
    L.append("・新規対応を聴きに行ける場合は *店舗まで行って直接ヒアリング → フィードバック*")
    L.append("・*契約率が改善するまで* 継続フォロー")
    L.append("・*店長とも連携* して進める")
    L.append("")
    L.append("━━━━━━━━━━━━━━")
    L.append(":dart: *目標KPI*")
    L.append("・契約率：*60%以上*")
    L.append("・解約率：*3%未満*")   # ピラティスは3%未満(2026-09-13 松崎指示。ハリナチュレは10%未満)
    L.append("_この2つの達成が研修担当、プロデューサーの役割、仕事です_")
    return "\n".join(L)


_BOLD_RE = re.compile(r"\*([^*\n]+)\*")


def fix_bold(text: str) -> str:
    """Slackの *太字* は前後が半角スペース/行頭行末でないと効かないため自動で補う
    (harinature-jisseki/contract_rate_alert.py と同じ処理)"""
    out = []
    for line in text.split("\n"):
        res, idx = [], 0
        for m in _BOLD_RE.finditer(line):
            res.append(line[idx:m.start()])
            b = line[m.start() - 1] if m.start() > 0 else ""
            a = line[m.end()] if m.end() < len(line) else ""
            res.append(("" if b in ("", " ") else " ") + m.group(0) + ("" if a in ("", " ") else " "))
            idx = m.end()
        res.append(line[idx:])
        out.append("".join(res))
    return "\n".join(out)


def post(message: str, do_post: bool) -> bool:
    message = fix_bold(message)
    if not do_post:
        print(f"----- [DRYRUN] {CHANNEL_LABEL} -----")
        print(message)
        print("----- (--post で実際に投稿) -----")
        return True
    try:
        r = requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {slack_bot_token()}",
                                   "Content-Type": "application/json; charset=utf-8"},
                          json={"channel": CHANNEL, "text": message, "link_names": True,
                                "unfurl_links": False, "unfurl_media": False,
                                "username": USERNAME, "icon_emoji": ICON},
                          timeout=30).json()
    except Exception as e:
        print(f"  ⚠️ {CHANNEL_LABEL} 投稿例外: {str(e)[:90]}")
        return False
    if r.get("ok"):
        print(f"  ✅ {CHANNEL_LABEL} へ投稿完了")
        return True
    print(f"  ⚠️ {CHANNEL_LABEL} 投稿失敗: {r.get('error')}")
    return False


def main() -> int:
    args = sys.argv[1:]
    auto = "--auto" in args
    do_post = auto or "--post" in args
    now = now_jst()
    ym = next((a for a in args if re.match(r"^\d{4}-\d{2}$", a)), now.strftime("%Y-%m"))
    year, month = int(ym[:4]), int(ym[5:7])

    marker = LOG_DIR / MARKER.format(d=now.strftime("%Y-%m-%d"))
    if auto and marker.exists():
        print("✓ 本日は投稿済み → スキップ")
        return 0

    agg = collect_staff(get_gspread_client(), year, month)
    flagged = flagged_staff(agg)
    print(f"▶️ {ym} 契約率{THRESHOLD_PCT}%未満(新規{MIN_NEW}+): {len(flagged)}名 "
          f"／ 集計スタッフ {len(agg)}名")
    if not flagged:
        print("  該当者なし → 投稿スキップ")   # マーカーは立てない(その日はまだ投稿されうる)
        return 0

    ok = post(build_message(month, flagged), do_post)
    if auto and ok:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(now.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _on_timeout)
    signal.alarm(HARD_TIMEOUT_SEC)
    try:
        rc = main()
    except HardTimeout as e:
        print(f"⏱️ {e}")
        rc = 1
    finally:
        signal.alarm(0)
    sys.exit(rc)
