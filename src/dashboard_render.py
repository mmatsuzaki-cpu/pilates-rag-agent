#!/usr/bin/env python3
"""ラピラティス実績ダッシュボード生成
  data.json を読み込み → HTML を組み立て → Playwright で PNG 出力
使い方:  python3 dashboard_render.py [data.json] [out.png]

harinature-rag-agent/src/dashboard_render.py からの移植 (2026-06-04)。
  グリッド自動列数 / body幅可変 / 3列以上でフォント段階縮小 のロジックはそのまま流用。
  カード項目(store_card / total_block)を ラピラティス KPI に作り替え:
    ①契約率 ②会員数 ③新規数 ④解約数(+解約率) ⑤紹介数 ⑥Google口コミ ⑦HPB口コミ
  色のしきい値(契約率ベース)は harinature と共通: 緑=50%↑ / 橙=1〜49% / 赤=0% / 灰=母数なし
  列数ルール: n=1→1列, 2-4→2列, 5-9→3列, n≥10→4列
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# ---- レイアウト密度 -----------------------------------------------
CARD_TARGET_W = 500  # カード1枚の目標幅(px)
GAP = 22             # カード間の隙間
PAD_X = 48           # body の左右 padding
MIN_BODY_W = 1080    # 最低 body 幅 (1列でも狭くしすぎない)


def cols_for(n: int) -> int:
    """店舗数 n から列数を決定"""
    if n <= 1:
        return 1
    if n <= 4:
        return 2
    if n <= 9:
        return 3
    return 4


def density_styles(n: int) -> dict:
    """店舗数に応じたサイズ・余白セット
       3列以上で カード内padding と 主要フォント を段階縮小
    """
    ncols = cols_for(n)
    body_w = max(MIN_BODY_W, PAD_X * 2 + ncols * CARD_TARGET_W + (ncols - 1) * GAP)
    if ncols >= 4:
        card_pad = "14px 16px"
        store_name = 20
        rate_size = 20
        kpi_label = 14
        num_size = 20
    elif ncols >= 3:
        card_pad = "16px 18px"
        store_name = 22
        rate_size = 24
        kpi_label = 15
        num_size = 24
    else:
        card_pad = "20px 22px"
        store_name = 24
        rate_size = 27
        kpi_label = 16
        num_size = 27
    return {
        "ncols": ncols,
        "body_w": body_w,
        "grid_template": f"repeat({ncols},1fr)",
        "card_pad": card_pad,
        "store_name": store_name,
        "rate_size": rate_size,
        "kpi_label": kpi_label,
        "num_size": num_size,
    }


# ---- 色のしきい値（契約率 → 色）-----------------------------------
def rate_class(num, den):
    if den == 0:
        return "none"          # 母数なし（—）
    rate = num / den
    if rate == 0:
        return "zero"          # 0%（要注力）
    if rate < 0.5:
        return "mid"           # 1〜49%
    return "good"              # 50%以上


def rate_label(num, den):
    if den == 0:
        return "—"
    return f"{round(num/den*100)}%"


def signal_emoji(num, den):
    """契約率ベースの信号機絵文字 (カード見出し用)"""
    return {"good": "🟢", "mid": "🟡", "zero": "🔴", "none": "⚪"}[rate_class(num, den)]


# ---- KPI 行 ------------------------------------------------------
def rate_kpi(no, label, num, den):
    """率を表示する行 (契約率)"""
    cls = rate_class(num, den)
    return f"""
      <div class="kpi">
        <div class="kpi-label"><span class="kpi-no">{no}</span>{label}</div>
        <div class="kpi-val">
          <span class="rate rate-{cls}">{rate_label(num, den)}</span>
          <span class="frac">({num}/{den})</span>
        </div>
      </div>"""


def num_kpi(no, label, value, unit="", extra=""):
    """数値を表示する行 (会員数/新規数/解約数/紹介数/口コミ)"""
    return f"""
      <div class="kpi">
        <div class="kpi-label"><span class="kpi-no">{no}</span>{label}</div>
        <div class="kpi-val">
          <span class="num">{value}</span><span class="unit">{unit}</span>
          {extra}
        </div>
      </div>"""


# ---- 店舗カード --------------------------------------------------
def store_card(s):
    emoji = signal_emoji(s["contract"]["num"], s["contract"]["den"])
    # 解約率 = 解約数 / 会員数
    cancel_rate = (s["cancels"] / s["members"] * 100) if s["members"] else 0
    cc = "cancel-warn" if s["cancels"] > 0 else "cancel-ok"
    cancel_extra = f'<span class="cancel {cc}">解約率 {cancel_rate:.1f}%</span>'
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="store-name">{emoji} {s['name']}</span>
      </div>
      <div class="kpis">
        {rate_kpi(1, "契約率", s['contract']['num'], s['contract']['den'])}
        {num_kpi(2, "会員数", f"{s['members']:,}", "人")}
        {num_kpi(3, "新規数", s['newcomers'], "人")}
        {num_kpi(4, "解約数", s['cancels'], "人", cancel_extra)}
        {num_kpi(5, "紹介数", s['referrals'], "人")}
        {num_kpi(6, "Google口コミ", s['google'], "件")}
        {num_kpi(7, "HPB口コミ", s['hpb'], "件")}
      </div>
    </div>"""


# ---- 合計ブロック ------------------------------------------------
def total_block(t):
    cancel_rate = (t["cancels"] / t["members"] * 100) if t["members"] else 0
    cls = rate_class(t["contract"]["num"], t["contract"]["den"])

    def num_cell(label, value, unit=""):
        return f"""
        <div class="tcell">
          <div class="tcell-label">{label}</div>
          <div class="tcell-rate">{value}</div>
          <div class="tcell-frac">{unit}</div>
        </div>"""
    return f"""
    <div class="total">
      <div class="total-head">
        <span class="total-title">全店合計</span>
      </div>
      <div class="tcells">
        <div class="tcell">
          <div class="tcell-label">契約率</div>
          <div class="tcell-rate rate-{cls}">{rate_label(t['contract']['num'], t['contract']['den'])}</div>
          <div class="tcell-frac">({t['contract']['num']}/{t['contract']['den']})</div>
        </div>
        {num_cell("会員数", f"{t['members']:,}", "人")}
        {num_cell("新規数", t['newcomers'], "人")}
        {num_cell("解約数", t['cancels'], f"解約率 {cancel_rate:.1f}%")}
        {num_cell("紹介数", t['referrals'], "人")}
        {num_cell("Google口コミ", t['google'], "件")}
        {num_cell("HPB口コミ", t['hpb'], "件")}
      </div>
    </div>"""


# ---- 共有 CSS ----------------------------------------------------
def _css(s):
    return f"""
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  :root {{
    /* La pilates ブランドカラー: ブロンズ→ゴールドのグラデ / 暖白背景 */
    --bg:#FDFBF7; --paper:#FFFFFF; --ink:#4A3F35; --sub:#9A8B79;
    --bronze:#9C7A5B; --gold:#C9962F; --gold-d:#A87B45; --line:#ECE3D5;
    --good:#3C6B4A; --mid:#C9962F; --zero:#C25B4A; --none:#B7AC9C;
  }}
  body {{
    width:{s['body_w']}px; background:var(--bg); color:var(--ink);
    font-family:"Noto Sans CJK JP",sans-serif; padding:44px {PAD_X}px 40px;
    -webkit-font-smoothing:antialiased;
  }}
  /* header */
  .header {{ display:flex; align-items:flex-end; justify-content:space-between;
    border-bottom:2.5px solid var(--gold-d); padding-bottom:18px; margin-bottom:26px; }}
  .h-left {{ display:flex; align-items:baseline; gap:16px; }}
  .spark {{ font-size:30px; line-height:1; color:var(--gold);
    background:linear-gradient(135deg,var(--bronze),var(--gold));
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
  .brand {{ font-family:"Noto Serif CJK JP","Georgia",serif; font-weight:700; font-size:44px;
    letter-spacing:.02em; background:linear-gradient(100deg,var(--bronze) 5%,var(--gold) 95%);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
  .sub {{ font-size:21px; font-weight:700; color:var(--sub); }}
  .asof {{ font-size:17px; color:#fff; padding:7px 16px; border-radius:999px;
    background:linear-gradient(135deg,var(--bronze),var(--gold));
    font-weight:700; letter-spacing:.02em; }}
  /* total: 店舗数に関係なく常に 横並び (項目数に応じて自動) */
  .total {{ background:linear-gradient(135deg,var(--bronze),var(--gold));
    border-radius:18px; padding:22px 28px; margin-bottom:26px; color:#fff;
    box-shadow:0 8px 22px rgba(168,123,69,.25); }}
  .total-head {{ display:flex; align-items:baseline; gap:14px; margin-bottom:14px; }}
  .total-title {{ font-family:"Noto Serif CJK JP",serif; font-size:26px; font-weight:900; letter-spacing:.06em; }}
  .tcells {{ display:grid; grid-template-columns:repeat(7,1fr); gap:12px; }}
  .tcell {{ background:rgba(255,255,255,.12); border-radius:12px; padding:14px 14px; }}
  .tcell-label {{ font-size:13px; opacity:.85; margin-bottom:6px; font-weight:600; }}
  .tcell-rate {{ font-size:30px; font-weight:900; line-height:1; font-family:"Noto Serif CJK JP",serif; }}
  .tcell-frac {{ font-size:13px; opacity:.8; margin-top:4px; }}
  .total .rate-good {{ color:#BFE6C8; }}
  .total .rate-mid  {{ color:#F2CE8F; }}
  .total .rate-zero {{ color:#F2B3A8; }}
  .total .rate-none {{ color:#D8DDD6; }}
  /* grid: 店舗数に応じて列数自動 (n=1→1列, 2-4→2列, 5-9→3列, ≥10→4列) */
  .grid {{ display:grid; grid-template-columns:{s['grid_template']}; gap:{GAP}px; }}
  .card {{ background:var(--paper); border:1px solid var(--line); border-radius:16px;
    padding:{s['card_pad']}; box-shadow:0 3px 10px rgba(60,55,80,.06); }}
  .card-head {{ display:flex; align-items:baseline; gap:12px; padding-bottom:12px;
    border-bottom:1.5px dashed var(--line); margin-bottom:6px; }}
  .store-name {{ font-family:"Noto Serif CJK JP",serif; font-size:{s['store_name']}px; font-weight:900; color:var(--gold-d); }}
  .kpis {{ }}
  .kpi {{ display:flex; align-items:center; justify-content:space-between;
    padding:10px 0; border-bottom:1px solid #F2EEF8; }}
  .kpi:last-child {{ border-bottom:none; }}
  .kpi-label {{ font-size:{s['kpi_label']}px; font-weight:600; color:#3a3550; display:flex; align-items:center; gap:9px; }}
  .kpi-no {{ display:inline-grid; place-items:center; width:22px; height:22px; border-radius:6px;
    background:#EDE6F6; color:var(--gold-d); font-size:13px; font-weight:800; }}
  .kpi-val {{ display:flex; align-items:baseline; gap:8px; }}
  .rate {{ font-size:{s['rate_size']}px; font-weight:900; font-family:"Noto Serif CJK JP",serif; line-height:1; }}
  .rate-good {{ color:var(--good); }} .rate-mid {{ color:var(--mid); }}
  .rate-zero {{ color:var(--zero); }} .rate-none {{ color:var(--none); }}
  .frac {{ font-size:14px; color:var(--sub); }}
  .num {{ font-size:{s['num_size']}px; font-weight:900; font-family:"Noto Serif CJK JP",serif; color:var(--ink); line-height:1; }}
  .unit {{ font-size:14px; color:var(--sub); margin-left:2px; }}
  .cancel {{ font-size:12px; font-weight:700; padding:2px 9px; border-radius:999px; margin-left:4px; }}
  .cancel-ok {{ background:#EAF1EB; color:var(--good); }}
  .cancel-warn {{ background:#F7E2DD; color:var(--zero); }}
  /* staff(スタッフ別契約率) */
  .store-rate {{ margin-left:auto; font-size:20px; font-weight:900; font-family:"Noto Serif CJK JP",serif; line-height:1; }}
  .store-frac {{ font-size:13px; color:var(--sub); margin-left:4px; font-weight:600; }}
  .staff-list {{ }}
  .srow {{ display:flex; align-items:center; justify-content:space-between; padding:10px 0; border-bottom:1px solid #F2EEF8; }}
  .srow:last-child {{ border-bottom:none; }}
  .sname {{ font-size:{s['kpi_label']}px; font-weight:700; color:#3a3550; }}
  .sval {{ display:flex; align-items:baseline; gap:8px; }}
  .s-empty {{ font-size:14px; color:var(--none); padding:10px 0; }}
  .footer {{ margin-top:24px; text-align:right; font-size:12px; color:var(--none); letter-spacing:.05em; }}
"""


# ---- HTML 全体 (店舗別ダッシュボード) ----------------------------
def build_html(d):
    n = len(d["stores"])
    s = density_styles(n)
    cards = "".join(store_card(st) for st in d["stores"])
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>{_css(s)}</style></head><body>
  <div class="header">
    <div class="h-left">
      <span class="spark">✳</span>
      <span class="brand">{d['title']}</span>
      <span class="sub">{d['subtitle']}</span>
    </div>
    <span class="asof">{d['as_of']}</span>
  </div>
  {total_block(d['total'])}
  <div class="grid">{cards}</div>
  <div class="footer">契約率の色分け　緑=50%以上 / 橙=1〜49% / 赤=0% / 灰=母数なし</div>
</body></html>"""


# ---- スタッフ別契約率カード --------------------------------------
def staff_card(s_):
    emoji = signal_emoji(s_["contract"]["num"], s_["contract"]["den"])
    cls = rate_class(s_["contract"]["num"], s_["contract"]["den"])
    staff = s_.get("staff", [])
    if staff:
        rows = "".join(
            f'<div class="srow"><span class="sname">{m["name"]}</span>'
            f'<span class="sval"><span class="rate rate-{rate_class(m["num"], m["den"])}">{rate_label(m["num"], m["den"])}</span>'
            f'<span class="frac">({m["num"]}/{m["den"]})</span></span></div>'
            for m in staff
        )
    else:
        rows = '<div class="s-empty">実績データなし</div>'
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="store-name">{emoji} {s_['name']}</span>
        <span class="store-rate rate-{cls}">{rate_label(s_['contract']['num'], s_['contract']['den'])}<span class="store-frac">({s_['contract']['num']}/{s_['contract']['den']})</span></span>
      </div>
      <div class="staff-list">{rows}</div>
    </div>"""


# ---- スタッフ別 HTML 全体 ----------------------------------------
def build_staff_html(d):
    n = len(d["stores"])
    s = density_styles(n)
    cards = "".join(staff_card(st) for st in d["stores"])
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>{_css(s)}</style></head><body>
  <div class="header">
    <div class="h-left">
      <span class="spark">✳</span>
      <span class="brand">{d['title']}</span>
      <span class="sub">{d['subtitle']}</span>
    </div>
    <span class="asof">{d['as_of']}</span>
  </div>
  <div class="grid">{cards}</div>
  <div class="footer">契約率の色分け　緑=50%以上 / 橙=1〜49% / 赤=0% / 灰=母数なし　|　数字 = 契約/新規</div>
</body></html>"""


def render_to_png(d, out_path: Path):
    """1件レンダリング (テスト/本番共用)"""
    n = len(d["stores"])
    s = density_styles(n)
    html = build_html(d)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": s["body_w"], "height": 800},
                        device_scale_factor=2)
        pg.set_content(html, wait_until="networkidle")
        pg.locator("body").screenshot(path=str(out_path))
        b.close()
    print(f"wrote {out_path}  (n={n}, ncols={s['ncols']}, body={s['body_w']}px)")


def render_staff_to_png(d, out_path: Path):
    """スタッフ別契約率ダッシュボードを1件レンダリング"""
    n = len(d["stores"])
    s = density_styles(n)
    html = build_staff_html(d)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": s["body_w"], "height": 800},
                        device_scale_factor=2)
        pg.set_content(html, wait_until="networkidle")
        pg.locator("body").screenshot(path=str(out_path))
        b.close()
    print(f"wrote {out_path}  (staff / n={n}, ncols={s['ncols']}, body={s['body_w']}px)")


def main():
    # 使い方: dashboard_render.py [data.json] [out.png] [--staff]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data_path = Path(args[0]) if len(args) > 0 else Path("data.json")
    out_path = Path(args[1]) if len(args) > 1 else Path("out.png")
    d = json.loads(data_path.read_text(encoding="utf-8"))
    if "--staff" in sys.argv:
        render_staff_to_png(d, out_path)
    else:
        render_to_png(d, out_path)


if __name__ == "__main__":
    main()
