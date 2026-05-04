"""alert_sender.py

ピラティス実績速報をSlack #ピラティス_実績進捗 に送信。
@channel メンション付き。

【データソース = 各店舗の集計表のみ】(2026-05-04 全面リファクタ)
- 売上・利益・口コミ表示は廃止(CSV取得は月2回 = 15日/月末のみ)
- 表示項目: 契約率 / 会員数 / 新規数 / 紹介数 / 解約数 の5つに絞る
- タイトル表示: 「{今月}月{日}日時点の実績」(毎朝の報告に合わせる)

使い方:
    python3 src/alert_sender.py            # 通常速報
    python3 src/alert_sender.py --report mid  # 月中報告(15日時点)
    python3 src/alert_sender.py --report end  # 月末報告
    python3 src/alert_sender.py --dry         # ドライラン(送信せず内容表示)
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import STORES, SPREADSHEET_ID, get_gspread_client, slack_webhook_send
from store_summary_reader import get_all_stores_summary

# 「ピラティス実績全部」スプシ(口コミシートあり)
DASHBOARD_SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"


def safe_int(v):
    try:
        return int(str(v).replace(",", "").strip()) if v else 0
    except (ValueError, TypeError):
        return 0


def get_reviews_from_kuchikomi(gc):
    """「ピラティス実績全部」スプシの「口コミ」シートから最新月の口コミを取得
    シート構造:
      列: 月初時点 / '' / 目標 / 12月 / 2025年1月 / ... / 2026年X月 / 前月比
      行2-6: Google × 5店舗(川越/大宮/高崎/神戸元町/西宮北口)
      行7-11: HPB × 5店舗
    最新月列 = 「前月比」の左の列
    """
    sh = gc.open_by_key(DASHBOARD_SSID)
    ws = sh.worksheet("口コミ")
    v = ws.get_all_values()
    header = v[0]
    # 「前月比」の左の列が最新月
    try:
        latest_col = header.index("前月比") - 1
    except ValueError:
        latest_col = len(header) - 1

    google_rows = {"S001": 1, "S002": 2, "S003": 3, "S004": 4, "S005": 5}  # 0-indexed
    hpb_rows    = {"S001": 6, "S002": 7, "S003": 8, "S004": 9, "S005": 10}

    result = {}
    for sid in ['S001', 'S002', 'S003', 'S004', 'S005']:
        g_row = v[google_rows[sid]] if google_rows[sid] < len(v) else []
        h_row = v[hpb_rows[sid]]    if hpb_rows[sid]    < len(v) else []
        g = safe_int(g_row[latest_col]) if latest_col < len(g_row) else 0
        h = safe_int(h_row[latest_col]) if latest_col < len(h_row) else 0
        result[sid] = {'google': g, 'hpb': h}
    return result


def contract_status(rate: float) -> str:
    """契約率の信号機判定 (50%以上🟢 / 30-50%🟡 / 30%未満🔴)"""
    if rate >= 0.50: return "🟢"
    if rate >= 0.30: return "🟡"
    return "🔴"


def build_message(data: dict, label: str) -> str:
    """label: 「5月3日時点の実績」など、見出し用ラベル"""

    # 信号機判定(契約率ベース)
    statuses = {sid: contract_status(d["contract_rate"]) for sid, d in data.items()}
    red_stores = [s for s in STORES if statuses.get(s["id"]) == "🔴"]
    yellow_stores = [s for s in STORES if statuses.get(s["id"]) == "🟡"]
    green_stores = [s for s in STORES if statuses.get(s["id"]) == "🟢"]

    lines = []
    lines.append("<!channel>")
    lines.append(f"📊 *ピラティス実績 {label}*")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━")
    if red_stores:
        lines.append(f"🚨 *要対応* ({len(red_stores)}): " + " / ".join(s["name"] for s in red_stores))
    if yellow_stores:
        lines.append(f"⚠️ *注意* ({len(yellow_stores)}): " + " / ".join(s["name"] for s in yellow_stores))
    if green_stores:
        lines.append(f"✅ *好調* ({len(green_stores)}): " + " / ".join(s["name"] for s in green_stores))
    lines.append("━━━━━━━━━━━━━━")
    lines.append("")

    # 店舗別 (🔴→🟡→🟢順)
    sort_key = {"🔴": 0, "🟡": 1, "🟢": 2, "⚪": 3}
    sorted_stores = sorted(STORES, key=lambda s: sort_key.get(statuses.get(s["id"], "⚪"), 9))

    for store in sorted_stores:
        sid = store["id"]
        if sid not in data:
            continue
        d = data[sid]
        st = statuses.get(sid, "⚪")
        cr = d["contract_rate"] * 100

        # 解約率 = 解約数 ÷ 会員数
        cancel_rate = (d['cancels'] / d['members'] * 100) if d['members'] else 0
        # 口コミ
        rv = d.get('reviews', {'google': 0, 'hpb': 0})

        lines.append(f"{st} *{store['name']}*  ─────────")
        lines.append("")
        lines.append(f"📈 *契約率*  {cr:.0f}%  ({d['contracts']}/{d['newcomers']})")
        lines.append(f"👥 *会員数*  {d['members']:,}人")
        lines.append(f"🆕 *新規数*  {d['newcomers']}人")
        lines.append(f"🚪 *解約数*  {d['cancels']}人  (解約率 {cancel_rate:.1f}%)")
        lines.append(f"🤝 *紹介数*  {d['referrals']}人")
        lines.append(f"⭐ *Google口コミ*  {rv['google']}件")
        lines.append(f"📱 *HPB口コミ*  {rv['hpb']}件")
        lines.append("")
        lines.append("")

    # 全店合計
    total_members = sum(d["members"] for d in data.values())
    total_new = sum(d["newcomers"] for d in data.values())
    total_contracts = sum(d["contracts"] for d in data.values())
    total_referrals = sum(d["referrals"] for d in data.values())
    total_cancels = sum(d["cancels"] for d in data.values())
    total_cr = (total_contracts / total_new * 100) if total_new else 0

    total_cancel_rate = (total_cancels / total_members * 100) if total_members else 0
    total_google = sum(d.get('reviews', {}).get('google', 0) for d in data.values())
    total_hpb = sum(d.get('reviews', {}).get('hpb', 0) for d in data.values())

    lines.append("━━━━━━━━━━━━━━")
    lines.append("🏆 *全店合計*")
    lines.append("")
    lines.append(f"📈 *契約率*  {total_cr:.0f}%  ({total_contracts}/{total_new})")
    lines.append(f"👥 *会員数*  {total_members:,}人")
    lines.append(f"🆕 *新規数*  {total_new}人")
    lines.append(f"🚪 *解約数*  {total_cancels}人  (解約率 {total_cancel_rate:.1f}%)")
    lines.append(f"🤝 *紹介数*  {total_referrals}人")
    lines.append(f"⭐ *Google口コミ*  {total_google:,}件")
    lines.append(f"📱 *HPB口コミ*  {total_hpb:,}件")

    return "\n".join(lines)


def make_label(report_type: str) -> str:
    """見出しラベル生成
    daily → 「5月3日時点の実績」(今日の月日)
    mid   → 「5月15日時点の実績」(=その月の15日)
    end   → 「5月末時点の実績」(=月末確定)
    """
    now = datetime.now()
    if report_type == "mid":
        return f"{now.month}月15日時点の実績"
    elif report_type == "end":
        # 月末は前月分の確定値を扱うことが多い(1日に走る想定)
        # 当月1日に走るなら→前月末の数値を出す
        if now.day == 1:
            prev_year, prev_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
            return f"{prev_month}月末時点の実績"
        return f"{now.month}月末時点の実績"
    else:
        return f"{now.month}月{now.day}日時点の実績"


def main():
    report_type = "daily"
    if "--report" in sys.argv:
        idx = sys.argv.index("--report")
        if idx + 1 < len(sys.argv):
            arg = sys.argv[idx + 1].lower()
            if arg in ("mid", "中間"): report_type = "mid"
            elif arg in ("end", "月末"): report_type = "end"

    # 取得対象月の決定
    now = datetime.now()
    if report_type == "end" and now.day == 1:
        # 月初に走る月末レポート → 前月の値を取得
        target_year, target_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    else:
        target_year, target_month = now.year, now.month

    print(f"📊 {report_type}レポート生成中 ({target_year}-{target_month:02d})...")

    # 先に口コミシート(軽量・1 read)を取得 → quota確保
    reviews = {}
    try:
        gc = get_gspread_client()
        reviews = get_reviews_from_kuchikomi(gc)
        print(f"  ✅ 口コミシート 取得完了")
    except Exception as e:
        print(f"  ⚠️ 口コミ取得失敗: {e}")

    # 集計表から5項目取得(契約率/会員数/新規/解約/紹介)※多数 read 消費
    summary = get_all_stores_summary(target_year, target_month)
    if not summary:
        print("❌ 集計表取得失敗")
        return 1
    print(f"  ✅ 取得店舗: {len(summary)}")

    # 口コミをマージ
    for sid in summary:
        summary[sid]['reviews'] = reviews.get(sid, {'google': 0, 'hpb': 0})

    label = make_label(report_type)
    msg = build_message(summary, label)

    if "--dry" in sys.argv:
        print("\n" + "=" * 60)
        print(msg)
        print("=" * 60)
        return 0

    if slack_webhook_send(msg):
        print("✅ Slack送信成功")
        return 0
    print("❌ Slack送信失敗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
