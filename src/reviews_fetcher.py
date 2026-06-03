"""reviews_fetcher.py

Google Places API + HotPepper Beauty スクレイプで全店の口コミ件数を取得 →
⑦月次店舗実績の最新月行(月末優先・なければ月中)に反映する。

毎日10:00のcronから実行される(run_feedback_sync.shに追加)。
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import PROJECT_ROOT, get_gspread_client, SPREADSHEET_ID

# alert_sender が読む「口コミ」シートのスプシ(⑦月次店舗実績とは別物)
DASHBOARD_SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# HotPepper URL は将来store毎に変動する可能性あるので config に外出し
HPB_URLS = {
    "S001": "https://beauty.hotpepper.jp/kr/slnH000743149/",
    "S002": "https://beauty.hotpepper.jp/kr/slnH000745957/",
    "S003": "https://beauty.hotpepper.jp/kr/slnH000774690/",
    "S004": "https://beauty.hotpepper.jp/kr/slnH000740308/",
    "S005": "https://beauty.hotpepper.jp/kr/slnH000777989/",
}


def fetch_google(place_id: str) -> int:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "language": "ja",
                    "fields": "user_ratings_total", "key": api_key},
            timeout=20,
        )
        res = r.json()
        if res.get("status") == "OK":
            return res["result"].get("user_ratings_total", 0)
    except Exception as e:
        print(f"  ⚠️ Google取得失敗 ({place_id}): {e}")
    return None


def fetch_hpb(url: str) -> int:
    if not url: return None
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP"},
                         timeout=15, allow_redirects=True)
        m = re.search(r'slnHeaderKuchikomiCount[^>]*>[^（(]*[（(]\s*(\d[\d,]*)\s*件', r.text)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception as e:
        print(f"  ⚠️ HPB取得失敗 ({url}): {e}")
    return None


def main():
    # place_ids ロード
    place_path = PROJECT_ROOT / "config" / "place_ids.json"
    if not place_path.exists():
        print(f"❌ {place_path} がありません(初回実行: python3 src/setup_place_ids.py)")
        return 1
    place_ids = json.loads(place_path.read_text(encoding="utf-8"))

    print(f"⭐ 口コミ取得開始: {datetime.now()}")
    counts = {}
    for sid, info in place_ids.items():
        g = fetch_google(info["place_id"])
        h = fetch_hpb(HPB_URLS.get(sid))
        counts[sid] = {"google": g, "hpb": h, "name": info["name"]}
        print(f"  {info['name']:10s}: Google={g} HPB={h}")

    # スプシの最新月行を更新(月末優先・無ければ月中)
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("⑦月次店舗実績")
    all_v = ws.get_all_values()
    header = all_v[0]
    COL = {h: i for i, h in enumerate(header)}

    # 各店舗の最新の有効行を見つけて更新
    print("\n📊 スプシ更新")
    for sid, c in counts.items():
        g, h = c["google"], c["hpb"]
        if g is None and h is None: continue

        # 最新の月末行 → 月中行 の順で対象行を探す
        store_rows = [(i, r) for i, r in enumerate(all_v[1:], start=2)
                      if len(r) > COL['店舗ID'] and r[COL['店舗ID']] == sid]
        store_rows.sort(key=lambda x: x[1][COL['年月']], reverse=True)

        target_idx = None
        for i, r in store_rows:
            if r[COL['期間']] == '月末(1-月末)' and r[COL['売上(税抜)']]:
                target_idx = i; break
        if target_idx is None:
            for i, r in store_rows:
                if r[COL['期間']] == '月中(1-15日)' and r[COL['売上(税抜)']]:
                    target_idx = i; break

        if target_idx is None:
            print(f"  ⚠️ {c['name']}: 対象行なし"); continue

        if g is not None:
            ws.update_cell(target_idx, COL['Google口コミ']+1, g)
        if h is not None:
            ws.update_cell(target_idx, COL['HPB口コミ']+1, h)
        if g is not None and h is not None:
            ws.update_cell(target_idx, COL['口コミ合計']+1, g+h)
        print(f"  ✅ {c['name']} 行{target_idx}: G={g} H={h}")

    # ── 口コミダッシュボードシート(DASHBOARD_SSID/「口コミ」)の当月列も更新 ──
    # alert_sender.get_reviews_from_kuchikomi が読むシート。
    # 当月列 = 「前月比」の左。Google行=2-6 / HPB行=7-11(1-indexed)。
    # Google+HPB 合計行(12-16)・前月比列は数式想定のため書き込まない。
    try:
        dsh = gc.open_by_key(DASHBOARD_SSID)
        kws = dsh.worksheet("口コミ")
        khdr = kws.row_values(1)
        try:
            latest_col = khdr.index("前月比")  # 0-indexed → 当月列は -1 だが update は1-indexed
        except ValueError:
            latest_col = len(khdr)
        col_1idx = latest_col  # 「前月比」の左の列(1-indexed) = latest_col(0-indexed の index)
        google_rows = {"S001": 2, "S002": 3, "S003": 4, "S004": 5, "S005": 6}  # 1-indexed
        hpb_rows    = {"S001": 7, "S002": 8, "S003": 9, "S004": 10, "S005": 11}
        n = 0
        for sid, c in counts.items():
            g, h = c["google"], c["hpb"]
            if g is not None and sid in google_rows:
                kws.update_cell(google_rows[sid], col_1idx, g); n += 1
            if h is not None and sid in hpb_rows:
                kws.update_cell(hpb_rows[sid], col_1idx, h); n += 1
        print(f"  ✅ 口コミシート 当月列(col{col_1idx}) 更新: {n}セル")
    except Exception as e:
        print(f"  ⚠️ 口コミシート更新失敗(無視): {e}")

    print("\n🎉 完了!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
