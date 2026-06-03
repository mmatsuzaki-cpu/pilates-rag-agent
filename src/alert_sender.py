"""alert_sender.py

ラピラティス実績速報をSlack #ピラティス_実績進捗 に送信。
@channel メンション付き。

【データソース = 各店舗の集計表のみ】(2026-05-04 全面リファクタ)
- 売上・利益表示は廃止(CSV取得は月2回 = 15日/月末のみ)
- 表示項目: 契約率 / 会員数 / 新規数 / 解約数 / 紹介数 / Google口コミ / HPB口コミ

【daily 配信形式】(2026-06-04 画像ダッシュボード化)
- harinature と同じポップな画像ダッシュボードを Bot Token で投稿
- ラピラティスの集計は「当月累計/スナップショット」のみで当日フローが取れないため、
  当月累計ダッシュボード 1枚 + 🌸見出し(@channel) を 1投稿で送信
- 実績ゼロ(取得失敗)時はテキストでフォールバック通知
- --as-of YYYY-MM-DD で過去日(当月)の再送が可能
- mid/end レポートは従来通り webhook テキスト送信(monthly-report.yml 用・変更なし)

使い方:
    python3 src/alert_sender.py                      # daily 画像ダッシュボード
    python3 src/alert_sender.py --force              # 冪等性チェックを無視して強制送信
    python3 src/alert_sender.py --as-of 2026-06-03   # 指定日(当月)基準で再送
    python3 src/alert_sender.py --dry                # ドライラン(送信せず内容表示)
    python3 src/alert_sender.py --report mid         # 月中報告(15日時点・webhookテキスト)
    python3 src/alert_sender.py --report end         # 月末報告(webhookテキスト)
"""

import os
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    STORES, SPREADSHEET_ID, get_gspread_client,
    slack_webhook_send, slack_bot_token, slack_post_message,
)
from store_summary_reader import get_all_stores_summary

# 「ラピラティス実績全部」スプシ(口コミシートあり)
DASHBOARD_SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"

STORE_ORDER = ["S001", "S002", "S003", "S004", "S005"]


def safe_int(v):
    try:
        return int(str(v).replace(",", "").strip()) if v else 0
    except (ValueError, TypeError):
        return 0


def get_reviews_from_kuchikomi(gc):
    """「ラピラティス実績全部」スプシの「口コミ」シートから最新月の口コミを取得
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
    try:
        latest_col = header.index("前月比") - 1
    except ValueError:
        latest_col = len(header) - 1

    google_rows = {"S001": 1, "S002": 2, "S003": 3, "S004": 4, "S005": 5}  # 0-indexed
    hpb_rows    = {"S001": 6, "S002": 7, "S003": 8, "S004": 9, "S005": 10}

    result = {}
    for sid in STORE_ORDER:
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
    """label: 「5月3日時点の実績」など、見出し用ラベル
    店舗順序: 川越 → 大宮 → 高崎 → 神戸元町 → 西宮北口(固定)
    ※ mid/end レポート(webhookテキスト)用。daily は画像ダッシュボードに移行。
    """
    statuses = {sid: contract_status(d["contract_rate"]) for sid, d in data.items()}

    lines = []
    lines.append("<!channel>")
    lines.append(f"📊 *ラピラティス実績 {label}*")
    lines.append("")

    for sid in STORE_ORDER:
        if sid not in data:
            continue
        store = next((s for s in STORES if s["id"] == sid), None)
        if not store:
            continue
        d = data[sid]
        st = statuses.get(sid, "⚪")
        cr = d["contract_rate"] * 100

        cancel_rate = (d['cancels'] / d['members'] * 100) if d['members'] else 0
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ダッシュボード PNG 生成 + Slack 添付 (2026-06-04 追加)
#   harinature-rag-agent/src/alert_sender.py からの移植
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def resolve_report_channel() -> str:
    """実績進捗チャンネルIDを解決
    1) env SLACK_REPORT_CHANNEL_ID があればそれ
    2) なければ conversations.list で名前から自動検出 (Botがメンバーのチャンネル)
    """
    import requests
    cid = os.environ.get("SLACK_REPORT_CHANNEL_ID", "").strip()
    if cid:
        return cid
    try:
        r = requests.post("https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {slack_bot_token()}"},
            data={"types": "public_channel,private_channel",
                  "limit": 1000, "exclude_archived": "true"}, timeout=30)
        for c in r.json().get("channels", []):
            n = c.get("name", "")
            if "実績進捗" in n and "ピラティス" in n:
                print(f"  ℹ️ 実績進捗チャンネル自動検出: {c['id']} ({n})")
                return c["id"]
    except Exception as e:
        print(f"  ⚠️ チャンネル自動検出失敗: {e}")
    return ""


def _agg_to_dashboard_data(summary: dict, title: str, subtitle: str, as_of: str) -> dict:
    """alert_sender の集計(summary)を dashboard_render.py 形式に変換
    summary[sid] = {contract_rate, contracts, newcomers, members, cancels,
                    referrals, reviews:{google, hpb}}
    契約率の色分けは contracts/newcomers ベース(build_message と同じ分子分母)
    """
    name_by_id = {s["id"]: s["name"] for s in STORES}
    stores = []
    tot = {"cnum": 0, "cden": 0, "members": 0, "newcomers": 0,
           "cancels": 0, "referrals": 0, "google": 0, "hpb": 0}
    for sid in STORE_ORDER:
        if sid not in summary:
            continue
        d = summary[sid]
        rv = d.get("reviews", {"google": 0, "hpb": 0})
        contracts = d.get("contracts", 0)
        newcomers = d.get("newcomers", 0)
        members = d.get("members", 0)
        cancels = d.get("cancels", 0)
        referrals = d.get("referrals", 0)
        google = rv.get("google", 0)
        hpb = rv.get("hpb", 0)
        stores.append({
            "name": name_by_id.get(sid, d.get("name", sid)),
            "contract": {"num": contracts, "den": newcomers},
            "members": members,
            "newcomers": newcomers,
            "cancels": cancels,
            "referrals": referrals,
            "google": google,
            "hpb": hpb,
        })
        tot["cnum"] += contracts; tot["cden"] += newcomers
        tot["members"] += members; tot["newcomers"] += newcomers
        tot["cancels"] += cancels; tot["referrals"] += referrals
        tot["google"] += google; tot["hpb"] += hpb
    return {
        "title": title,
        "subtitle": subtitle,
        "as_of": as_of,
        "total": {
            "contract": {"num": tot["cnum"], "den": tot["cden"]},
            "members": tot["members"],
            "newcomers": tot["newcomers"],
            "cancels": tot["cancels"],
            "referrals": tot["referrals"],
            "google": tot["google"],
            "hpb": tot["hpb"],
        },
        "stores": stores,
    }


def _slack_upload_png(channel_id: str, png_paths, comment: str = "") -> bool:
    """Slack files.upload v2 で PNG を投稿 (複数ファイル対応 = 1投稿に複数添付)
    channel_id: チャンネルID(C...)。png_paths: Path 単体 または Path のリスト
    """
    import requests
    if isinstance(png_paths, (str, Path)):
        png_paths = [Path(png_paths)]
    titles = ["当月累計の実績", "実績ダッシュボード"]
    try:
        files_meta = []
        for i, pp in enumerate(png_paths):
            pp = Path(pp)
            size = pp.stat().st_size
            # Step 1: 署名付きアップロードURL取得
            r = requests.post("https://slack.com/api/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {slack_bot_token()}"},
                data={"filename": pp.name, "length": size}, timeout=30)
            j = r.json()
            if not j.get("ok"):
                print(f"  ⚠️ getUploadURL失敗: {j.get('error')}")
                return False
            upload_url, file_id = j["upload_url"], j["file_id"]
            # Step 2: PNG本体アップロード
            with open(pp, "rb") as f:
                r2 = requests.post(upload_url, data=f.read(), timeout=60)
            if r2.status_code != 200:
                print(f"  ⚠️ PNGアップロード失敗: HTTP {r2.status_code}")
                return False
            files_meta.append({"id": file_id, "title": titles[min(i, len(titles)-1)]})
        # Step 3: 全ファイルを1投稿としてチャンネルに投稿
        body = {"files": files_meta, "channel_id": channel_id}
        if comment:
            body["initial_comment"] = comment
        r3 = requests.post("https://slack.com/api/files.completeUploadExternal",
            headers={"Authorization": f"Bearer {slack_bot_token()}",
                     "Content-Type": "application/json; charset=utf-8"},
            json=body, timeout=30)
        if r3.json().get("ok"):
            return True
        print(f"  ⚠️ complete失敗: {r3.json().get('error')}")
        return False
    except Exception as e:
        print(f"  ⚠️ PNG送信例外: {e}")
        return False


def _send_dashboard(data: dict, channel_id: str, comment: str, empty_note: str) -> bool:
    """ダッシュボードPNG(当月累計1枚)を生成して 1投稿で送信
    実績ある店舗が無ければ empty_note をテキスト投稿
    """
    try:
        from dashboard_render import render_to_png
    except ImportError as e:
        print(f"  ⚠️ dashboard_render import失敗(PNG送信スキップ): {e}")
        return False
    if not data["stores"]:
        res = slack_post_message(channel_id, empty_note)
        print("  ℹ️ 実績なし → テキスト通知" if res.get("ok") else f"  ❌ テキスト通知失敗: {res.get('error')}")
        return res.get("ok", False)
    now = datetime.now()
    out_path = Path(f"/tmp/pilates_dashboard_{now.strftime('%Y%m%d_%H%M%S_%f')}.png")
    try:
        render_to_png(data, out_path)
    except Exception as e:
        print(f"  ⚠️ PNG生成失敗: {e}")
        return False
    ok = _slack_upload_png(channel_id, out_path, comment)
    print("  🖼️ ダッシュボードPNG 送信成功" if ok else "  ❌ ダッシュボードPNG 送信失敗")
    try:
        out_path.unlink()
    except Exception:
        pass
    return ok


def already_sent_today(channel_id: str) -> bool:
    """本日のbot自身投稿が実績進捗チャンネルにあるか確認(冪等性チェック)
    GitHub Actions cron 多重化対応。--force で強制再送可。
    本日付け marker「(N日時点)」 or 「YYYY/MM/DD」を含む投稿があれば送信済みと判定。
    """
    if "--force" in sys.argv:
        return False
    if not channel_id:
        print("  ⚠️ チャンネルID未解決で冪等性チェックskip", flush=True)
        return False
    try:
        bot_token = slack_bot_token()
    except Exception as e:
        print(f"  ⚠️ Slack token取得失敗で冪等性チェックskip: {e}", flush=True)
        return False
    if not bot_token:
        return False
    try:
        import requests
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)
        # UTC/JST のズレを過去24h oldest で吸収
        oldest = min(today_start.timestamp(), now.timestamp() - 22 * 3600)
        r = requests.get("https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {bot_token}"},
            params={"channel": channel_id, "limit": 50, "oldest": oldest}, timeout=15)
        d = r.json()
        day_marker = f"({now.day}日時点)"     # 例: "(3日時点)"
        date_iso = now.strftime("%Y/%m/%d")
        for m in d.get("messages", []):
            text = m.get("text", "")
            if "GitHub Actions 失敗" in text or "未完了アラート" in text:
                continue
            if day_marker in text or date_iso in text:
                return True
        return False
    except Exception as e:
        print(f"  ⚠️ 冪等性チェック失敗(続行): {e}")
        return False


def make_label(report_type: str, ref: datetime = None) -> str:
    """見出しラベル生成
    daily → 「5月3日時点の実績」(基準日の月日)
    mid   → 「5月15日時点の実績」(=その月の15日)
    end   → 「5月末時点の実績」(=月末確定)
    """
    now = ref or datetime.now()
    if report_type == "mid":
        return f"{now.month}月15日時点の実績"
    elif report_type == "end":
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

    # --as-of YYYY-MM-DD: 基準日を任意指定 (過去日の再送用)。未指定なら今日
    as_of_override = None
    if "--as-of" in sys.argv:
        idx = sys.argv.index("--as-of")
        if idx + 1 < len(sys.argv):
            try:
                as_of_override = datetime.strptime(sys.argv[idx + 1], "%Y-%m-%d")
            except ValueError:
                print("  ⚠️ --as-of 日付パース失敗、今日を使用")

    ref = as_of_override if as_of_override else datetime.now()

    # 取得対象月の決定
    now = datetime.now()
    if report_type == "end" and now.day == 1 and not as_of_override:
        # 月初に走る月末レポート → 前月の値を取得
        target_year, target_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    elif as_of_override:
        target_year, target_month = as_of_override.year, as_of_override.month
    else:
        target_year, target_month = now.year, now.month

    # 冪等性: daily かつ本日送信済みなら skip (--force で強制再送)
    report_channel = ""
    if report_type == "daily":
        report_channel = resolve_report_channel()
        if not as_of_override and already_sent_today(report_channel):
            print("✓ 本日既にSlack送信済 → skip (--force で強制再送)")
            return 0

    print(f"📊 {report_type}レポート生成中 ({target_year}-{target_month:02d})...")

    # 先に口コミシート(軽量・1 read)を取得 → quota確保
    reviews = {}
    try:
        gc = get_gspread_client()
        reviews = get_reviews_from_kuchikomi(gc)
        print("  ✅ 口コミシート 取得完了")
    except Exception as e:
        print(f"  ⚠️ 口コミ取得失敗: {e}")

    # 集計表から取得(契約率/会員数/新規/解約/紹介)
    summary = get_all_stores_summary(target_year, target_month)
    if not summary:
        print("❌ 集計表取得失敗")
        return 1
    print(f"  ✅ 取得店舗: {len(summary)}")

    for sid in summary:
        summary[sid]['reviews'] = reviews.get(sid, {'google': 0, 'hpb': 0})

    # ── daily: 画像ダッシュボード ─────────────────────────────
    if report_type == "daily":
        weekday_j = ["月", "火", "水", "木", "金", "土", "日"][ref.weekday()]
        subtitle = f"新規実績　{ref.month}月の集計({ref.day}日時点)"
        as_of_label = f"{ref.month}/{ref.day} 時点"
        data = _agg_to_dashboard_data(summary, "La pilates", subtitle, as_of_label)

        mention = "" if "--silent" in sys.argv else "<!channel>\n"
        head = (f"{mention}:cherry_blossom: *ラピラティス新規実績　"
                f"{ref.month}/{ref.day}({weekday_j})* :cherry_blossom:\n"
                f"当月累計({ref.day}日時点)")
        empty_note = (f"{mention}:cherry_blossom: *ラピラティス新規実績　"
                      f"{ref.month}/{ref.day}({weekday_j})* :cherry_blossom:\n"
                      f"まだ実績はありません({ref.day}日時点)")

        if "--dry" in sys.argv:
            print("\n" + "=" * 60)
            print(head)
            print(f"[stores={len(data['stores'])}] total={data['total']}")
            print("=" * 60)
            return 0

        if "--no-slack" in sys.argv:
            print("📵 チャンネル送信スキップ(--no-slack)")
            return 0

        if not report_channel:
            print("❌ 実績進捗チャンネルID未解決。Botが実績進捗チャンネルに招待されているか、"
                  "env SLACK_REPORT_CHANNEL_ID を確認してください。")
            return 1

        ok = _send_dashboard(data, report_channel, head, empty_note)
        return 0 if ok else 1

    # ── mid/end: 従来通り webhook テキスト ───────────────────
    label = make_label(report_type, ref)
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
