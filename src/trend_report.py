"""trend_report.py — 年間の契約率推移レポート(画像)を生成し Slack に配信

毎月月初(1日)に、その年の「1月〜直近確定月」の契約率推移を画像化して
#ピラティス_実績進捗 に投稿する(確定版)。

構成:
  ① 店舗別 契約率の推移(折れ線・全店平均ライン付き)
  ② 店舗ごとのスタッフ別 契約率(月次ヒートマップ表・平均列付き)

データ: 各店舗集計表の R{令和}.{月}LTV シート(店舗合計 D4/G4/H4 + スタッフ別ブロック)。
「直近確定月」= データが存在する最新の月(=月初なら前月まで、翌年1月なら前年12月まで)。

使い方:
    python3 src/trend_report.py              # 自動(当年・直近確定月まで)配信
    python3 src/trend_report.py --dry        # 生成内容を表示(送信なし)
    python3 src/trend_report.py --no-slack   # 画像だけ生成(/tmp)・送信なし
    python3 src/trend_report.py --through 8   # 8月までに固定(テスト用)
    python3 src/trend_report.py --force       # 冪等性チェックを無視して再送
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from common import get_gspread_client, slack_bot_token
from store_summary_reader import STORE_SUMMARIES, safe_int
from alert_sender import resolve_report_channel, _now_jst

NAME6 = {"S001": "川越", "S002": "大宮", "S003": "高崎",
         "S004": "神戸元町", "S005": "西宮北口", "S006": "所沢",
         "S007": "浦和"}
ORDER = ["S001", "S002", "S003", "S004", "S005", "S006", "S007"]
LINE_COLORS = {"S001": "#C9962F", "S002": "#3C6B4A", "S003": "#C25B4A",
               "S004": "#4A6FA5", "S005": "#9C6BA0", "S006": "#B0742F",
               "S007": "#2F8F8F"}


# ━━━━━━━━━━━━━━━━━ データ取得 ━━━━━━━━━━━━━━━━━
def gather(gc, year: int) -> dict:
    """指定年の全店 店舗合計+スタッフ別 契約率(月次)を取得。
    返り値: {sid: {"name", "total": {m: {num,den}}, "staff": {name: {m: {num,den}}}}}
    """
    import time
    reiwa = year - 2018
    out = {}
    for si, store in enumerate(STORE_SUMMARIES):
        if si > 0:
            time.sleep(2)
        sh = gc.open_by_key(store["ssid"])
        titles = [w.title for w in sh.worksheets()]
        msheet = {}
        for m in range(1, 13):
            for t in titles:
                if t.strip() == f"R{reiwa}.{m}月LTV":
                    msheet[m] = t
                    break
        rec = {"name": NAME6.get(store["id"], store["name"]), "total": {}, "staff": {}}
        if msheet:
            ranges = [f"'{msheet[m]}'!A2:CK4" for m in sorted(msheet)]
            try:
                vr = sh.values_batch_get(ranges)["valueRanges"]
            except Exception as e:
                print(f"  ⚠️ {rec['name']} 取得失敗: {e}")
                out[store["id"]] = rec
                continue
            for idx, m in enumerate(sorted(msheet)):
                vals = vr[idx].get("values", [])
                r2 = vals[0] if len(vals) > 0 else []
                r3 = vals[1] if len(vals) > 1 else []
                r4 = vals[2] if len(vals) > 2 else []
                tn = safe_int(r4[3]) if len(r4) > 3 else 0
                tc = safe_int(r4[6]) if len(r4) > 6 else 0
                if tn > 0:
                    rec["total"][m] = {"num": tc, "den": tn}
                c = 9
                while c < len(r3):
                    name = r2[c].strip() if c < len(r2) else ""
                    if name and not name.startswith("スタッフ"):
                        hdr = [r3[c + k].strip() if c + k < len(r3) else "" for k in range(8)]
                        val = [r4[c + k].strip() if c + k < len(r4) else "" for k in range(8)]
                        nv = safe_int(val[hdr.index("新規数")]) if "新規数" in hdr else 0
                        kv = safe_int(val[hdr.index("契約数")]) if "契約数" in hdr else 0
                        if nv > 0:
                            rec["staff"].setdefault(name, {})[m] = {"num": kv, "den": nv}
                    c += 8
        out[store["id"]] = rec
    return out


def last_month_with_data(data: dict) -> int:
    last = 0
    for sid in ORDER:
        for m in data.get(sid, {}).get("total", {}):
            last = max(last, int(m))
    return last


# ━━━━━━━━━━━━━━━━━ 描画ヘルパ ━━━━━━━━━━━━━━━━━
def rate_class(num, den):
    if den == 0:
        return "none"
    r = num / den
    return "zero" if r == 0 else ("mid" if r < 0.5 else "good")


def pct(num, den):
    return "—" if den == 0 else f"{round(num/den*100)}%"


def _get(md_dict, m):
    return md_dict.get(m) or md_dict.get(str(m))


def cell(md):
    if not md or md.get("den", 0) == 0:
        return '<td class="c c-none">—</td>'
    cls = rate_class(md["num"], md["den"])
    return f'<td class="c c-{cls}">{pct(md["num"], md["den"])}<span class="f">{md["num"]}/{md["den"]}</span></td>'


def avg_md(md_dict, months):
    tn = sum((_get(md_dict, m) or {}).get("den", 0) for m in months)
    tc = sum((_get(md_dict, m) or {}).get("num", 0) for m in months)
    return {"num": tc, "den": tn}


def avg_cell(md_dict, months):
    a = avg_md(md_dict, months)
    if a["den"] == 0:
        return '<td class="c c-none avgcol">—</td>'
    cls = rate_class(a["num"], a["den"])
    return f'<td class="c c-{cls} avgcol">{pct(a["num"], a["den"])}<span class="f">{a["num"]}/{a["den"]}</span></td>'


def all_store_month(data, m):
    tc = tn = 0
    for sid in ORDER:
        md = _get(data.get(sid, {}).get("total", {}), m)
        if md:
            tc += md["num"]; tn += md["den"]
    return (tc / tn * 100) if tn else None


def line_chart(data, sid, months, content_w):
    """1店舗分の折れ線: その店の月次契約率(太線・値ラベル付き) + 全店平均(参考・細い点線)"""
    W, H = content_w, 420
    # PADR は凡例＋余白。最終月の値ラベル(%)が凡例に重ならないよう十分に取る
    PADL, PADR, PADT, PADB = 70, 230, 30, 50
    plotW, plotH = W - PADL - PADR, H - PADT - PADB
    n = len(months)
    col = LINE_COLORS[sid]
    st = data.get(sid, {})

    def x(m):
        i = months.index(m)
        return PADL + (i / (n - 1) * plotW if n > 1 else plotW / 2)

    def y(v):
        return PADT + (1 - v / 100) * plotH

    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="chart">']
    for gv in (0, 25, 50, 75, 100):
        yy = y(gv)
        p.append(f'<line x1="{PADL}" y1="{yy:.0f}" x2="{PADL+plotW}" y2="{yy:.0f}" stroke="#E7DECF" stroke-width="1"/>')
        p.append(f'<text x="{PADL-12}" y="{yy+6:.0f}" class="ax" text-anchor="end">{gv}%</text>')
    for m in months:
        p.append(f'<text x="{x(m):.0f}" y="{PADT+plotH+30:.0f}" class="ax" text-anchor="middle">{m}月</text>')
    p.append(f'<line x1="{PADL}" y1="{y(50):.0f}" x2="{PADL+plotW}" y2="{y(50):.0f}" stroke="#C9AE7A" stroke-width="1.5" stroke-dasharray="5 4"/>')

    # 全店平均(参考・薄い点線)
    apts = [(m, all_store_month(data, m)) for m in months]
    apts = [(m, v) for m, v in apts if v is not None]
    if len(apts) >= 2:
        d = " ".join(f"{x(m):.1f},{y(v):.1f}" for m, v in apts)
        p.append(f'<polyline points="{d}" fill="none" stroke="#B7AC9C" stroke-width="2.5" stroke-dasharray="7 5" stroke-linejoin="round"/>')
    for m, v in apts:
        p.append(f'<circle cx="{x(m):.1f}" cy="{y(v):.1f}" r="3.5" fill="#B7AC9C"/>')

    # 当店ライン(主役・太線 + 値ラベル)
    pts = [(m, _get(st.get("total", {}), m)["num"] / _get(st.get("total", {}), m)["den"] * 100)
           for m in months if _get(st.get("total", {}), m) and _get(st.get("total", {}), m)["den"] > 0]
    if len(pts) >= 2:
        d = " ".join(f"{x(m):.1f},{y(v):.1f}" for m, v in pts)
        p.append(f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>')
    for m, v in pts:
        p.append(f'<circle cx="{x(m):.1f}" cy="{y(v):.1f}" r="7" fill="#fff" stroke="{col}" stroke-width="3.5"/>')
        p.append(f'<text x="{x(m):.1f}" y="{y(v)-17:.1f}" class="ptval" fill="{col}" text-anchor="middle">{round(v)}%</text>')

    # 凡例 (プロット右端から 66px 離して値ラベルとの重なりを回避)
    lx = PADL + plotW + 66
    ly = PADT + 14
    p.append(f'<rect x="{lx}" y="{ly-13}" width="20" height="6" rx="3" fill="{col}"/>')
    p.append(f'<text x="{lx+28}" y="{ly-4}" class="lg" font-weight="900">{st.get("name","")}</text>')
    ly += 32
    p.append(f'<line x1="{lx}" y1="{ly-10}" x2="{lx+20}" y2="{ly-10}" stroke="#B7AC9C" stroke-width="3" stroke-dasharray="6 4"/>')
    p.append(f'<text x="{lx+28}" y="{ly-4}" class="lg">全店平均</text>')
    p.append('</svg>')
    return "".join(p)


def store_table(data, sid, months):
    st = data.get(sid, {})
    tot, staff = st.get("total", {}), st.get("staff", {})
    if not tot and not staff:
        return ""
    head = "".join(f"<th>{m}月</th>" for m in months) + '<th class="avgcol-h">平均</th>'
    total_cells = "".join(cell(_get(tot, m)) for m in months)
    rows = [f'<tr class="total-row"><td class="nm">店舗全体</td>{total_cells}{avg_cell(tot, months)}</tr>']

    def load(nm):
        return sum((_get(staff[nm], m) or {}).get("den", 0) for m in months)
    for nm in sorted(staff, key=lambda n: -load(n)):
        d = staff[nm]
        cells = "".join(cell(_get(d, m)) for m in months)
        rows.append(f'<tr><td class="nm">{nm}</td>{cells}{avg_cell(d, months)}</tr>')
    return (f'<table><thead><tr><th class="nm-h">スタッフ</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_html(data, sid, year, months):
    """1店舗ぶんのHTML(折れ線 + その店のスタッフ表)"""
    n = len(months)
    content_w = max(1100, 150 + n * 118 + 190)
    body_w = content_w + 80
    st = data.get(sid, {})
    sname = st.get("name", "")
    tot = st.get("total", {})
    a = avg_md(tot, months)
    avg_txt = pct(a["num"], a["den"])
    last = months[-1] if months else 0
    table = store_table(data, sid, months)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  :root {{ --bg:#FDFBF7; --ink:#4A3F35; --sub:#9A8B79; --bronze:#9C7A5B; --gold:#C9962F;
    --gold-d:#A87B45; --line:#ECE3D5; --good:#3C6B4A; --mid:#C9962F; --zero:#C25B4A; --none:#B7AC9C; }}
  body {{ width:{body_w}px; background:var(--bg); color:var(--ink); font-family:"Noto Sans CJK JP",sans-serif;
    padding:44px 40px 40px; -webkit-font-smoothing:antialiased; }}
  .header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px;
    border-bottom:2.5px solid var(--gold-d); padding-bottom:16px; margin-bottom:22px; }}
  .h-left {{ display:flex; align-items:baseline; gap:14px; }}
  .spark {{ font-size:28px; background:linear-gradient(135deg,var(--bronze),var(--gold));
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
  .brand {{ font-family:"Noto Serif CJK JP","Georgia",serif; font-weight:700; font-size:36px;
    background:linear-gradient(100deg,var(--bronze) 5%,var(--gold) 95%);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
  .storename {{ font-family:"Noto Serif CJK JP",serif; font-size:34px; font-weight:900; color:var(--ink);
    display:flex; align-items:center; gap:10px; }}
  .sub {{ font-size:21px; font-weight:700; color:var(--sub); }}
  .avgbadge {{ font-size:22px; font-weight:900; color:#fff; padding:10px 20px; border-radius:999px;
    background:linear-gradient(135deg,var(--bronze),var(--gold)); white-space:nowrap;
    font-family:"Noto Serif CJK JP",serif; }}
  .ab-f {{ display:block; font-size:12px; font-weight:600; opacity:.9; text-align:center;
    font-family:"Noto Sans CJK JP",sans-serif; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:20px 24px;
    box-shadow:0 3px 10px rgba(60,55,40,.05); margin-bottom:22px; }}
  .card-t {{ font-family:"Noto Serif CJK JP",serif; font-size:20px; font-weight:900; color:var(--gold-d); margin-bottom:8px; }}
  .chart {{ width:100%; height:auto; }}
  .ax {{ font-size:18px; fill:var(--sub); }}
  .lg {{ font-size:18px; fill:var(--ink); font-weight:700; }}
  .ptval {{ font-size:19px; font-weight:900; font-family:"Noto Serif CJK JP",serif; }}
  .dot {{ width:16px; height:16px; border-radius:50%; display:inline-block; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ text-align:center; padding:12px 4px; border-bottom:1px solid #F1EADC; }}
  thead th {{ font-size:18px; font-weight:700; color:var(--sub); border-bottom:1.5px solid var(--line); }}
  .nm-h {{ text-align:left; padding-left:10px; }}
  .nm {{ text-align:left; padding-left:10px; font-size:20px; font-weight:700; color:#3a352a; white-space:nowrap; }}
  .total-row td {{ background:#FBF5E9; }}
  .total-row .nm {{ color:var(--gold-d); font-weight:900; }}
  .c {{ font-size:22px; font-weight:800; font-family:"Noto Serif CJK JP",serif; line-height:1.15; }}
  .c .f {{ display:block; font-size:13px; font-weight:600; color:var(--sub); font-family:"Noto Sans CJK JP",sans-serif; }}
  .c-good {{ color:var(--good); }} .c-mid {{ color:var(--mid); }} .c-zero {{ color:var(--zero); }}
  .c-none {{ color:var(--none); font-weight:600; }}
  .avgcol {{ background:#FBF5E9; border-left:2px solid var(--line); }}
  .avgcol-h {{ background:#FBF5E9; border-left:2px solid var(--line); color:var(--gold-d); font-weight:900; }}
  .total-row .avgcol {{ background:#F4E8CF; }}
  .footer {{ margin-top:16px; text-align:right; font-size:13px; color:var(--none); }}
</style></head><body>
  <div class="header">
    <div class="h-left">
      <span class="spark">✳</span><span class="brand">La pilates</span>
      <span class="storename"><span class="dot" style="background:{LINE_COLORS[sid]}"></span>{sname}</span>
      <span class="sub">{year}年 契約率推移（1〜{last}月）</span>
    </div>
    <span class="avgbadge">通期平均 {avg_txt}<span class="ab-f">{a['num']}/{a['den']}</span></span>
  </div>
  <div class="card"><div class="card-t">契約率の推移（月次）</div>{line_chart(data, sid, months, content_w)}</div>
  <div class="card"><div class="card-t">スタッフ別 契約率（月次）</div>{table}</div>
  <div class="footer">色分け　緑=50%以上 / 橙=1〜49% / 赤=0% / 灰=対応なし　｜　各セル下段=契約数/新規数　｜　平均=通期(1〜{last}月)の合計契約÷合計新規</div>
</body></html>"""


def render_store_pngs(data, year, months, stamp: str):
    """店舗ごとに1枚ずつPNGを生成し、[(sid, Path)] を返す(実績のある店のみ)"""
    n = len(months)
    body_w = max(1100, 150 + n * 118 + 190) + 80
    outs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": body_w, "height": 1000}, device_scale_factor=2)
        for sid in ORDER:
            st = data.get(sid, {})
            # 対象期間(months)内に実績がある店のみ生成。
            # 期間外にしかデータが無い店(例: 8月開店の所沢を1〜7月レポートで扱う場合)は
            # 全セル「—」の空レポートになるためスキップする。
            if avg_md(st.get("total", {}), months)["den"] == 0:
                print(f"  · {NAME6.get(sid)}: 対象期間に実績なし → スキップ")
                continue
            out = Path(f"/tmp/pilates_trend_{year}_{sid}_{stamp}.png")
            pg.set_content(build_html(data, sid, year, months), wait_until="networkidle")
            pg.locator("body").screenshot(path=str(out))
            outs.append((sid, out))
            print(f"  ✅ {st.get('name')} → {out.name}")
        b.close()
    return outs


def upload_pngs(channel_id: str, items, comment: str) -> bool:
    """[(sid, Path)] を 1投稿に複数添付(各ファイルのタイトル=店舗名)で送信"""
    import requests
    try:
        files_meta = []
        for sid, pp in items:
            size = pp.stat().st_size
            r = requests.post("https://slack.com/api/files.getUploadURLExternal",
                              headers={"Authorization": f"Bearer {slack_bot_token()}"},
                              data={"filename": pp.name, "length": size}, timeout=30)
            j = r.json()
            if not j.get("ok"):
                print(f"  ⚠️ getUploadURL失敗: {j.get('error')}")
                return False
            with open(pp, "rb") as f:
                r2 = requests.post(j["upload_url"], data=f.read(), timeout=60)
            if r2.status_code != 200:
                print(f"  ⚠️ アップロード失敗: HTTP {r2.status_code}")
                return False
            files_meta.append({"id": j["file_id"], "title": f"{NAME6.get(sid, sid)} 契約率推移"})
        body = {"files": files_meta, "channel_id": channel_id, "initial_comment": comment}
        r3 = requests.post("https://slack.com/api/files.completeUploadExternal",
                           headers={"Authorization": f"Bearer {slack_bot_token()}",
                                    "Content-Type": "application/json; charset=utf-8"},
                           json=body, timeout=30)
        if r3.json().get("ok"):
            return True
        print(f"  ⚠️ complete失敗: {r3.json().get('error')}")
        return False
    except Exception as e:
        print(f"  ⚠️ 送信例外: {e}")
        return False


def already_sent(channel_id, year, last) -> bool:
    """当月の推移レポートが既に投稿済みか(冪等性)。--force で無視。"""
    if "--force" in sys.argv or not channel_id:
        return False
    try:
        import requests
        from datetime import timedelta
        now = _now_jst()
        oldest = (now - timedelta(days=6)).timestamp()
        r = requests.get("https://slack.com/api/conversations.history",
                         headers={"Authorization": f"Bearer {slack_bot_token()}"},
                         params={"channel": channel_id, "limit": 40, "oldest": oldest}, timeout=15)
        marker = f"{year}年 契約率推移"
        submark = f"1〜{last}月"
        for m in r.json().get("messages", []):
            t = m.get("text", "")
            if marker in t and submark in t:
                return True
    except Exception as e:
        print(f"  ⚠️ 冪等性チェック失敗(続行): {e}")
    return False


def main():
    through = None
    if "--through" in sys.argv:
        i = sys.argv.index("--through")
        if i + 1 < len(sys.argv):
            through = int(sys.argv[i + 1])

    gc = get_gspread_client()
    now = _now_jst()
    # ── 対象年と「確定月」の決定 ────────────────────────────
    # 確定版レポートなので当月(進行中)は含めない = 前月までが上限。
    # 1月に実行した場合は前年12月まで(=前年のレポート)を出す。
    if now.month == 1:
        year, cap = now.year - 1, 12
    else:
        year, cap = now.year, now.month - 1
    print(f"📈 {year}年 契約率推移レポート生成中(確定月上限: {cap}月)...")
    data = gather(gc, year)
    last = min(last_month_with_data(data), cap)
    if last == 0 and now.month != 1:
        # 当年にまだ確定データが無い(年始など) → 前年の確定版にフォールバック
        year -= 1
        print(f"  当年の確定データなし → 前年 {year}年 に切替")
        data = gather(gc, year)
        last = min(last_month_with_data(data), 12)
    if through:
        last = min(last, through)
    if last == 0:
        print("❌ データが取得できませんでした")
        return 1
    months = list(range(1, last + 1))
    for sid in ORDER:
        t = data.get(sid, {})
        got = sorted(int(m) for m in t.get("total", {}))
        print(f"  {NAME6.get(sid)}: 月={got} スタッフ{len(t.get('staff',{}))}")

    stamp = now.strftime('%Y%m%d_%H%M%S_%f')
    items = render_store_pngs(data, year, months, stamp)
    if not items:
        print("❌ 生成できる店舗がありません")
        return 1

    if "--dry" in sys.argv:
        print(f"（--dry: 送信なし / {len(items)}枚生成: {[str(p) for _, p in items]}）")
        return 0
    if "--no-slack" in sys.argv:
        print(f"📵 送信スキップ(--no-slack) {len(items)}枚: {[str(p) for _, p in items]}")
        return 0

    channel = resolve_report_channel()
    if not channel:
        print("❌ 投稿先チャンネル未解決")
        return 1
    if already_sent(channel, year, last):
        print("✓ 当月の推移レポート送信済 → skip (--force で再送)")
        return 0
    mention = "" if "--silent" in sys.argv else "<!channel>\n"
    names = "・".join(NAME6.get(sid, sid) for sid, _ in items)
    comment = (f"{mention}:chart_with_upwards_trend: *La pilates {year}年 契約率推移* "
               f":chart_with_upwards_trend:\n{year}年 1〜{last}月（確定版・店舗別/スタッフ別・平均つき）\n"
               f"{names}（全{len(items)}店舗）")
    ok = upload_pngs(channel, items, comment)
    print(f"  🖼️ 契約率推移レポート {len(items)}枚 送信成功" if ok else "  ❌ 送信失敗")
    for _, p in items:
        try:
            p.unlink()
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
