"""streamlit_app.py - ピラティスFBシステム(La pilates ブランドデザイン)

Streamlit Cloud のエントリポイント。
カウンセリング録音をアップロード → 文字起こし → AI評価 → 育成FB生成。
"""

import streamlit as st
from datetime import date
from pathlib import Path


# ── ページ設定 ─────────────────────────────────────
st.set_page_config(
    page_title="FB SYSTEM | KOSHIKI × La pilates",
    page_icon="🤍",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ── La pilates ブランドCSS ──────────────────────────
# カラーパレット:
#   ブラウン      #8B6F47
#   ダークブラウン #5C4A36
#   ゴールド      #C9A961
#   ベージュ      #F5EFE5
#   アイボリー    #FBF8F2
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Noto+Serif+JP:wght@300;400;500;700&family=Noto+Sans+JP:wght@300;400;500;700&display=swap');

    /* Streamlitヘッダー非表示 */
    [data-testid="stHeader"] { background: transparent; height: 0; }
    [data-testid="stToolbar"] { display: none; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* 全体背景: アイボリー */
    .stApp {
        background: linear-gradient(180deg, #FBF8F2 0%, #F5EFE5 100%);
        font-family: 'Noto Sans JP', sans-serif;
    }

    /* メインコンテナ */
    .main .block-container {
        max-width: 760px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    /* ロゴ星 */
    .logo-star {
        text-align: center;
        font-family: serif;
        font-size: 3rem;
        background: linear-gradient(135deg, #C9A961 0%, #8B6F47 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1;
        margin-bottom: 0.5rem;
    }

    /* ブランドロゴ */
    .brand-logo {
        text-align: center;
        font-family: 'Cormorant Garamond', serif;
        font-size: 2.75rem;
        font-weight: 500;
        background: linear-gradient(90deg, #8B6F47 0%, #C9A961 50%, #8B6F47 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: 0.04em;
        line-height: 1.15;
        margin: 0;
    }
    .brand-logo .multiply {
        font-size: 1.5rem;
        vertical-align: middle;
        margin: 0 0.4rem;
        opacity: 0.85;
    }
    .brand-tagline {
        text-align: center;
        font-family: 'Noto Serif JP', serif;
        color: #8B6F47;
        font-size: 0.95rem;
        letter-spacing: 0.5em;
        font-weight: 300;
        margin-top: 0.75rem;
    }

    /* ロゴ区切り線 */
    .brand-divider {
        width: 60px;
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, #C9A961 50%, transparent 100%);
        margin: 1.5rem auto 2.5rem auto;
    }

    /* タイトル(ブランドロゴと統一: Cormorant Garamond + ゴールドグラデ) */
    .app-title {
        text-align: center;
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.85rem;
        font-weight: 500;
        background: linear-gradient(90deg, #8B6F47 0%, #C9A961 50%, #8B6F47 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: 0.25em;
        line-height: 1.2;
        margin: 0 0 0.5rem 0;
    }
    .app-subtitle {
        text-align: center;
        font-family: 'Noto Serif JP', serif;
        color: #8B6F47;
        font-size: 0.85rem;
        margin-bottom: 2.5rem;
        font-weight: 300;
        letter-spacing: 0.08em;
    }

    /* セクション見出し */
    .section-title {
        font-family: 'Noto Serif JP', serif;
        font-size: 0.95rem;
        font-weight: 500;
        color: #5C4A36;
        margin: 1.5rem 0 0.75rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid rgba(201, 169, 97, 0.25);
        letter-spacing: 0.08em;
    }

    /* フォームカード */
    div[data-testid="stForm"] {
        background: #FBFAF6;
        padding: 2.5rem !important;
        border-radius: 4px;
        box-shadow: 0 4px 24px rgba(139, 111, 71, 0.08);
        border: 1px solid rgba(201, 169, 97, 0.15);
    }

    /* プライマリボタン */
    .stButton button[kind="primary"],
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #8B6F47 0%, #5C4A36 100%) !important;
        color: #FBF8F2 !important;
        border: none !important;
        padding: 0.9rem 2rem !important;
        border-radius: 2px !important;
        font-weight: 500 !important;
        font-size: 0.95rem !important;
        font-family: 'Noto Serif JP', serif !important;
        letter-spacing: 0.15em !important;
        width: 100% !important;
        transition: all 0.3s !important;
        box-shadow: 0 4px 12px rgba(139, 111, 71, 0.2) !important;
    }
    .stButton button[kind="primary"]:hover,
    .stFormSubmitButton button:hover {
        background: linear-gradient(135deg, #5C4A36 0%, #8B6F47 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 8px 20px rgba(139, 111, 71, 0.3) !important;
    }

    /* 入力欄 */
    .stTextInput input,
    .stTextArea textarea,
    .stDateInput input {
        border-radius: 2px !important;
        border: 1px solid rgba(139, 111, 71, 0.2) !important;
        padding: 0.75rem 0.9rem !important;
        transition: all 0.2s !important;
        background: #FFFFFF !important;
        font-family: 'Noto Sans JP', sans-serif !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus,
    .stDateInput input:focus {
        border-color: #C9A961 !important;
        box-shadow: 0 0 0 3px rgba(201, 169, 97, 0.15) !important;
    }
    label, .stTextInput label, .stTextArea label, .stDateInput label {
        font-family: 'Noto Serif JP', serif !important;
        font-weight: 500 !important;
        color: #5C4A36 !important;
        font-size: 0.9rem !important;
        letter-spacing: 0.05em !important;
    }

    /* ファイルアップローダー */
    [data-testid="stFileUploaderDropzone"] {
        background: linear-gradient(135deg, rgba(201,169,97,0.04) 0%, rgba(139,111,71,0.06) 100%);
        border: 1px dashed rgba(139, 111, 71, 0.3) !important;
        border-radius: 4px !important;
        transition: all 0.25s !important;
    }
    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: #C9A961 !important;
        background: rgba(201, 169, 97, 0.06);
    }

    /* メトリクス */
    [data-testid="stMetric"] {
        background: #FBFAF6;
        padding: 1.25rem 1rem;
        border-radius: 4px;
        box-shadow: 0 2px 8px rgba(139, 111, 71, 0.06);
        border: 1px solid rgba(201, 169, 97, 0.15);
        text-align: center;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Noto Serif JP', serif;
        font-size: 0.8rem;
        color: #8B6F47;
        font-weight: 400;
        letter-spacing: 0.1em;
    }
    [data-testid="stMetricValue"] {
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.75rem;
        color: #8B6F47;
        font-weight: 600;
    }

    /* 結果カード */
    .result-card {
        background: #FBFAF6;
        padding: 1.5rem 1.75rem;
        border-radius: 4px;
        margin: 0.75rem 0;
        box-shadow: 0 2px 12px rgba(139, 111, 71, 0.06);
        border-left: 3px solid #C9A961;
        font-family: 'Noto Sans JP', sans-serif;
        color: #5C4A36;
        line-height: 1.8;
    }
    .result-card.good { border-left-color: #C9A961; }
    .result-card.warn { border-left-color: #B89968; }
    .result-card.line { border-left-color: #8B6F47; }

    /* code(LINE文面) */
    code, pre {
        font-family: 'Noto Sans JP', sans-serif !important;
        background: #FBFAF6 !important;
        color: #5C4A36 !important;
        border: 1px solid rgba(201, 169, 97, 0.2) !important;
        border-radius: 4px !important;
    }

    /* divider */
    hr {
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent 0%, rgba(201,169,97,0.4) 50%, transparent 100%) !important;
        margin: 2rem 0 !important;
    }

    /* ログイン画面 */
    .login-wrapper {
        max-width: 420px;
        margin: 5rem auto 0 auto;
        text-align: center;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ── ロゴ表示 ──────────────────────────────────────
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


def render_brand_header():
    """La pilates ブランドヘッダー
    ロゴ画像が assets/logo.png にあればそれを表示、なければ CSS版を表示
    """
    if LOGO_PATH.exists():
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            st.image(str(LOGO_PATH), use_container_width=True)
    else:
        # ロゴ画像が無い場合は CSSでブランドロゴを描画
        st.markdown("""
        <h1 class="brand-logo">KOSHIKI <span class="multiply">×</span> La pilates</h1>
        <p class="brand-tagline">整体 × マシンピラティス</p>
        """, unsafe_allow_html=True)

    st.markdown('<div class="brand-divider"></div>', unsafe_allow_html=True)


# ── パスワード認証 ────────────────────────────────────

def check_password():
    """松崎さん設定のパスワードでログイン"""
    def password_entered():
        if st.session_state.get("password") == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.markdown('<div class="login-wrapper">', unsafe_allow_html=True)
    render_brand_header()
    st.markdown(
        '<p class="app-subtitle">パスワードを入力してください</p>',
        unsafe_allow_html=True,
    )
    st.text_input(
        "パスワード", type="password", on_change=password_entered,
        key="password", label_visibility="collapsed",
        placeholder="パスワード",
    )
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("パスワードが違います")
    st.markdown('</div>', unsafe_allow_html=True)
    return False


# ── メイン画面 ────────────────────────────────────────

def main():
    if not check_password():
        st.stop()

    # ブランドヘッダー
    render_brand_header()

    # タイトル
    st.markdown('<h2 class="app-title">FB SYSTEM</h2>', unsafe_allow_html=True)
    st.markdown(
        '<p class="app-subtitle">カウンセリング録音をアップロード → AIが評価+FBを自動生成</p>',
        unsafe_allow_html=True,
    )

    COURSE_OPTIONS = [
        "—",
        "サブスク 月1", "サブスク 月2", "サブスク 月3", "サブスク 月4", "サブスク 月6",
        "年払い 月1", "年払い 月2", "年払い 月3", "年払い 月4", "年払い 月6",
        "整体なし 月2", "整体なし 月3", "整体なし 月4", "整体なし 月6",
        "トライアル 2回",
    ]

    # 入会の有無 は form の外(動的にコース有効/無効を切り替えるため)
    st.markdown('<div class="section-title">SESSION INFORMATION</div>', unsafe_allow_html=True)

    STORE_OPTIONS = ["川越", "大宮", "高崎", "神戸元町", "西宮北口", "所沢", "浦和"]

    col1, col2 = st.columns(2)
    with col1:
        store = st.selectbox("店舗", STORE_OPTIONS, index=0, key="store_select")
    with col2:
        staff_name = st.text_input("スタッフ名", placeholder="例: MIRAI", key="staff_name_input")
    session_date = st.date_input("セッション日", value=date.today(), key="session_date_input")

    st.markdown('<div class="section-title">CONTRACT RESULT</div>', unsafe_allow_html=True)
    col3, col4 = st.columns(2)
    with col3:
        contract = st.selectbox(
            "入会の有無",
            ["なし", "あり"],
            index=0,
            help="契約成立の有無を選んでね",
            key="contract_select",
        )
    with col4:
        is_no_contract = (contract == "なし")
        course = st.selectbox(
            "コース(入会ありの場合のみ)",
            COURSE_OPTIONS,
            index=0,
            disabled=is_no_contract,
            help="入会ありの場合に選択",
            key="course_select",
        )
    # 「なし」を選んだら course を強制的に "—"
    if is_no_contract:
        course = "—"

    # 録音 + お客様情報 + 送信は form 内
    with st.form("upload_form"):
        st.markdown('<div class="section-title">CUSTOMER INFORMATION</div>', unsafe_allow_html=True)
        col_a, col_b = st.columns(2)
        with col_a:
            age = st.selectbox(
                "年齢",
                ["—", "10代", "20代", "30代", "40代", "50代", "60代", "70代以上"],
                index=0,
            )
        with col_b:
            job = st.text_input("仕事内容", placeholder="例: 看護師(夜勤あり)")

        concerns = st.text_area(
            "悩み",
            placeholder="例: 首肩腰の痛み、3人目出産後の体型変化",
            height=80,
        )
        history = st.text_input("既往歴", placeholder="例: なし / ヘルニア / 帝王切開 等")

        st.markdown('<div class="section-title">AUDIO FILE</div>', unsafe_allow_html=True)
        audio_file = st.file_uploader(
            "録音ファイル",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            label_visibility="collapsed",
            help="新規カウンセリング・体験レッスン・クロージングの録音",
        )

        st.markdown('<div class="section-title">QUESTIONS (OPTIONAL)</div>', unsafe_allow_html=True)
        questions = st.text_area(
            "疑問点(リーダー/研修担当に聞きたいこと)",
            placeholder="例: 産後ママへのクロージングがうまくできない / トライアル後の提案タイミングは?",
            height=80,
            help="任意。リーダーや研修担当に相談したいことがあれば記入してね",
        )

        submitted = st.form_submit_button("GENERATE FB", type="primary")

    if submitted:
        # 必須チェック
        errors = []
        if not staff_name:
            errors.append("スタッフ名")
        if age == "—":
            errors.append("年齢")
        if not job.strip():
            errors.append("仕事内容")
        if not concerns.strip():
            errors.append("悩み")
        if not history.strip():
            errors.append("既往歴")
        if not audio_file:
            errors.append("録音ファイル")
        if errors:
            st.error(f"⚠️ 未入力: {', '.join(errors)} を入力してね💦")
            return

        # 処理
        customer_info = {
            "age": age,
            "job": job.strip(),
            "concerns": concerns.strip(),
            "history": history.strip(),
        }
        from coaching.coaching_analyzer import analyze_session
        with st.spinner("文字起こし + AI評価中...  1〜2分かかります"):
            try:
                result = analyze_session(
                    audio_file, staff_name, session_date,
                    customer_info=customer_info,
                    contract=contract, course=course, store=store,
                    questions=questions.strip(),
                )
            except Exception as e:
                st.error(f"処理失敗💦 {e}")
                return

        st.success("フィードバック生成完了")

        # 振り返り要約
        st.markdown('<div class="section-title">SESSION SUMMARY</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card line">{result.get("session_summary", "(要約なし)")}</div>', unsafe_allow_html=True)

        # スコア
        st.markdown('<div class="section-title">EVALUATION</div>', unsafe_allow_html=True)
        scores = result.get("scores", {})
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a: st.metric("HEARING",  f"{scores.get('hearing', 0)} / 5")
        with col_b: st.metric("PROPOSAL", f"{scores.get('proposal', 0)} / 5")
        with col_c: st.metric("CLOSING",  f"{scores.get('closing', 0)} / 5")
        with col_d: st.metric("TONE",     f"{scores.get('tone', 0)} / 5")

        # 良かったポイント
        st.markdown('<div class="section-title">STRENGTHS</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card good">{result.get("good_points", "(なし)")}</div>', unsafe_allow_html=True)

        # 改善点
        st.markdown('<div class="section-title">IMPROVEMENTS</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card warn">{result.get("improvements", "(なし)")}</div>', unsafe_allow_html=True)

        # 疑問点(任意入力があれば表示)
        if questions.strip():
            st.markdown('<div class="section-title">QUESTIONS FOR LEADER</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="result-card line">{questions.strip()}</div>', unsafe_allow_html=True)

        st.divider()
        st.caption("Slack に 振り返り内容 + 評価 + FB + 疑問点 が自動投稿されました")


if __name__ == "__main__":
    main()
