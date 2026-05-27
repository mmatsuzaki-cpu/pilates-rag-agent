"""streamlit_app.py - ピラティス育成FBシステム(Studio Coach風)

Streamlit Cloud のエントリポイント。
カウンセリング録音をアップロード → 文字起こし → AI評価 → 育成FB生成。

【無料運用】
- 文字起こし: faster-whisper(オープンソース)
- AI評価: Gemini Flash 2.5 API(月20件で約25円)
- パスワード保護: Streamlit secrets の APP_PASSWORD で照合

【処理時間】 5分音声 → 約30秒で文字起こし + 30秒でAI評価 = 約1分
"""

import streamlit as st
from datetime import date


# ── パスワード認証 ────────────────────────────────────

def check_password():
    """松崎さん設定のパスワードでログイン"""
    def password_entered():
        if st.session_state.get("password") == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 入力消去
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("🔒 パスワード", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("パスワードが違うょ💦")
    return False


# ── メイン画面 ────────────────────────────────────────

def main():
    st.set_page_config(page_title="ピラティス育成FB", page_icon="🧘‍♀️", layout="centered")

    # パスワード認証
    if not check_password():
        st.stop()

    st.title("🧘‍♀️ ピラティス育成FBシステム")
    st.caption("カウンセリング録音をアップロード → 5項目評価 + LINE文面を自動生成")

    st.divider()

    # 入力フォーム
    with st.form("upload_form"):
        col1, col2 = st.columns(2)
        with col1:
            staff_name = st.text_input("👤 スタッフ名", placeholder="例: YUKINO")
        with col2:
            session_date = st.date_input("📅 セッション日", value=date.today())

        audio_file = st.file_uploader(
            "🎤 録音ファイル",
            type=["m4a", "mp3", "wav", "mp4", "aac"],
            help="新規カウンセリング・体験レッスン・クロージングの録音",
        )

        notes = st.text_area("📝 メモ(任意)", placeholder="お客様の属性メモ等(あれば)")

        submitted = st.form_submit_button("✨ フィードバックを生成する", type="primary")

    if submitted:
        if not staff_name:
            st.error("スタッフ名を入力してね💦")
            return
        if not audio_file:
            st.error("録音ファイルを選んでね💦")
            return

        # 処理(coaching_analyzer.py を呼ぶ)
        from coaching.coaching_analyzer import analyze_session
        with st.spinner("🎙️ 文字起こし + AI評価中... 1〜2分かかるょ💕"):
            try:
                result = analyze_session(audio_file, staff_name, session_date, notes)
            except Exception as e:
                st.error(f"処理失敗💦 {e}")
                return

        # 結果表示
        st.success("✨ フィードバック生成完了!")
        st.divider()

        # スコア表示(★★★★★)
        st.subheader("📊 評価")
        col_a, col_b, col_c, col_d = st.columns(4)
        scores = result.get("scores", {})
        with col_a: st.metric("ヒアリング", f"★{scores.get('hearing', 0)}/5")
        with col_b: st.metric("提案",     f"★{scores.get('proposal', 0)}/5")
        with col_c: st.metric("クロージング", f"★{scores.get('closing', 0)}/5")
        with col_d: st.metric("トーン",   f"★{scores.get('tone', 0)}/5")

        st.divider()

        # 良かったポイント
        st.subheader("💎 良かったポイント")
        st.markdown(result.get("good_points", "(なし)"))

        # 改善点
        st.subheader("🎯 改善点")
        st.markdown(result.get("improvements", "(なし)"))

        # LINE用文面(コピペ用)
        st.subheader("📩 LINE用文面(コピペ可)")
        st.code(result.get("line_message", ""), language="text")

        st.divider()
        st.caption(f"📡 Slack/Notion 通知も自動送信されたょ✨")


if __name__ == "__main__":
    main()
