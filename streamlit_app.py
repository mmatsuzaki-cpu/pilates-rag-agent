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
    page_icon="✦",
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

    /* タイトル */
    .app-title {
        text-align: center;
        font-family: 'Noto Serif JP', serif;
        color: #5C4A36;
        font-size: 1.5rem;
        font-weight: 400;
        letter-spacing: 0.15em;
        margin-bottom: 0.5rem;
    }
    .app-subtitle {
        text-align: center;
        color: #8B6F47;
        font-size: 0.85rem;
        margin-bottom: 2.5rem;
        font-weight: 300;
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
        <div class="logo-star">✦</div>
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
        '<p class="app-subtitle">カウンセリング録音をアップロード → AIが5項目評価+LINE文面を自動生成</p>',
        unsafe_allow_html=True,
    )

    # 入力フォーム
    with st.form("upload_form"):
        st.markdown('<div class="section-title">SESSION INFORMATION</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            staff_name = st.text_input("スタッフ名", placeholder="例: YUKINO")
        with col2:
            session_date = st.date_input("セッション日", value=date.today())

        st.markdown('<div class="section-title">CONTRACT RESULT</div>', unsafe_allow_html=True)
        col3, col4 = st.columns(2)
        with col3:
            contract = st.selectbox(
                "入会の有無",
                ["なし", "あり"],
                index=0,
                help="契約成立の有無を選んでね",
            )
        with col4:
            course = st.selectbox(
                "コース(入会ありの場合)",
                ["未契約", "月3", "月4", "月8", "月12", "年払い", "その他"],
                index=0,
                help="入会ありの場合に選択。なしなら未契約のまま",
            )

        st.markdown('<div class="section-title">AUDIO FILE</div>', unsafe_allow_html=True)
        audio_file = st.file_uploader(
            "録音ファイル",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            label_visibility="collapsed",
            help="新規カウンセリング・体験レッスン・クロージングの録音",
        )

        st.markdown('<div class="section-title">NOTES (OPTIONAL)</div>', unsafe_allow_html=True)
        notes = st.text_area(
            "メモ",
            placeholder="お客様の属性メモ等(あれば)",
            label_visibility="collapsed",
            height=100,
        )

        submitted = st.form_submit_button("✦  GENERATE FB  ✦", type="primary")

    if submitted:
        if not staff_name:
            st.error("スタッフ名を入力してね💦")
            return
        if not audio_file:
            st.error("録音ファイルを選んでね💦")
            return

        # 処理
        from coaching.coaching_analyzer import analyze_session
        with st.spinner("文字起こし + AI評価中...  1〜2分かかります"):
            try:
                result = analyze_session(
                    audio_file, staff_name, session_date, notes,
                    contract=contract, course=course,
                )
            except Exception as e:
                st.error(f"処理失敗💦 {e}")
                return

        st.success("✦ フィードバック生成完了")

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

        # LINE用文面
        st.markdown('<div class="section-title">LINE MESSAGE</div>', unsafe_allow_html=True)
        st.code(result.get("line_message", ""), language="text")

        st.divider()
        st.caption("Slack / Notion 通知は自動で送信されました")


if __name__ == "__main__":
    main()
