"""feedback_builder.py

新規振り返り投稿に対する「具体的なフィードバック」をテンプレ+条件分岐で生成。

【方針】
- 技術系(ピラティス/整体)のFBは入れない(研修担当がFB)
- カウンセリング・クロージングにフォーカス
- お客様タイプ(検討の壁) + 属性タグ(主婦/産後/etc) で文章を組み合わせる

【第1段階 実装範囲 (2026-05-14)】
- お客様タイプ: 他店比較タイプ / 持ち帰りタイプ / 契約済タイプ / その他(汎用)
- 属性タグ: 主婦 / 産後 / デスクワーカー / 立ち仕事 / 慢性的悩み
- 第2段階以降で他のタイプ/タグ拡張予定
"""

import re


# ── 抽出関数 ───────────────────────────────────────────

def _clean(s):
    """先頭末尾の不要な記号(コロン全角/半角・スペース)を削除"""
    if not s: return ""
    return s.strip().lstrip(":：　 ").rstrip(":：　 ").strip()


def get_first_customer_block(text):
    """1投稿に複数客の振り返りが含まれる場合、最初の客だけを取り出す
    「年齢:」が2回以上出現したら、2人目の「年齢:」より前で切る
    """
    matches = list(re.finditer(r"年齢[\s:：]", text))
    if len(matches) <= 1:
        return text
    return text[: matches[1].start()]


def extract_staff_name(text):
    """振り返り先頭からスタッフ名を抽出
    - 「お疲れ様」「お手隙」「FB」等の挨拶行をスキップ
    - 日付行・項目ラベル行をスキップ
    - 短い名前候補行(英大文字 or カタカナ)を返す
    """
    SKIP_KEYWORDS = ["お疲れ", "お手隙", "FB", "fb", "よろしく", "ありがとう", "確認", "今回"]
    LABEL_KEYWORDS = ["年齢", "仕事", "悩み", "既往歴", "契約", "検討理由", "理想", "提案"]
    for line in text.split("\n")[:6]:
        line = line.strip()
        if not line:
            continue
        # 挨拶行
        if any(kw in line for kw in SKIP_KEYWORDS):
            continue
        # 日付行 (5/7 / 5月7日)
        if re.fullmatch(r"\d+\s*[/\-月]\s*\d+\s*[日]?", line):
            continue
        # 項目ラベル行
        if any(label in line for label in LABEL_KEYWORDS):
            continue
        # 短い名前候補
        if 1 <= len(line) <= 15:
            return line
    return None


def extract_age(text):
    m = re.search(r"年齢[\s:：]*(\d+)", text)
    return m.group(1) if m else None


def extract_job(text):
    m = re.search(r"仕事[\s:：]*([^\n]+)", text)
    if m:
        return _clean(m.group(1))[:30]
    return None


def extract_concerns(text):
    m = re.search(r"悩み[\s:：]*([^\n]+)", text)
    if m:
        return _clean(m.group(1))[:80]
    return None


def extract_self_good(text):
    """「今回の良かったこと」セクションを抽出"""
    m = re.search(r"今回の良かったこと[\s:：]*\n*([\s\S]+?)(?=\n\n|\n[^・\s]|$)", text)
    if m:
        return _clean(m.group(1))[:300]
    return None


def extract_postpartum_years(text):
    """産後何年経過したかを抽出"""
    patterns = [
        r"出産[^\n]{0,30}?(\d+)\s*年前",   # 「3人目出産10年前」
        r"産後\s*(\d+)\s*年",
        r"出産後\s*(\d+)\s*年",
        r"出産から\s*(\d+)\s*年",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return int(m.group(1))
    return None


def detect_interest_signals(text):
    """お客様からの能動的アクション=関心度高めシグナルを検出"""
    signals = []
    # LINE等での追加情報リクエスト
    if any(kw in text for kw in ["LINE", "ライン"]) and any(kw in text for kw in ["送って", "送っていただけ", "送付", "教えて"]):
        signals.append("お客様から能動的に追加情報のリクエスト(LINEで送ってほしい等)")
    # 再説明要求
    if any(kw in text for kw in ["もう一度", "再度", "もう一回"]) and any(kw in text for kw in ["説明", "教えて", "送って"]):
        signals.append("再説明・再案内のリクエスト")
    # 次回への言及
    if any(kw in text for kw in ["次回はいつ", "次の予約", "次は"]):
        signals.append("お客様から次回への言及")
    # 連絡先交換系
    if any(kw in text for kw in ["連絡先", "LINE交換", "またご連絡"]):
        signals.append("連絡継続を希望するシグナル")
    return signals


def extract_contract(text):
    """契約状況: あり / なし / 不明
    「契約の有無(コース):なし」(全角・半角括弧両対応)
    行ベースで走査(正規表現の \\s が改行を含むのを回避)
    """
    for line in text.split("\n"):
        if "契約の有無" in line:
            m = re.search(r"[:：][ \t]*(.+)$", line)
            if m:
                v = _clean(m.group(1))
                if not v: return "不明"
                if "なし" in v or "無" in v or "ない" in v:
                    return "なし"
                return "あり"
    return "不明"


# ── お客様タイプ分類(検討の壁) ────────────────────────

def classify_barrier(text):
    """検討の壁を分類。優先順位順にチェック"""
    # 検討理由セクションを優先的に見る
    m = re.search(r"検討理由[\s:：]*([^\n]+)", text)
    reason = m.group(1) if m else ""
    full = text + " " + reason

    # 他店比較
    if any(kw in full for kw in ["他店", "他の店舗", "比較したい", "比較する", "見比べ"]):
        return "other_store_compare"
    # 持ち帰り検討
    if any(kw in full for kw in ["家で考え", "家族と相談", "持ち帰", "検討します", "考えます"]):
        return "take_home"
    # 価格懸念
    if any(kw in full for kw in ["高い", "予算", "料金が", "費用", "お金"]):
        return "price_concern"
    # 時間懸念
    if any(kw in full for kw in ["忙しい", "通えるか", "時間が", "曜日"]):
        return "time_concern"
    # 体験のみ
    if any(kw in full for kw in ["とりあえず", "お試し", "体験だけ", "気軽に"]):
        return "trial_only"
    return "generic"


def classify_contract_result(text):
    """契約あり = success, なし = lost, 不明 = unknown"""
    c = extract_contract(text)
    if c == "あり":
        return "contract_success"
    if c == "なし":
        return "contract_lost"
    return "unknown"


# ── 属性タグ抽出 ─────────────────────────────────────

def extract_tags(text):
    tags = []
    job = (extract_job(text) or "").lower() + " " + text

    if any(kw in text for kw in ["主婦", "お子さん", "育児", "子育て", "ママ"]):
        tags.append("housewife")
    if any(kw in text for kw in ["産後", "出産", "妊娠", "授乳"]):
        tags.append("postpartum")
    if any(kw in text for kw in ["デスクワーク", "PC作業", "座り仕事", "事務", "デスク"]):
        tags.append("desk_work")
    if any(kw in text for kw in ["立ち仕事", "販売", "美容師", "看護師", "介護"]):
        tags.append("standing_work")
    if any(kw in text for kw in ["ずっと", "長年", "慢性", "何年も", "前から"]):
        tags.append("chronic")
    return tags


# ── テンプレ ──────────────────────────────────────────

BARRIER_LABELS = {
    "other_store_compare": "他店比較タイプ",
    "take_home": "持ち帰り検討タイプ",
    "price_concern": "価格懸念タイプ",
    "time_concern": "時間懸念タイプ",
    "trial_only": "体験のみタイプ",
    "generic": "総合",
}

TAG_LABELS = {
    "housewife": "主婦/育児中",
    "postpartum": "産後",
    "desk_work": "デスクワーカー",
    "standing_work": "立ち仕事",
    "chronic": "慢性的悩み",
}


# 深掘り質問テンプレ(属性タグ別)
DEEP_QUESTIONS_BY_TAG = {
    "housewife": [
        "通える曜日・時間帯は?(送り迎えの隙間?夫の休日?)",
        "ご家族の理解は得られそうですか?(時間・予算の確認)",
    ],
    "postpartum": [
        "「産後にしんどくなった」→ どんな自分になりたい?(体型?体力?自分時間?)",
        "「いつから一番悪化した?」(出産直後 / 数年後 / 最近?)",
    ],
    "desk_work": [
        "1日どれくらい座っていますか?(連続時間が長いほど提案の刺さりが変わる)",
        "作業環境は?(自宅PC/オフィス/カフェなど)",
        "休憩や立ち上がる頻度は?",
    ],
    "standing_work": [
        "連続して立つ時間は?(休憩タイミングの確認)",
        "足のむくみ・疲労感のピークはいつ?(終業時/翌朝)",
        "休日の過ごし方(動く派/休む派)で提案を変える",
    ],
    "chronic": [
        "「いつから?」「これまで何か対処されてきましたか?」(整体・整骨院・他のジム経験)",
        "今までで効果を感じた施術はありましたか?(成功体験を引き出す)",
        "「今回こそ変えたい」気持ちの強さはどのくらい?(モチベ確認)",
    ],
}


# 良かった点の汎用フレーズ(振り返りから読み取れない場合のフォールバック)
GOOD_POINTS_GENERIC = "ヒアリングと提案の流れがしっかりまとめられていて◎です✨"


# クロージング戦略テンプレ(検討の壁別)
CLOSING_STRATEGIES = {
    "contract_success": {
        "intro": "契約獲得お疲れ様です🎉 ここからは「定着サポート」のフェーズに切り替え:",
        "items": [
            "①初回体験の感動を冷めさせない\n  「今日感じた変化、来週も体感できますよ」と次回への期待を伝える",
            "②目標を一緒に設定する\n  「3ヶ月後・半年後にこうなりたい、を一緒に決めましょう」(契約直後のモチベが一番高い)",
            "③次回予約をその場で確定\n  「来週の同じ時間でお取りしますね」(=固定化で習慣化)",
            "④中間カウンセリングの予告\n  「3ヶ月後に進捗チェックしましょう」(=モチベ維持・解約予防の最重要施策)",
        ],
    },
    "other_store_compare": {
        "intro": "「比較したい」と言われた時点で すでに持ち帰りモード💦\nLINEで送る = 検討期間ができる = 他店と並べられる = 入会率が下がる\n\nその場で決め切るためのアプローチ案:",
        "items": [
            "①比較ポイントを具体化\n  「どんな点を比較されますか?(料金?メニュー?雰囲気?)」\n   → 漠然比較を解消",
            "②違いを\"記憶に残す\"形で見せる\n  「先ほど整体で◯◯がほぐれましたよね、これ他店だとオプション月+◯◯円です」\n   → 数字付きの体感が記憶に残る",
            "③期限と特典で背中を押す\n  「今日の体験価格は本日中のお申込みで適用、月跨ぐと通常価格に戻ります」\n   → 決断のタイムリミットを作る",
            "④仮押さえだけお願いする\n  「次回予約だけ仮で押さえます。比較してやっぱり違うなと思えばキャンセルOK」\n   → ハードル下げて「もう通うことになってる」心理状態を作る",
        ],
    },
    "take_home": {
        "intro": "「家で考えたい」=持ち帰り検討モード💦\n決定権者の確認とリミット設定がカギ:",
        "items": [
            "①決定権者の確認\n  「ご家族とのご相談ですか?(誰の同意があれば決められる?)」",
            "②期限を区切る\n  「◯日までにお返事いただけたら、今日の体験価格適用です」",
            "③LINE後追いの準備\n  特徴・料金・効果のまとめをLINEで送付 → 翌日リマインド連絡",
        ],
    },
    "price_concern": {
        "intro": "価格懸念がベース → コスパ可視化と支払い柔軟性の提示:",
        "items": [
            "①1回あたり換算\n  「月◯回で◯円÷◯回 = 1回◯円。マッサージ1回より安い計算です」",
            "②優先順位の整理\n  「健康投資は何より優先順位高くないですか?この体が一生使う資本ですから」",
            "③支払い柔軟性\n  「分割払いや年払い割引もあるので、無理なく続けられます」",
        ],
    },
    "time_concern": {
        "intro": "通えるか不安がベース → 続けやすさを具体的に提示:",
        "items": [
            "①通いやすい曜日時間を一緒に確認\n  「平日昼?週末?どの時間が一番継続しやすそうですか?」",
            "②最低頻度の提案\n  「月◯回からでも十分効果出ます。続けるハードル下げましょう」",
            "③予約変更の柔軟性\n  「直前変更も◯時間前までOKなので、続けやすいですよ」",
        ],
    },
    "trial_only": {
        "intro": "「とりあえず体験」モード → その場で次のステップを聞き出す:",
        "items": [
            "①体験変化の振り返り\n  「先ほどの整体・ピラティスで一番変化を感じたのはどこですか?」",
            "②理想とのギャップを引き出す\n  「この変化を続けたらどうなりたいですか?」",
            "③次回をその場で打診\n  「今の感覚を忘れないうちに、次回いつ来られそうですか?」",
        ],
    },
    "generic": {
        "intro": "クロージング部分の振り返り:",
        "items": [
            "お客様の「決断の障壁」が何かを明確にできると、次回からの提案精度が上がります",
            "「今日決めて行ってもらう」より「次回の予約をその場で取る」の方が成功率高い",
        ],
    },
}


NEXT_FOCUS = {
    "contract_success": [
        "契約直後は「初回の感動」を覚えているうちに目標設定+次回固定で習慣化を作る",
        "中間カウンセリングを早めに予告(=解約予防の最重要施策)",
    ],
    "other_store_compare": [
        "他店比較タイプは「持ち帰らせない工夫」を1つは入れる",
    ],
    "take_home": [
        "持ち帰りタイプは「期限+決定権者の確認」をセットで",
    ],
    "price_concern": [
        "価格懸念タイプは「1回あたり換算」「健康投資の優先順位」を必ず伝える",
    ],
    "time_concern": [
        "時間懸念タイプは「最低頻度+予約柔軟性」で続けるハードルを下げる",
    ],
    "trial_only": [
        "体験のみタイプは「次回予約をその場で」が最重要",
    ],
    "generic": [
        "次回はお客様の「決断の障壁」を1問深掘りしてみる",
    ],
}

# 属性タグごとの+α 次回意識
NEXT_FOCUS_BY_TAG = {
    "housewife": "主婦層は家族の理解(時間・予算)ヒアリングを1問入れる",
    "postpartum": "産後ママは「経過年数で育児フェーズを判定」して質問を変える",
    "desk_work": "デスクワーカーは「1日座る時間」を具体化",
    "standing_work": "立ち仕事は「疲労ピーク時間帯」のヒアリングを入れる",
    "chronic": "慢性悩みタイプは「過去の対処履歴」を聞くと熱量UP",
}


def get_postpartum_phase_questions(years):
    """産後年数別に深掘り質問を返す"""
    if years is None:
        return [
            "産後何年目?(育児フェーズで提案が変わります)",
            "「産後にしんどくなった」→ どんな自分になりたい?(体型?体力?自分時間?)",
        ]
    if years <= 3:
        return [
            f"産後{years}年目 → 授乳期や育児負担がまだ大きいフェーズ",
            "「育児で一番疲れるシーンは?」(抱っこ?授乳?夜泣き?)",
            "ご家族の協力体制(自分時間の確保)はどう?",
        ]
    elif years <= 7:
        return [
            f"産後{years}年経過 → 育児負担が少しずつ減ってくるフェーズ",
            "「自分のために時間を使う」ことへの意識はどれくらい?",
            "理想の体型・体力像は?(妊娠前に戻したい / それ以上を目指す?)",
        ]
    else:  # 8年〜
        return [
            f"産後{years}年経過 → 育児ほぼ手離れフェーズ ✨",
            "「自分のための時間が欲しい」フェーズ = 通うモチベ高めになりやすい",
            "「どうなりたいか」の理想を引き出す(健康維持/体型/体力/メンタル)",
        ]


# ── メイン生成関数 ────────────────────────────────────

def build_detailed_feedback(reflection_text, staff_name="スタッフ"):
    """振り返りテキストから具体的なFBを生成
    - 複数客の振り返りなら最初の客だけ対象
    - 契約済なら定着サポート視点のテンプレを使う
    """
    # 1投稿に複数客が含まれる場合、最初の客だけ抽出
    text = get_first_customer_block(reflection_text)

    age = extract_age(text)
    job = extract_job(text)
    concerns = extract_concerns(text)
    barrier = classify_barrier(text)
    tags = extract_tags(text)
    contract = extract_contract(text)
    good_self = extract_self_good(text)
    postpartum_years = extract_postpartum_years(text)
    interest_signals = detect_interest_signals(text)

    # 検討の壁(barrier)と契約結果(contract)は別軸として扱う
    # 検討の壁: 他店比較/価格懸念/時間懸念 etc(契約有無に関係なくお客様が迷っていた点)
    # 契約結果: あり/なし → クロージングの視点を分岐(定着サポート vs 失注分析)

    # 状態整理ライン(重複排除)
    profile_parts = []
    if age: profile_parts.append(f"{age}歳")
    if job: profile_parts.append(job)
    # タグ表示は仕事と被らないように調整
    display_tags = []
    for t in tags:
        if t == "housewife" and job and "主婦" in job:
            continue  # 仕事=主婦 ならタグ「主婦/育児中」は省略
        if t == "postpartum":
            if postpartum_years is not None:
                display_tags.append(f"産後{postpartum_years}年経過")
            else:
                display_tags.append("産後")
            continue
        if t in TAG_LABELS:
            display_tags.append(TAG_LABELS[t])
    if display_tags:
        profile_parts.append("・".join(display_tags))
    profile = " / ".join(profile_parts) if profile_parts else "情報少なめ"

    barrier_label = BARRIER_LABELS.get(barrier, "総合")

    # 深掘り質問(タグ別を結合)
    deep_qs = []
    # 産後タグは年数別出し分け
    if "postpartum" in tags:
        deep_qs.extend(get_postpartum_phase_questions(postpartum_years))
    # 他のタグ
    for tag in tags:
        if tag == "postpartum": continue  # 上で処理済み
        if tag in DEEP_QUESTIONS_BY_TAG:
            deep_qs.extend(DEEP_QUESTIONS_BY_TAG[tag])
    # タグが取れない時は generic 質問
    if not deep_qs:
        deep_qs = [
            "「困りごとが起きるシーンを具体的に」(朝/夕方?仕事中?家事中?)",
            "「これまでどんな対処してきたか」(他施術経験)",
            "「どうなりたいか」の理想像(=モチベの源泉)",
        ]
    deep_qs_text = "\n".join([f"{chr(0x2460+i)}{q}" for i, q in enumerate(deep_qs[:5])])

    # クロージング戦略: 契約結果で視点を分岐
    # - 契約あり → 定着サポート視点(barrier 関係なく)
    # - 契約なし → 検討の壁(barrier)別の失注分析視点
    if contract == "あり":
        closing = CLOSING_STRATEGIES["contract_success"]
        closing_section_heading = "クロージング(契約獲得🎉 → 定着サポート視点)"
    else:
        closing = CLOSING_STRATEGIES.get(barrier, CLOSING_STRATEGIES["generic"])
        closing_section_heading = f"クロージング({barrier_label}への対応)"
    closing_text = closing["intro"] + "\n\n" + "\n\n".join(closing["items"])

    # 良かった点 + 関心度シグナル追記
    if good_self:
        good_summary = good_self.split("\n")[0][:100]
        good_text = f"自己評価で挙がっていた「{good_summary}…」のポイント、しっかり言語化できていて◎✨"
    else:
        good_text = GOOD_POINTS_GENERIC
    if interest_signals:
        good_text += "\n\n🔥 *関心度高めシグナル検出*"
        for sig in interest_signals:
            good_text += f"\n・{sig}"
        good_text += "\n→ お客様から能動的なアクションが出ている = 関心度はかなり高い証拠✨"

    # 次回意識: 契約結果で視点を分岐
    if contract == "あり":
        next_focus = NEXT_FOCUS["contract_success"].copy()
    else:
        next_focus = NEXT_FOCUS.get(barrier, NEXT_FOCUS["generic"]).copy()
    for tag in tags:
        if tag in NEXT_FOCUS_BY_TAG:
            next_focus.append(NEXT_FOCUS_BY_TAG[tag])
    next_focus_text = "\n".join([f"・{x}" for x in next_focus])

    # 契約結果表示
    if contract == "あり":
        contract_result = "🎉 契約獲得"
    elif contract == "なし":
        contract_result = "🥲 契約なし(失注分析視点)"
    else:
        contract_result = "不明"

    fb = f"""📝 {staff_name}さん、振り返りお疲れ様です:relaxed:

【お客様の状態整理(営業面)】
・{profile}
・主訴: {concerns or "不明"}
・検討の壁: {barrier_label}
・結果: {contract_result}


📌 カウンセリングで良かった点
{good_text}


🎯 もう一歩深掘りしたかったポイント
{deep_qs_text}


💎 {closing_section_heading}
{closing_text}


🌟 次回意識すること
{next_focus_text}
"""
    return fb


if __name__ == "__main__":
    # 千乃さん5/8振り返りで検証
    sample = """YUKINO

お疲れ様です！

今回もお手隙の際にFBお願いいたします。

5/7

年齢:43
仕事:主婦
悩み:首肩腰が辛い。お子さん3人目産んでから体がしんどくなってしまった。(3人目出産10年前)
既往歴:なし
契約の有無(コース):なし

悩みに対しての改善方法/提案内容:体がかなり硬めで、特に脊柱の可動域が狭かったので、脊柱の柔軟性アップを目標にしました。

検討理由:他の店舗と比較したい。

今回の良かったこと:他の店舗と比較したいとお話しいただいた際、当店は整体がついていたりパーソナルでひとりひとり合わせたワークをすることをしっかりお伝えしました。そのためお客様からLINEに比較する際に忘れないためにも再度当店の特徴送っていただけませんか?とお話しがありました。
"""
    print(build_detailed_feedback(sample, "千乃"))
