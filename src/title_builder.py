"""title_builder.py — Notion振り返りページの "わかりやすいタイトル" 生成

旧フォーマット: 📝 2026-05-15 10:45 松崎: ❶店舗：高崎店...
新フォーマット: 💭 フェイスラインのたるみ・ほうれい線が気になる方 | 高崎店 加藤 | 5/15 [未入会]
"""
import re
from datetime import datetime


MAX_CONCERN_LEN = 50   # 悩み部分の最大長(超えたら短縮)
MAX_TITLE_LEN = 180    # Notion title 全体最大長


def _shorten_concern(concern: str) -> str:
    """悩みテキストを短く整形(キーワード抽出+「・」連結)"""
    if not concern:
        return ""
    # 改行除去 + 正規化
    s = re.sub(r"\s+", " ", concern).strip()
    # 「、」「,」「/」 で分割
    parts = re.split(r"[、,/・\s]+", s)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return s[:MAX_CONCERN_LEN]
    # 上位3キーワードを「・」連結
    joined = "・".join(parts[:3])
    if len(joined) > MAX_CONCERN_LEN:
        joined = joined[:MAX_CONCERN_LEN] + "…"
    return joined


def make_friendly_title(
    concern: str = "",
    store: str = "",
    staff: str = "",
    date: str = "",      # "YYYY-MM-DD" or "M/D" or datetime
    result: str = "",
    fallback: str = "",  # 全部空ならこれを使う
) -> str:
    """わかりやすいタイトル生成
    優先順: 悩み > 店舗+スタッフ > 日付 > 結果

    例:
      "💭 フェイスラインのたるみ・ほうれい線が気になる方 | 高崎店 加藤 | 5/15 [未入会]"
    """
    parts = []

    # 1. 悩みヘッダ
    concern_short = _shorten_concern(concern)
    if concern_short:
        parts.append(f"💭 {concern_short}が気になる方")
    elif fallback:
        # 悩み無し→fallback(本文先頭等)
        fb = re.sub(r"\s+", " ", fallback)[:50]
        parts.append(f"📝 {fb}")
    else:
        parts.append("📝 (悩み未記入)")

    # 2. 店舗 + スタッフ
    sub_meta = []
    if store: sub_meta.append(store)
    if staff: sub_meta.append(staff)
    if sub_meta:
        parts.append(" ".join(sub_meta))

    # 3. 日付(短縮: M/D)
    date_str = ""
    if isinstance(date, datetime):
        date_str = date.strftime("%-m/%-d")
    elif isinstance(date, str) and date:
        # "2026-05-15" → "5/15", "5/15" → そのまま
        m = re.match(r"^\d{4}-(\d{1,2})-(\d{1,2})", date)
        if m:
            date_str = f"{int(m.group(1))}/{int(m.group(2))}"
        else:
            date_str = date
    if date_str:
        parts.append(date_str)

    # 4. 結果
    if result:
        parts.append(f"[{result}]")

    title = " | ".join(parts[:3]) + ((" " + parts[3]) if len(parts) >= 4 else "")
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN] + "…"
    return title


if __name__ == "__main__":
    print(make_friendly_title(
        concern="フェイスラインのたるみ、ほうれい線、噛み締め",
        store="高崎店", staff="加藤",
        date="2026-05-15", result="未入会"
    ))
    print(make_friendly_title(
        concern="むくみ・小顔",
        store="大宮店", staff="本間",
        date="5/15", result="入会"
    ))
    print(make_friendly_title(  # 悩み無し → fallback
        store="新宿店", staff="渡部",
        date="2026-05-15", result="入会",
        fallback="お話する中で家族と相談したいということで…"
    ))
