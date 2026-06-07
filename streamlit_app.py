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


# ── La pilates エンタープライズデザインCSS ──────────
# カラーシステム(ブラウン/ゴールド系):
#   Primary    #5C4A36 (ダークブラウン)
#   Brand      #8B6F47 (ブラウン)
#   Accent     #C9A961 (ゴールド)
#   Surface 0  #FFFFFF (純白)
#   Surface 1  #FBF8F2 (オフホワイト)
#   Surface 2  #F5EFE5 (微淡ベージュ)
#   Border     rgba(26,26,26,0.08)
#   Text Dark  #1A1A1A
#   Text Body  #5C4A36
#   Text Mute  #7D6A55
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&family=Noto+Serif+JP:wght@300;400;500;600;700&family=Noto+Sans+JP:wght@300;400;500;700&display=swap');

    /* CSS Variables */
    :root {
        --primary: #5C4A36;
        --brand: #8B6F47;
        --accent: #C9A961;
        --surface-0: #FFFFFF;
        --surface-1: #FBF8F2;
        --surface-2: #F5EFE5;
        --border: rgba(26,26,26,0.08);
        --border-strong: rgba(26,26,26,0.15);
        --text-dark: #1A1A1A;
        --text-body: #5C4A36;
        --text-mute: #7D6A55;
        --shadow-sm: 0 1px 2px rgba(26,26,26,0.04), 0 1px 3px rgba(26,26,26,0.03);
        --shadow-md: 0 1px 3px rgba(26,26,26,0.04), 0 4px 16px rgba(26,26,26,0.04);
        --shadow-lg: 0 4px 8px rgba(26,26,26,0.04), 0 16px 48px rgba(26,26,26,0.06);
    }

    /* Streamlit chrome を完全に非表示 */
    [data-testid="stHeader"] { background: transparent; height: 0; }
    [data-testid="stToolbar"] { display: none; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }

    /* 全体: 真っ白ベース */
    .stApp {
        background: var(--surface-1);
        font-family: 'Inter', 'Noto Sans JP', -apple-system, sans-serif;
        color: var(--text-body);
    }

    /* メインコンテナ */
    .main .block-container {
        max-width: 880px;
        padding-top: 1.5rem;
        padding-bottom: 5rem;
    }

    /* ───────────── トップナビゲーション ───────────── */
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 0 1.5rem 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 3rem;
    }
    .topbar-left {
        display: flex;
        align-items: center;
        gap: 0.85rem;
    }
    .topbar-logo {
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.4rem;
        font-weight: 500;
        color: var(--text-dark);
        letter-spacing: 0.06em;
        line-height: 1;
    }
    .topbar-logo .multiply {
        color: var(--accent);
        font-style: italic;
        margin: 0 0.45rem;
        font-weight: 300;
    }
    .topbar-divider {
        width: 1px;
        height: 18px;
        background: var(--border-strong);
    }
    .topbar-product {
        font-family: 'Inter', sans-serif;
        font-size: 0.78rem;
        font-weight: 500;
        color: var(--text-mute);
        letter-spacing: 0.18em;
        text-transform: uppercase;
    }
    .topbar-meta {
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.3rem 0.7rem;
        background: rgba(201,169,97,0.12);
        border: 1px solid rgba(201,169,97,0.35);
        border-radius: 999px;
        font-size: 0.7rem;
        font-weight: 500;
        color: var(--primary);
        letter-spacing: 0.06em;
    }
    .status-badge::before {
        content: '';
        width: 6px; height: 6px;
        background: #4CAF50;
        border-radius: 50%;
        box-shadow: 0 0 0 3px rgba(76,175,80,0.15);
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .version-tag {
        font-family: 'Inter', monospace;
        font-size: 0.7rem;
        color: var(--text-mute);
        letter-spacing: 0.04em;
    }

    /* ───────────── ヒーローセクション ───────────── */
    .hero-wrap {
        text-align: center;
        margin-bottom: 3.5rem;
        padding: 1rem 0 2rem 0;
    }
    .hero-eyebrow {
        display: inline-block;
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        font-weight: 600;
        color: var(--brand);
        letter-spacing: 0.32em;
        text-transform: uppercase;
        padding: 0.35rem 0.9rem;
        background: rgba(201,169,97,0.10);
        border-radius: 999px;
        margin-bottom: 1.5rem;
    }
    .hero-title {
        font-family: 'Cormorant Garamond', serif;
        font-size: 3rem;
        font-weight: 400;
        color: var(--text-dark);
        letter-spacing: -0.01em;
        line-height: 1.15;
        margin: 0 0 1.1rem 0;
    }
    .hero-title em {
        font-style: italic;
        font-weight: 300;
        color: var(--brand);
    }
    .hero-subtitle {
        font-family: 'Noto Sans JP', sans-serif;
        font-size: 0.95rem;
        color: var(--text-mute);
        line-height: 1.75;
        max-width: 540px;
        margin: 0 auto;
        font-weight: 400;
    }

    /* ───────────── セクションヘッダー ───────────── */
    .section-title {
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        color: var(--text-mute) !important;
        margin: 2rem 0 1rem 0 !important;
        padding: 0 !important;
        border: none !important;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .section-title::before {
        content: '';
        width: 3px;
        height: 14px;
        background: var(--brand);
        border-radius: 2px;
    }

    /* ───────────── フォームカード ───────────── */
    div[data-testid="stForm"] {
        background: var(--surface-0);
        padding: 2.5rem !important;
        border-radius: 12px;
        box-shadow: var(--shadow-md);
        border: 1px solid var(--border);
    }

    /* ───────────── ボタン ───────────── */
    .stButton button[kind="primary"],
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #8B6F47 0%, #5C4A36 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        padding: 0.95rem 2rem !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        letter-spacing: 0.12em !important;
        width: 100% !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 1px 2px rgba(92,74,54,0.15), 0 2px 8px rgba(92,74,54,0.10) !important;
        text-transform: uppercase;
        position: relative;
        overflow: hidden;
    }
    .stButton button[kind="primary"]:hover,
    .stFormSubmitButton button:hover {
        background: linear-gradient(135deg, #5C4A36 0%, #3F3324 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(92,74,54,0.25), 0 8px 24px rgba(92,74,54,0.15) !important;
    }
    .stButton button[kind="primary"]:active,
    .stFormSubmitButton button:active {
        transform: translateY(0) !important;
    }

    /* ───────────── 入力欄 ───────────── */
    .stTextInput input,
    .stTextArea textarea,
    .stDateInput input,
    .stSelectbox > div > div {
        border-radius: 8px !important;
        border: 1px solid var(--border-strong) !important;
        padding: 0.7rem 0.9rem !important;
        transition: all 0.15s ease !important;
        background: var(--surface-0) !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        font-size: 0.9rem !important;
        color: var(--text-dark) !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus,
    .stDateInput input:focus {
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 3px rgba(139,111,71,0.12) !important;
        outline: none !important;
    }
    .stSelectbox > div > div:hover {
        border-color: var(--brand) !important;
    }

    /* ラベル */
    label,
    .stTextInput label,
    .stTextArea label,
    .stDateInput label,
    .stSelectbox label,
    .stFileUploader label {
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        font-weight: 500 !important;
        color: var(--text-dark) !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.02em !important;
        margin-bottom: 0.4rem !important;
    }

    /* ───────────── ファイルアップローダー ───────────── */
    [data-testid="stFileUploaderDropzone"] {
        background: var(--surface-1);
        border: 1.5px dashed var(--border-strong) !important;
        border-radius: 10px !important;
        transition: all 0.2s ease !important;
        padding: 1.5rem !important;
    }
    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--brand) !important;
        background: rgba(201,169,97,0.04);
    }

    /* ───────────── メトリクス(KPIカード) ───────────── */
    [data-testid="stMetric"] {
        background: var(--surface-0);
        padding: 1.4rem 1.2rem;
        border-radius: 10px;
        box-shadow: var(--shadow-sm);
        border: 1px solid var(--border);
        text-align: left;
        transition: all 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        box-shadow: var(--shadow-md);
        border-color: var(--border-strong);
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.68rem !important;
        color: var(--text-mute) !important;
        font-weight: 600 !important;
        letter-spacing: 0.16em !important;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] {
        font-family: 'Cormorant Garamond', serif !important;
        font-size: 2.2rem !important;
        color: var(--text-dark) !important;
        font-weight: 500 !important;
        line-height: 1.1 !important;
    }

    /* ───────────── 結果カード ───────────── */
    .result-card {
        background: var(--surface-0);
        padding: 1.6rem 1.8rem;
        border-radius: 10px;
        margin: 0.6rem 0;
        box-shadow: var(--shadow-sm);
        border: 1px solid var(--border);
        font-family: 'Noto Sans JP', sans-serif;
        color: var(--text-body);
        line-height: 1.85;
        font-size: 0.92rem;
        position: relative;
        transition: all 0.2s ease;
    }
    .result-card:hover {
        box-shadow: var(--shadow-md);
    }
    .result-card::before {
        content: '';
        position: absolute;
        left: 0; top: 0; bottom: 0;
        width: 3px;
        background: var(--brand);
        border-radius: 10px 0 0 10px;
    }
    .result-card.good::before { background: #C9A961; }
    .result-card.warn::before { background: #D49B5C; }
    .result-card.line::before { background: var(--brand); }
    .result-card strong { color: var(--text-dark); font-weight: 600; }

    /* ───────────── インフォボックス(処理時間目安) ───────────── */
    [data-testid="stAlert"] {
        background: var(--surface-0) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        box-shadow: var(--shadow-sm);
        padding: 1.1rem 1.3rem !important;
    }
    [data-testid="stAlert"][data-baseweb="notification"]:has([data-testid="stMarkdownContainer"]) {
        border-left: 3px solid var(--brand) !important;
    }

    /* spinner */
    .stSpinner > div {
        border-color: var(--brand) !important;
        border-top-color: transparent !important;
    }

    /* ───────────── code / pre ───────────── */
    code, pre {
        font-family: 'JetBrains Mono', 'Inter', monospace !important;
        background: var(--surface-2) !important;
        color: var(--text-dark) !important;
        border: 1px solid var(--border) !important;
        border-radius: 6px !important;
        font-size: 0.85rem !important;
    }

    /* ───────────── 区切り線 ───────────── */
    hr {
        border: none !important;
        height: 1px !important;
        background: var(--border) !important;
        margin: 3rem 0 2rem 0 !important;
    }

    /* ───────────── キャプション ───────────── */
    [data-testid="stCaptionContainer"],
    .stCaption {
        color: var(--text-mute) !important;
        font-family: 'Inter', 'Noto Sans JP', sans-serif !important;
        font-size: 0.78rem !important;
        letter-spacing: 0.02em;
    }

    /* ───────────── ログイン画面(エンタープライズ風) ───────────── */
    .login-wrapper {
        max-width: 440px;
        margin: 6rem auto 0 auto;
        text-align: center;
        background: var(--surface-0);
        padding: 3rem 2.5rem;
        border-radius: 12px;
        box-shadow: var(--shadow-lg);
        border: 1px solid var(--border);
    }
    .login-wrapper .topbar-logo {
        display: inline-block;
        font-size: 1.8rem;
        margin-bottom: 1rem;
    }
    .login-subtitle {
        font-family: 'Inter', 'Noto Sans JP', sans-serif;
        font-size: 0.85rem;
        color: var(--text-mute);
        margin: 0.5rem 0 2rem 0;
        letter-spacing: 0.04em;
    }

    /* ───────────── フッター ───────────── */
    .app-footer {
        margin-top: 5rem;
        padding-top: 2rem;
        border-top: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        color: var(--text-mute);
        letter-spacing: 0.04em;
    }
    .app-footer .footer-brand {
        font-family: 'Cormorant Garamond', serif;
        font-size: 0.85rem;
        color: var(--text-body);
        letter-spacing: 0.06em;
    }
    .app-footer .footer-tech {
        display: flex;
        gap: 1.2rem;
        align-items: center;
    }

    /* ───────────── 成功・エラー装飾 ───────────── */
    [data-testid="stAlert"][kind="success"] {
        background: rgba(201,169,97,0.06) !important;
        border-color: rgba(201,169,97,0.25) !important;
        border-left: 3px solid var(--accent) !important;
    }
    [data-testid="stAlert"][kind="error"] {
        background: rgba(212,107,89,0.06) !important;
        border-color: rgba(212,107,89,0.25) !important;
        border-left: 3px solid #D46B59 !important;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ── ロゴ表示 ──────────────────────────────────────
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


def render_topbar():
    """トップナビゲーション(エンタープライズSaaS風)"""
    st.markdown("""
    <div class="topbar">
        <div class="topbar-left">
            <span class="topbar-logo">KOSHIKI <span class="multiply">×</span> La pilates</span>
            <span class="topbar-divider"></span>
            <span class="topbar-product">Counseling FB System</span>
        </div>
        <div class="topbar-meta">
            <span class="status-badge">Online</span>
            <span class="version-tag">v1.2.0</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_hero():
    """ヒーローセクション(プロダクト紹介)"""
    st.markdown("""
    <div class="hero-wrap">
        <span class="hero-eyebrow">New Counseling Feedback</span>
        <h1 class="hero-title">育成FB <em>を自動で。</em></h1>
        <p class="hero-subtitle">
            新規カウンセリング録音をアップロードするだけで、AIが姿勢分析・パーソナルワーク哲学<br>
            に沿った 4軸スコアリング・パーソナライズFB を自動生成します。
        </p>
    </div>
    """, unsafe_allow_html=True)


def render_footer():
    """フッター"""
    st.markdown("""
    <div class="app-footer">
        <div class="footer-brand">KOSHIKI × La pilates</div>
        <div class="footer-tech">
            <span>⚡ Powered by Gemini 2.0 Flash</span>
            <span>🔒 Data is processed securely</span>
            <span>© 2026 KOSHIKI × La pilates</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── パスワード認証 ────────────────────────────────────

def check_password():
    """松崎さん設定のパスワードでログイン
    URL クエリパラメータ ?key=xxx でも自動ログイン可
    例: https://pilates-fb.streamlit.app/?key=miraipilates5721!
    """
    APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")

    # ── URLクエリパラメータでの自動ログイン ──
    try:
        url_key = st.query_params.get("key", "")
    except Exception:
        # 古いStreamlit互換
        url_key = st.experimental_get_query_params().get("key", [""])[0]
    if url_key and url_key == APP_PASSWORD:
        st.session_state["password_correct"] = True

    def password_entered():
        if st.session_state.get("password") == APP_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.markdown(
        '<div class="login-wrapper">'
        '<div class="topbar-logo">KOSHIKI <span class="multiply">×</span> La pilates</div>'
        '<p class="login-subtitle">Counseling Feedback System</p>',
        unsafe_allow_html=True,
    )
    st.text_input(
        "パスワード", type="password", on_change=password_entered,
        key="password", label_visibility="collapsed",
        placeholder="Enter your password",
    )
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("パスワードが違います")
    st.markdown('</div>', unsafe_allow_html=True)
    return False


# ── メイン画面 ────────────────────────────────────────

def main():
    if not check_password():
        st.stop()

    render_topbar()
    render_hero()

    COURSE_OPTIONS = [
        "—",
        "サブスク 月1", "サブスク 月2", "サブスク 月3", "サブスク 月4", "サブスク 月6",
        "年払い 月1", "年払い 月2", "年払い 月3", "年払い 月4", "年払い 月6",
        "整体なし 月2", "整体なし 月3", "整体なし 月4", "整体なし 月6",
        "トライアル 2回",
    ]

    # 入会の有無 は form の外(動的にコース有効/無効を切り替えるため)
    st.markdown('<div class="section-title">01 · Session Information</div>', unsafe_allow_html=True)

    STORE_OPTIONS = ["川越", "大宮", "高崎", "神戸元町", "西宮北口", "所沢", "浦和"]

    col1, col2 = st.columns(2)
    with col1:
        store = st.selectbox("店舗", STORE_OPTIONS, index=0, key="store_select")
    with col2:
        staff_name = st.text_input("スタッフ名", placeholder="例: MIRAI", key="staff_name_input")
    session_date = st.date_input("セッション日", value=date.today(), key="session_date_input")

    st.markdown('<div class="section-title">02 · Contract Result</div>', unsafe_allow_html=True)
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
        st.markdown('<div class="section-title">03 · Customer Information</div>', unsafe_allow_html=True)
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

        st.markdown('<div class="section-title">04 · Audio Recording</div>', unsafe_allow_html=True)
        audio_file = st.file_uploader(
            "録音ファイル",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            label_visibility="collapsed",
            help=("新規カウンセリング・体験レッスン・クロージングの録音\n\n"
                  "⏱ 目安(Gemini Audio): 30分録音 → 約30秒〜1.5分 / 60分録音 → 約1〜3分"),
        )

        st.markdown('<div class="section-title">05 · Questions for Leader  (Optional)</div>', unsafe_allow_html=True)
        questions = st.text_area(
            "疑問点(リーダー/研修担当に聞きたいこと)",
            placeholder="例: 産後ママへのクロージングがうまくできない / トライアル後の提案タイミングは?",
            height=80,
            help="任意。リーダーや研修担当に相談したいことがあれば記入してね",
        )

        submitted = st.form_submit_button("Generate Feedback  →", type="primary")

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
        from coaching.coaching_analyzer import analyze_session, SINGLE_FILE_SIZE_LIMIT_MB, CHUNK_MINUTES, MAX_PARALLEL_WORKERS
        # ファイルサイズで処理方式を自動判定
        size_mb = audio_file.size / 1024 / 1024
        if size_mb <= SINGLE_FILE_SIZE_LIMIT_MB:
            mode_label = "🚀 一発処理モード"
            est_low = max(1, int(size_mb * 0.05))
            est_high = max(2, int(size_mb * 0.15))
            mode_detail = f"{size_mb:.1f}MB → 通常処理(文字起こし+評価を1回で完結)"
        else:
            mode_label = "⚡️ 並列チャンク処理モード"
            est_chunks = max(2, int(size_mb / CHUNK_MINUTES) + 1)
            est_low = max(1, est_chunks // MAX_PARALLEL_WORKERS + 1)
            est_high = max(2, est_chunks // MAX_PARALLEL_WORKERS + 3)
            mode_detail = (
                f"{size_mb:.1f}MB → {CHUNK_MINUTES}分ごとに約{est_chunks}チャンクへ分割、"
                f"{MAX_PARALLEL_WORKERS}並列で文字起こし→評価生成"
            )

        spinner_msg = (
            f"{mode_label}: {size_mb:.1f}MB の音声を処理中... 予測 {est_low}〜{est_high}分💕\n\n"
            f"完了するとSlackに通知が届くから、このタブはそのまま開いておいてね"
        )
        st.info(
            f"⏱ **{mode_label}**\n\n"
            f"{mode_detail}\n\n"
            f"完了見込み: **約{est_low}〜{est_high}分** ✨"
        )
        with st.spinner(spinner_msg):
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
        st.markdown('<div class="section-title">Session Summary</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card line">{result.get("session_summary", "(要約なし)")}</div>', unsafe_allow_html=True)

        # スコア
        st.markdown('<div class="section-title">Evaluation Scores</div>', unsafe_allow_html=True)
        scores = result.get("scores", {})
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a: st.metric("HEARING",  f"{scores.get('hearing', 0)} / 5")
        with col_b: st.metric("PROPOSAL", f"{scores.get('proposal', 0)} / 5")
        with col_c: st.metric("CLOSING",  f"{scores.get('closing', 0)} / 5")
        with col_d: st.metric("TONE",     f"{scores.get('tone', 0)} / 5")

        # 良かったポイント
        st.markdown('<div class="section-title">Strengths</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card good">{result.get("good_points", "(なし)")}</div>', unsafe_allow_html=True)

        # 改善点
        st.markdown('<div class="section-title">Improvements</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card warn">{result.get("improvements", "(なし)")}</div>', unsafe_allow_html=True)

        # 疑問点(任意入力があれば表示)
        if questions.strip():
            st.markdown('<div class="section-title">Questions for Leader</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="result-card line">{questions.strip()}</div>', unsafe_allow_html=True)

        st.divider()
        st.caption("✓ Slack #ピラティス_新規振り返り に自動投稿済み  ·  振り返り内容 + 評価 + FB + 疑問点")

        # Notion 蓄積リンク
        notion_url = result.get("notion_url", "")
        if notion_url:
            st.caption(f"📊 Notion蓄積完了 → [履歴ページを開く]({notion_url})")

    # フッター(全画面共通)
    render_footer()


if __name__ == "__main__":
    main()
