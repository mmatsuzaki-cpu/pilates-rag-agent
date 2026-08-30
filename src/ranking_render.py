"""ranking_render.py

月間ランキング(レッスン数 / 契約率)を1枚のPNGにレンダリングする。
デザインは dashboard_render.py の La pilates ゴールド系に合わせている。

d = {
  "subtitle": "月間ランキング　2026年8月",
  "as_of": "8月 確定",
  "lesson":   [{"name","store","value"}, ...],          # レッスン数(本)
  "contract": [{"name","store","value","num","den"}, ...],  # 契約率(%)
  "lesson_note": str, "contract_note": str, "foot": str,
}
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BODY_W = 1500


def _badge(i: int) -> str:
    cls = {1: " m1", 2: " m2", 3: " m3"}.get(i, "")
    return f'<span class="medal{cls}">{i}</span>'


def _rows(items: list, kind: str) -> str:
    if not items:
        return '<div class="empty">データがありません</div>'
    out = []
    for i, m in enumerate(items, start=1):
        if kind == "lesson":
            val = f'{m["value"]}<span class="unit">本</span>'
        else:
            val = (f'{m["value"]}<span class="unit">%</span>'
                   f'<span class="sub">({m["num"]}/{m["den"]})</span>')
        top = " top" if i <= 3 else ""
        out.append(
            f'<div class="row{top}">{_badge(i)}'
            f'<span class="nm">{m["name"]}</span>'
            f'<span class="st">{m["store"]}</span>'
            f'<span class="val">{val}</span></div>')
    return "".join(out)


def build_html(d: dict) -> str:
    n_lesson = len(d.get("lesson") or [])
    n_contract = len(d.get("contract") or [])
    return f"""<html><head><meta charset="utf-8"><style>
:root {{ --bg:#FBF8F1; --ink:#2E2A24; --bronze:#9C7A5B; --gold:#C9962F;
  --gold-d:#A87B45; --line:#ECE3D5; --green:#2F7D4F; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ width:{BODY_W}px; background:var(--bg); color:var(--ink);
  font-family:"Noto Sans CJK JP",sans-serif; padding:44px 46px 40px; }}
.head {{ display:flex; align-items:flex-end; gap:16px;
  border-bottom:2.5px solid var(--gold-d); padding-bottom:18px; margin-bottom:26px; }}
.spark {{ font-size:30px; color:var(--gold); }}
.brand {{ font-family:"Noto Serif CJK JP","Georgia",serif; font-weight:700; font-size:44px;
  background:linear-gradient(100deg,var(--bronze) 5%,var(--gold) 95%);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
.sub-t {{ font-size:20px; font-weight:700; color:#6B6357; padding-bottom:6px; }}
.asof {{ margin-left:auto; background:linear-gradient(135deg,var(--bronze),var(--gold));
  color:#fff; font-weight:800; font-size:17px; padding:8px 18px; border-radius:999px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:26px; }}
.card {{ background:#fff; border:1px solid var(--line); border-radius:20px;
  padding:24px 26px 18px; box-shadow:0 2px 10px rgba(0,0,0,.04); }}
.card-t {{ font-family:"Noto Serif CJK JP",serif; font-size:25px; font-weight:900;
  color:var(--gold-d); display:flex; align-items:center; gap:10px;
  border-bottom:1.5px dashed var(--line); padding-bottom:12px; margin-bottom:6px; }}
.row {{ display:flex; align-items:center; gap:14px; padding:13px 4px;
  border-bottom:1px solid #F4EEE3; }}
.row:last-child {{ border-bottom:none; }}
.row.top {{ background:linear-gradient(90deg,#FFFBF0,#fff); border-radius:10px; }}
.medal {{ width:34px; height:34px; border-radius:50%; flex:none;
  display:flex; align-items:center; justify-content:center;
  font-weight:900; font-size:16px; background:#F0EAE0; color:#8A8074; }}
.m1 {{ background:linear-gradient(135deg,#E8C86A,#C9962F); color:#fff; }}
.m2 {{ background:linear-gradient(135deg,#D9D9D9,#A8A8A8); color:#fff; }}
.m3 {{ background:linear-gradient(135deg,#D6A882,#9C7A5B); color:#fff; }}
.nm {{ font-size:21px; font-weight:800; }}
.st {{ font-size:14px; color:#8A8074; background:#F6F1E8;
  padding:3px 10px; border-radius:999px; }}
.val {{ margin-left:auto; font-family:"Noto Serif CJK JP",serif;
  font-size:29px; font-weight:900; color:var(--green); line-height:1; }}
.unit {{ font-size:16px; margin-left:2px; }}
.sub {{ font-size:15px; color:#8A8074; font-weight:700; margin-left:7px; }}
.empty {{ padding:26px 4px; color:#9A9086; font-size:16px; text-align:center; }}
.note {{ margin-top:12px; font-size:13px; color:#9A9086; text-align:right; }}
.foot {{ margin-top:22px; font-size:13px; color:#9A9086; text-align:right; }}
</style></head><body>
<div class="head"><span class="spark">✳</span>
  <span class="brand">La pilates</span>
  <span class="sub-t">{d['subtitle']}</span>
  <span class="asof">{d['as_of']}</span></div>
<div class="grid">
  <div class="card"><div class="card-t"><span>🏋️</span>レッスン数 TOP{n_lesson or ''}</div>
    {_rows(d.get('lesson'), 'lesson')}
    <div class="note">{d.get('lesson_note','')}</div></div>
  <div class="card"><div class="card-t"><span>🎯</span>契約率 TOP{n_contract or ''}</div>
    {_rows(d.get('contract'), 'contract')}
    <div class="note">{d.get('contract_note','')}</div></div>
</div>
<div class="foot">{d.get('foot','')}</div></body></html>"""


def render_ranking_to_png(d: dict, out_path: Path) -> Path:
    """ランキング画像を1枚生成して out_path に保存"""
    html = build_html(d)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": BODY_W, "height": 900}, device_scale_factor=2)
        pg.set_content(html, wait_until="networkidle")
        # TOP5など内容が少ないと viewport 高さのぶん下に余白が出る。
        # body は viewport 高さに広がってしまうため、最後の要素の下端 +
        # body の padding-bottom を実コンテンツ高さとして viewport を合わせ直す。
        h = pg.evaluate("""() => {
            const el = document.querySelector('.foot') || document.body;
            const pb = parseFloat(getComputedStyle(document.body).paddingBottom) || 0;
            return Math.ceil(el.getBoundingClientRect().bottom + pb);
        }""")
        pg.set_viewport_size({"width": BODY_W, "height": max(int(h), 200)})
        pg.locator("body").screenshot(path=str(out_path))
        b.close()
    print(f"  🖼  ランキング画像: {out_path}")
    return out_path
