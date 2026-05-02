"""alert_sender.py

ピラティス実績速報をSlack #ピラティス_実績進捗 に送信。
@channel メンション付き。

使い方:
    python3 src/alert_sender.py            # 通常速報(最新月のデータ)
    python3 src/alert_sender.py --report mid  # 月中報告(月中(1-15日))
    python3 src/alert_sender.py --report end  # 月末報告(月末(1-月末))
    python3 src/alert_sender.py --dry         # ドライラン
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    STORES, get_jisseki_data, format_money,
    status_emoji, contract_status,
    slack_webhook_send,
)


# 改善策プール(本部マニュアル準拠の簡易版)
IMPROVEMENT_SUGGESTIONS = {
    "contract_rate": [
        "🎯 *クロージング時の姿勢改善*\n　　 横並びNG → 片膝立ちで目線を下に(威圧感回避)",
        "📝 *言葉遣い統一(マニュアル50項目)*\n　　 「いいですか?」→「よろしいでしょうか?」など",
        "🎬 *Before↔Afterテスト(本部施策2025/5〜)*\n　　 変化を体感→成約率UP",
    ],
    "cancel_rate": [
        "🚪 *お見送り徹底*\n　　 他のレッスン中でも手を止めて「少々お待ちください」→玄関まで",
        "📵 *スタッフ間私語NG運用*\n　　 お客様前でタメ口・足組み・腕組み・お菓子全てNG",
        "💝 *月会費の対価意識*\n　　 「品質の高いレッスンを提供する」をチームで毎日唱和",
    ],
}


def overall_status(d: dict) -> str:
    """信号機判定 (B案: 🔴2個以上→🔴, 1個か🟡あり→🟡, 全🟢→🟢)"""
    sales_ach = d["sales"] / d["sales_target"] if d["sales_target"] else 0
    profit_ach = d["profit"] / d["profit_target"] if d["profit_target"] else 0
    statuses = [status_emoji(sales_ach), status_emoji(profit_ach), contract_status(d["contract_rate"])]
    red = statuses.count("🔴")
    yellow = statuses.count("🟡")
    if red >= 2:
        return "🔴"
    if red == 1 or yellow >= 1:
        return "🟡"
    return "🟢"


def build_message(data: dict, report_type: str = "daily") -> str:
    today_str = datetime.now().strftime("%-m/%-d")

    if report_type == "mid":
        title_suffix = "中間報告 (1日-15日)"
    elif report_type == "end":
        title_suffix = "月末報告 (1日-月末)"
    else:
        title_suffix = "速報"

    # ステータス判定
    statuses = {sid: overall_status(data[sid]) for sid in data}
    red_stores = [s for s in STORES if statuses.get(s["id"]) == "🔴"]
    yellow_stores = [s for s in STORES if statuses.get(s["id"]) == "🟡"]
    green_stores = [s for s in STORES if statuses.get(s["id"]) == "🟢"]

    lines = []
    lines.append("<!channel>")
    lines.append(f"🌅 *ピラティス実績{title_suffix}*  {today_str}")
    lines.append("💴 *全て税抜表示*  / 目標は月次")
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
        sales_ach = d["sales"] / d["sales_target"] if d["sales_target"] else 0
        profit_ach = d["profit"] / d["profit_target"] if d["profit_target"] else 0
        sales_st = status_emoji(sales_ach)
        profit_st = status_emoji(profit_ach)
        cr_st = contract_status(d["contract_rate"])

        lines.append(f"{st} *{store['name']}* ({d['year_month']} {d['period']})  ─────────")
        lines.append("")
        lines.append("💰 *売上*")
        lines.append(f"　 *{format_money(d['sales'])}円*  ⇨  目標 {format_money(d['sales_target'])}円  "
                     f"({sales_ach*100:.0f}%{' '+sales_st if sales_st in ('🔴','🟡') else ''})")
        lines.append("")
        lines.append("💎 *利益*")
        lines.append(f"　 *{format_money(d['profit'])}円*  ⇨  目標 {format_money(d['profit_target'])}円  "
                     f"({profit_ach*100:.0f}%{' '+profit_st if profit_st in ('🔴','🟡') else ''})")
        lines.append("")
        lines.append("📈 *契約率*")
        lines.append(f"　 *{d['contract_rate']*100:.0f}%{' '+cr_st if cr_st in ('🔴','🟡') else ''}* "
                     f"({d['contracts']}/{d['newcomers']})  ⇨  目標 50%以上")
        lines.append("")
        lines.append(f"👥 *会員数*  {d['members']:,}人")
        lines.append(f"🆕 *新規数*  {d['newcomers']}人  /  🤝 *紹介数*  {d['referrals']}人")
        lines.append(f"🚪 *解約数*  {d['cancels']}人")
        if d['google_review'] or d['hpb_review']:
            total = d['google_review'] + d['hpb_review']
            lines.append(f"⭐ *口コミ*  {total}件 (Google {d['google_review']} + HPB {d['hpb_review']})")
        lines.append("")

        # 改善策(🔴判定の項目のみ)
        cr_st_only = contract_status(d["contract_rate"])
        if st == "🔴" and cr_st_only == "🔴":
            lines.append("━━━━━━━━━━━")
            lines.append("💡 *改善策*")
            lines.append("")
            lines.append("【📈 契約率低迷】")
            lines.append("")
            for s in IMPROVEMENT_SUGGESTIONS["contract_rate"]:
                lines.append(f"　▸ {s}")
                lines.append("")
        lines.append("")

    # 全店合計
    total_sales = sum(d["sales"] for d in data.values())
    total_profit = sum(d["profit"] for d in data.values())
    total_members = sum(d["members"] for d in data.values())
    total_new = sum(d["newcomers"] for d in data.values())
    total_sales_target = sum(d["sales_target"] for d in data.values())
    total_profit_target = sum(d["profit_target"] for d in data.values())

    lines.append("━━━━━━━━━━━━━━")
    lines.append("🏆 *全店合計*")
    s_ach = total_sales / total_sales_target * 100 if total_sales_target else 0
    p_ach = total_profit / total_profit_target * 100 if total_profit_target else 0
    lines.append(f"💰 売上 *{format_money(total_sales)}円*  目標 {format_money(total_sales_target)}円 ({s_ach:.0f}%)")
    lines.append(f"💎 利益 *{format_money(total_profit)}円*  目標 {format_money(total_profit_target)}円 ({p_ach:.0f}%)")
    lines.append(f"👥 会員数 *{total_members:,}人*  /  🆕 新規 *{total_new}人*")

    return "\n".join(lines)


def main():
    report_type = "daily"
    if "--report" in sys.argv:
        idx = sys.argv.index("--report")
        if idx + 1 < len(sys.argv):
            arg = sys.argv[idx + 1].lower()
            if arg in ("mid", "中間"): report_type = "mid"
            elif arg in ("end", "月末"): report_type = "end"

    period = None
    if report_type == "mid":
        period = "月中(1-15日)"
    elif report_type == "end":
        period = "月末(1-月末)"

    print(f"📊 {report_type}レポート生成中(period={period})...")
    data = get_jisseki_data(period=period)
    if not data:
        print("❌ データ取得失敗")
        return 1
    print(f"  取得店舗: {len(data)}")

    msg = build_message(data, report_type=report_type)

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
