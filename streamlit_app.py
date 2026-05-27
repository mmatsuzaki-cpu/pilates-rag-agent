"""streamlit_app.py - ピラティスFBシステム(Studio Coach風)

Streamlit Cloud のエントリポイント。
カウンセリング録音をアップロード → 文字起こし → AI評価 → 育成FB生成。
"""

import streamlit as st
from datetime import date


# ── ページ設定(最初に1回だけ) ─────────────────────
st.set_page_config(
    page_title="ピラティスFBシステム",
    page_icon="🧘‍♀️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ── カスタムCSS ──────────────────────────────────
CUSTOM_CSS = """
<style>
    /* Streamlitヘッダー非表示 */
    [data-testid="stHeader"] {
        background: transparent;
        height: 0;
    }
    [data-testid="stToolbar"] {
        display: none;
    }
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}

    /* 全体背景 */
    .stApp {
        background: linear-gradient(135deg, #f7f9fa 0%, #e8f4f1 50%, #f0f7f3 100%);
    }

    /* メインコンテナ */
    .main .block-container {
        max-width: 760px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }

    /* タイトルヒーロー */
    .hero {
        background: linear-gradient(135deg, #2D7A6A 0%, #1a4d44 100%);
        color: white;
        padding: 2.5rem 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 12px 36px rgba(45, 122, 106, 0.25);
        position: relative;
        overflow: hidden;
    }
    .hero::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -10%;
        width: 200px;
        height: 200px;
        background: rgba(255,255,255,0.05);
        border-radius: 50%;
    }
    .hero::after {
        content: '';
        position: absolute;
        bottom: -30%;
        left: -10%;
        width: 150px;
        height: 150px;
        background: rgba(255,255,255,0.05);
        border-radius: 50%;
    }
    .hero h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        position: relative;
        z-index: 1;
    }
    .hero p {
        margin: 0.75rem 0 0 0;
        opacity: 0.92;
        font-size: 0.95rem;
        position: relative;
        z-index: 1;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(255,255,255,0.18);
        backdrop-filter: blur(10px);
        padding: 0.3rem 1rem;
        border-radius: 100px;
        font-size: 0.78rem;
        margin-top: 1rem;
        font-weight: 500;
        position: relative;
        z-index: 1;
    }

    /* セクション見出し */
    .section-title {
        font-size: 1.15rem;
        font-weight: 600;
        color: #1a4d44;
        margin: 1.5rem 0 0.75rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    /* フォームカード */
    div[data-testid="stForm"] {
        background: white;
        padding: 2rem !important;
        border-radius: 20px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.06);
        border: 1px solid rgba(45, 122, 106, 0.08);
    }

    /* プライマリボタン */
    .stButton button[kind="primary"],
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #2D7A6A 0%, #1a4d44 100%) !important;
        color: white !important;
        border: none !important;
        padding: 0.85rem 2rem !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
        width: 100% !important;
        transition: all 0.25s !important;
        box-shadow: 0 6px 18px rgba(45, 122, 106, 0.3) !important;
    }
    .stButton button[kind="primary"]:hover,
    .stFormSubmitButton button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 10px 24px rgba(45, 122, 106, 0.4) !important;
    }

    /* 入力欄 */
    .stTextInput input,
    .stTextArea textarea,
    .stDateInput input {
        border-radius: 12px !important;
        border: 1.5px solid rgba(0,0,0,0.08) !important;
        padding: 0.65rem 0.9rem !important;
        transition: all 0.2s !important;
    }
    .stTextInput input:focus,
    .stTextArea textarea:focus,
    .stDateInput input:focus {
        border-color: #2D7A6A !important;
        box-shadow: 0 0 0 3px rgba(45, 122, 106, 0.1) !important;
    }
    label {
        font-weight: 500 !important;
        color: #374151 !important;
    }

    /* ファイルアップローダー */
    [data-testid="stFileUploaderDropzone"] {
        background: linear-gradient(135deg, rgba(45,122,106,0.04) 0%, rgba(45,122,106,0.08) 100%);
        border: 2px dashed rgba(45, 122, 106, 0.35) !important;
        border-radius: 16px !important;
        transition: all 0.25s !important;
    }
    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: rgba(45, 122, 106, 0.6) !important;
        background: rgba(45, 122, 106, 0.06);
    }

    /* メトリクス */
    [data-testid="stMetric"] {
        background: white;
        padding: 1.25rem 1rem;
        border-radius: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        border: 1px solid rgba(45, 122, 106, 0.08);
        text-align: center;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem;
        color: #6b7280;
        font-weight: 500;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
        color: #2D7A6A;
        font-weight: 700;
    }

    /* 結果カード */
    .result-card {
        background: white;
        padding: 1.5rem 1.75rem;
        border-radius: 16px;
        margin: 1rem 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.05);
        border-left: 4px solid #2D7A6A;
    }
    .result-card.good { border-left-color: #10b981; }
    .result-card.warn { border-left-color: #f59e0b; }
    .result-card.line { border-left-color: #6366f1; }

    /* divider */
    hr {
        border-color: rgba(45, 122, 106, 0.15) !important;
        margin: 2rem 0 !important;
    }

    /* パスワード入力欄(ログイン時) */
    .login-card {
        background: white;
        padding: 2.5rem;
        border-radius: 20px;
        max-width: 420px;
        margin: 4rem auto;
        box-shadow: 0 12px 36px rgba(0,0,0,0.1);
        text-align: center;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


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

    st.markdown(
        '<div style="text-align:center; margin-top:4rem;">'
        '<h1 style="color:#2D7A6A; font-size:2.5rem; margin-bottom:0.5rem;">🔒</h1>'
        '<h2 style="color:#1a4d44; font-weight:600;">ピラティスFBシステム</h2>'
        '<p style="color:#6b7280;">パスワードを入力してください</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.text_input("パスワード", type="password", on_change=password_entered, key="password", label_visibility="collapsed")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("❌ パスワードが違うょ💦")
    return False


# ── メイン画面 ────────────────────────────────────────

def main():
    if not check_password():
        st.stop()

    # ヒーローセクション
    st.markdown("""
    <div class="hero">
        <h1>🧘‍♀️ ピラティスFBシステム</h1>
        <p>カウンセリング録音をアップロード → AIが5項目評価+LINE文面を自動生成</p>
        <span class="hero-badge">✨ AI Powered</span>
    </div>
    """, unsafe_allow_html=True)

    # 入力フォーム
    with st.form("upload_form"):
        st.markdown('<div class="section-title">📋 セッション情報</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            staff_name = st.text_input("👤 スタッフ名", placeholder="例: YUKINO")
        with col2:
            session_date = st.date_input("📅 セッション日", value=date.today())

        st.markdown('<div class="section-title">🎤 録音ファイル</div>', unsafe_allow_html=True)
        audio_file = st.file_uploader(
            "アップロード",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            label_visibility="collapsed",
            help="新規カウンセリング・体験レッスン・クロージングの録音",
        )

        st.markdown('<div class="section-title">📝 メモ(任意)</div>', unsafe_allow_html=True)
        notes = st.text_area(
            "メモ",
            placeholder="お客様の属性メモ等(あれば)",
            label_visibility="collapsed",
            height=100,
        )

        submitted = st.form_submit_button("✨ フィードバックを生成する", type="primary")

    if submitted:
        if not staff_name:
            st.error("スタッフ名を入力してね💦")
            return
        if not audio_file:
            st.error("録音ファイルを選んでね💦")
            return

        # 処理
        from coaching.coaching_analyzer import analyze_session
        with st.spinner("🎙️ 文字起こし + AI評価中... 1〜2分かかるょ💕"):
            try:
                result = analyze_session(audio_file, staff_name, session_date, notes)
            except Exception as e:
                st.error(f"処理失敗💦 {e}")
                return

        st.balloons()
        st.success("✨ フィードバック生成完了!")

        # スコア表示
        st.markdown('<div class="section-title">📊 評価</div>', unsafe_allow_html=True)
        scores = result.get("scores", {})
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a: st.metric("ヒアリング", f"★ {scores.get('hearing', 0)}/5")
        with col_b: st.metric("提案",     f"★ {scores.get('proposal', 0)}/5")
        with col_c: st.metric("クロージング", f"★ {scores.get('closing', 0)}/5")
        with col_d: st.metric("トーン",   f"★ {scores.get('tone', 0)}/5")

        # 良かったポイント
        st.markdown('<div class="section-title">💎 良かったポイント</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card good">{result.get("good_points", "(なし)")}</div>', unsafe_allow_html=True)

        # 改善点
        st.markdown('<div class="section-title">🎯 改善点</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-card warn">{result.get("improvements", "(なし)")}</div>', unsafe_allow_html=True)

        # LINE用文面
        st.markdown('<div class="section-title">📩 LINE用文面(コピペ可)</div>', unsafe_allow_html=True)
        st.code(result.get("line_message", ""), language="text")

        st.divider()
        st.caption("📡 Slack/Notion 通知も自動送信されたょ✨")


if __name__ == "__main__":
    main()
