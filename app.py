import os
import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
import random
import base64
from CRAIN_stripe import (
    create_checkout_session,
    get_or_create_stripe_customer,
    create_billing_portal_session,
)

import stripe  # ← 追加
stripe.api_key = st.secrets["stripe"]["secret_key"]  # ← 追加
# 公開時は secrets.toml の [app] base_url に HTTPS 公開URLを設定する
APP_BASE_URL = st.secrets.get("app", {}).get("base_url", "http://localhost:8501").rstrip("/")
# --- Page Config ---
st.set_page_config(
    page_title="CRAIN | AI Video Script Generator",
    page_icon="crain_icon.png", 
    layout="wide"
)

# 画像をBase64形式に変換してHTMLに埋め込むためのヘルパー関数
def get_image_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return ""

logo_base64 = get_image_base64("crain_logo.png")
icon_base64 = get_image_base64("crain_icon.png")

# --- 漆黒の背景 ＆ 完全カスタムCSS ---
st.markdown(f"""
<html lang="ja" class="notranslate" translate="no">
<head>
    <meta name="google" content="notranslate" />
</head>
<style>
    /* ページの背景を完全な漆黒（#000000）に固定 */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
        background: #000000 !important;
        background-color: #000000 !important;
        color: #f1f5f9 !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    
    header, footer {{visibility: hidden;}}

    /* ロゴの完全シームレス配置 ＆ 拡大ボタン完全排除 */
    .crain-logo-wrapper {{
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 20px 0 5px 0;
        background: #000000 !important;
    }}
    .crain-logo-wrapper img {{
        max-width: 100%;
        width: 450px;
        background: #000000 !important;
        pointer-events: none;
    }}

    .crain-header-icon img {{
        width: 42px;
        height: 42px;
        border-radius: 10px;
        background: #000000 !important;
    }}

    /* フォーム・入力域のガラスモーフィズム */
    .stTextInput>div>div>input, .stSelectbox>div>div, .stTextArea>div>div>textarea {{
        background: rgba(18, 10, 36, 0.8) !important;
        border: 1px solid rgba(139, 92, 246, 0.4) !important;
        color: #f8fafc !important;
        border-radius: 12px !important;
        backdrop-filter: blur(16px);
    }}
    .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus {{
        border-color: #a855f7 !important;
        box-shadow: 0 0 25px rgba(168, 85, 247, 0.6) !important;
    }}

    /* ネオンボタン */
    .stButton>button {{
        background: linear-gradient(135deg, #7c3aed 0%, #4c1d95 100%) !important;
        color: #ffffff !important;
        border: 1px solid rgba(216, 180, 254, 0.5) !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        letter-spacing: 0.1em !important;
        transition: all 0.35s ease !important;
        box-shadow: 0 4px 30px rgba(124, 58, 237, 0.4) !important;
    }}
    .stButton>button:hover {{
        background: linear-gradient(135deg, #8b5cf6 0%, #5b21b6 100%) !important;
        box-shadow: 0 0 35px rgba(168, 85, 247, 0.85) !important;
        transform: translateY(-2px);
    }}

    /* タブデザイン */
    .stTabs [data-baseweb="tab-list"] {{
        background-color: rgba(15, 8, 30, 0.8);
        border-radius: 14px;
        padding: 6px;
        border: 1px solid rgba(139, 92, 246, 0.3);
    }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(135deg, rgba(124, 58, 237, 0.4) 0%, rgba(76, 29, 149, 0.4) 100%) !important;
        color: #ffffff !important;
        border-radius: 10px;
        border: 1px solid rgba(192, 132, 252, 0.4);
        box-shadow: 0 0 20px rgba(168, 85, 247, 0.4);
    }}
</style>
</html>
""", unsafe_allow_html=True)

# --- Initialize Supabase & OpenAI ---
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

openai_api_key = st.secrets.get("openai", {}).get("api_key", "")
client = OpenAI(api_key=openai_api_key) if openai_api_key else None

# --- Session & Multi-language ---
if "user" not in st.session_state:
    st.session_state.user = None

if "lang" not in st.session_state:
    st.session_state.lang = "日本語"

if "is_premium" not in st.session_state:
    st.session_state.is_premium = False

if "free_generation_left" not in st.session_state:
    st.session_state.free_generation_left = 2

if "premium_generation_left" not in st.session_state:
    st.session_state.premium_generation_left = 30

if "script_refine_left" not in st.session_state:
    st.session_state.script_refine_left = 0
if "idea_refine_left" not in st.session_state:
    st.session_state.idea_refine_left = 0
from datetime import datetime
from zoneinfo import ZoneInfo

def today_jst():
    return datetime.now(
        ZoneInfo("Asia/Tokyo")
    ).date().isoformat()


def usage_today():
    user = st.session_state.get("user")

    if user is None:
        return 0

    result = (
        supabase.table("daily_usage")
        .select("generation_count")
        .eq("user_id", str(user.id))
        .eq("usage_date", today_jst())
        .limit(1)
        .execute()
    )

    return (
        int(result.data[0]["generation_count"])
        if result.data
        else 0
    )

def reserve_generation():
    result = supabase.rpc(
        "crain_reserve_generation",
        {}
    ).execute()

    return result.data is True
try:
    auth_session = st.session_state.get("auth_session")

    if auth_session is not None:
        supabase.auth.set_session(
            auth_session.access_token,
            auth_session.refresh_token
        )

        current_user = supabase.auth.get_user()
        st.session_state.user = current_user.user
        st.write(
            "認証チェック:",
            "成功" if supabase.auth.get_session() else "失敗"
        )
except Exception as e:
    st.session_state.user = None
    st.session_state.is_premium = False
    st.error(f"認証セッションの復元に失敗しました: {e}")
# ログインユーザーの契約状態を取得
st.session_state.is_premium = False

user = st.session_state.get("user")

if user is not None:
    try:
        result = (
            supabase.table("subscriptions")
            .select("plan, status, stripe_live_plan, stripe_live_status")
            .eq("user_id", str(user.id))
            .limit(1)
            .execute()
        )

        if result.data:
            subscription = result.data[0]

            stripe_mode = st.secrets["stripe"].get("mode", "test")

            if stripe_mode == "live":
                plan = subscription.get("stripe_live_plan")
                status = subscription.get("stripe_live_status")
            else:
                plan = subscription.get("plan")
                status = subscription.get("status")

            st.session_state.is_premium = (
                plan == "premium"
                and status in ["active", "trialing"]
            )
        else:
            st.session_state.is_premium = False
    except Exception as e:
        st.session_state.is_premium = False
        st.error(f"契約情報の取得に失敗しました: {e}")

TEXTS = {
    "日本語": {
        "subtitle": "Create × AI × Innovation",
        "auth_select": "アクセスモード",
        "signin": "サインイン",
        "signup": "アカウント作成",
        "email_label": "メールアドレス",
        "pass_label": "パスワード",
        "btn_signin": "CRAINへログイン",
        "btn_signup": "アカウント新規作成",
        "tab_script": "台本生成",
        "tab_idea": "企画提供",
        "tab_archive": "生成履歴",
        "tab_saved": "保存済み",
        "tab_upgrade": "プレミアム",
        "tab_support": "サポート",
        "platform_label": "ターゲットプラットフォーム",
        "duration_label": "動画の長さ",
        "genre_label": "カテゴリー",
        "target_label": "ターゲット層（ペルソナ）",
        "tone_label": "トーン＆マナー",
        "topic_label": "テーマ・発信内容",
        "extra_label": "追加指示パラメーター",
        "btn_generate": "台本を生成する",
        "btn_refine": "台本を修正・再構築する",
        "ideas_genre": "ジャンル・領域",
        "btn_ideas": "企画アイデアを生成する",
        "monthly": "月額プラン",
        "annual": "年額プラン（おすすめ）",
    },
    "English": {
        "subtitle": "Create × AI × Innovation",
        "auth_select": "Access Mode",
        "signin": "Sign In",
        "signup": "Create Account",
        "email_label": "Email Address",
        "pass_label": "Password",
        "btn_signin": "Sign In to CRAIN",
        "btn_signup": "Create CRAIN Account",
        "tab_script": "Script",
        "tab_idea": "Ideation",
        "tab_archive": "Archive",
        "tab_saved": "Saved",
        "tab_upgrade": "Upgrade",
        "tab_support": "Support",
        "platform_label": "Target Platform",
        "duration_label": "Target Duration",
        "genre_label": "Category",
        "target_label": "Target Persona",
        "tone_label": "Tone & Style",
        "topic_label": "Main Topic / Concept",
        "extra_label": "Additional Parameters",
        "btn_generate": "GENERATE SCRIPT",
        "btn_refine": "REFINE SCRIPT",
        "ideas_genre": "Domain / Category",
        "btn_ideas": "GENERATE IDEAS",
        "monthly": "Monthly Plan",
        "annual": "Annual Plan (Recommended)",
    }
}

t = TEXTS[st.session_state.lang]

# ---------------------------------------------------------
# 画面制御: 未ログイン時
# ---------------------------------------------------------
# ==========================================
# CRAIN 法律関連ページ
# ==========================================

if st.session_state.user is None:
    # HTMLタグで直接画像を埋め込むことで、拡大ボタンを完全に回避し背景と一体化
    st.markdown(f"""
        <div class="crain-logo-wrapper">
            <img src="data:image/png;base64,{logo_base64}">
        </div>
        <div style='text-align:center; color:#a78bfa; letter-spacing:0.25em; font-size:0.85rem; font-weight: 500; margin-bottom: 35px;'>{t['subtitle']}</div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        lang_choice = st.selectbox("Language / 言語", ["日本語", "English"], index=0 if st.session_state.lang == "日本語" else 1)
        if lang_choice != st.session_state.lang:
            st.session_state.lang = lang_choice
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        auth_mode = st.radio(t["auth_select"], [t["signin"], t["signup"]], horizontal=True)
        
        email = st.text_input(t["email_label"], placeholder="name@domain.com")
        password = st.text_input(t["pass_label"], type="password", placeholder="••••••••")

        st.markdown("<br>", unsafe_allow_html=True)
        if auth_mode == t["signin"]:
            if st.button(t["btn_signin"], use_container_width=True):
                if not email or not password:
                    st.warning("情報を入力してください。")
                else:
                    try:
                        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state.user = res.user
                        st.session_state.auth_session = res.session
                        
                        supabase.auth.set_session(
                            res.session.access_token,
                            res.session.refresh_token
                        )

                        st.rerun()
                    except Exception:
                        st.error("認証失敗: メールアドレスまたはパスワードが正しくありません。")
        else:
            if st.button(t["btn_signup"], use_container_width=True):
                if not email or not password:
                    st.warning("情報を入力してください。")
                else:
                    try:
                        res = supabase.auth.sign_up({"email": email, "password": password})
                        st.success("アカウントが正常に作成されました。サインインを行ってください。")
                    except Exception as e:
                        st.error(f"作成失敗: {e}")
    # ==========================================
    # CRAIN 法律関連ページ
    # ==========================================

    with st.expander("📄 利用規約・プライバシーポリシー・特定商取引法に基づく表記"):

        tab_terms, tab_privacy, tab_law = st.tabs([
            "利用規約",
            "プライバシーポリシー",
            "特定商取引法に基づく表記"
        ])

        with tab_terms:
            st.subheader("CRAIN 利用規約")
            st.write("""
    本サービス「CRAIN」は、AIを活用した動画制作支援サービスです。

    利用者は、法令および本規約を遵守してサービスを利用するものとします。

    生成された文章については、利用者自身が内容の正確性や適法性を確認してください。

    本サービスの不正利用、第三者の権利侵害、違法行為を禁止します。

    有料プランは月額1,980円、年額19,800円です。
    契約は解約されるまで自動更新されます。

    解約はアプリ内の契約管理画面から行えます。
            """)

        with tab_privacy:
            st.subheader("プライバシーポリシー")
            st.write("""
    CRAINでは、サービス提供のために以下の情報を取り扱います。

    ・メールアドレス
    ・アカウント情報
    ・動画生成に必要な入力情報
    ・生成履歴
    ・サブスクリプション契約情報

    取得した情報は、認証、サービス提供、決済管理、
    お問い合わせ対応、サービス改善のために利用します。

    決済にはStripe、データ管理にはSupabase、
    AI文章生成にはOpenAIのサービスを利用します。

    個人情報は、法令に基づく場合などを除き、
    必要な範囲を超えて第三者に提供しません。

    お問い合わせ：
    [krto1yout1@gmail.com]
            """)

        with tab_law:
            st.subheader("特定商取引法に基づく表記")
            st.write("""
    販売事業者：［加藤 綾隼］
    サービス名：CRAIN

    所在地・電話番号：
    請求があった場合、遅滞なく開示いたします。

    お問い合わせ：
    ［krto1yout1@gmail.com］

    販売価格：
    月額1,980円（税込）
    年額19,800円（税込）

    支払方法：
    クレジットカード決済

    支払時期：
    初回申込時および各契約更新時

    解約方法：
    アプリ内の契約管理画面から手続きできます。

    解約後の利用：
    契約期間終了まで利用可能です。

    返品・返金：
    原則として返金には応じません。
    ただし、法令上必要な場合を除きます。
            """)
# ---------------------------------------------------------
# 画面制御: ログイン済み時
# ---------------------------------------------------------
else:
    # --- Sidebar ---
    st.sidebar.markdown("### SYSTEM SETTINGS")
    selected_lang = st.sidebar.selectbox("Language / 言語", ["日本語", "English"], index=0 if st.session_state.lang == "日本語" else 1)
    if selected_lang != st.session_state.lang:
        st.session_state.lang = selected_lang
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.text(f"User:\n{st.session_state.user.email}")
    st.sidebar.markdown("<br>", unsafe_allow_html=True)

    if st.sidebar.button("LOGOUT", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.session_state.is_premium = False
        st.rerun()

    # --- Header ---
    col_icon, col_title, col_status = st.columns([0.4, 2.6, 1.5])

    with col_icon:
        st.markdown(f"""
            <div class="crain-header-icon" style="padding-top: 4px;">
                <img src="data:image/png;base64,{icon_base64}">
            </div>
        """, unsafe_allow_html=True)

    with col_title:
        st.markdown("""
            <div style="margin-top: -2px;">
                <span style="font-size: 1.8rem; font-weight: 900; letter-spacing: 0.15em; color: #fff;">
                    CRAIN
                </span>
            </div>
        """, unsafe_allow_html=True)
        st.caption("Next-Generation Video Script Architecture")

        with col_status:
            is_prem = st.session_state.get("is_premium", False)

            try:
                used_today = usage_today()
            except Exception:
                used_today = None
                st.warning("利用回数を取得できませんでした。")

        daily_limit = 30 if is_prem else 2
        remaining = max(0, daily_limit - used_today) if used_today is not None else "確認不可"

        if is_prem:
            st.markdown(
                f"<div style='text-align:right; color:#a855f7;'>"
                f"💎 PREMIUM｜残り {remaining} / {daily_limit} 回"
                f"</div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div style='text-align:right; color:#94a3b8;'>"
                f"FREE｜残り {remaining} / {daily_limit} 回"
                f"</div>",
                unsafe_allow_html=True
            )

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        t["tab_script"], t["tab_idea"], t["tab_archive"], t["tab_saved"], t["tab_upgrade"], t["tab_support"]
    ])

    # ---------------------------------------------------------
    # TAB 1: 台本生成
    # ---------------------------------------------------------
    with tab1:
        st.markdown(f"##### {t['tab_script']}")
        
        platform = st.selectbox(
            t["platform_label"], 
            ["TikTok / YouTube Shorts", "Instagram Reels", "YouTube (Long-form)", "Other"],
            key="script_platform"
        )
        
        duration_options = [f"{i}分 (約{i * 300}文字)" for i in range(1, 11)]
        target_duration_selection = st.selectbox(t["duration_label"], duration_options, key="script_duration")
        
        genre = st.selectbox(t["genre_label"], ["ビジネス・副業", "エンタメ・トレンド", "美容・ヘルスケア", "ライフスタイル・ガジェット", "教育・解説", "その他"], key="script_genre")
        target_audience = st.text_input(t["target_label"], placeholder="例: 20代後半の業務効率化に関心があるビジネスパーソン", key="script_target")
        speaking_style = st.text_input(t["tone_label"], placeholder="例: 知的で信頼感があり、テンポの良い構成", key="script_style")
        topic = st.text_area(t["topic_label"], placeholder="例: 2026年に絶対に導入すべきAI自動化ツール3選", key="script_topic_input")
        extra_instructions = st.text_area(t["extra_label"], placeholder="例: 冒頭3秒で具体的な数字を提示し、視覚的フックを強める", key="script_extra")

        use_trend_ai = False
        if is_prem:
            use_trend_ai = st.checkbox("CRAIN Trend & Algorithm Optimization Module", value=True, key="script_trend")

        if st.button(t["btn_generate"], key="generate_script_btn"):
            can_generate = True
            
            if can_generate:
                if not topic:
                    st.warning("メインテーマを入力してください。")
                elif not client:
                    st.error("OpenAI APIキーの認識に失敗しました。")
                else:
                    try:
                        allowed = reserve_generation()
                    except Exception as e:
                        allowed = False
                        st.error(f"生成回数の確認に失敗しました: {e}")
                    
                    if not allowed:
                        st.warning(
                          "🔒 現在、台本を生成できません。\n\n"
                            "本日の無料生成回数を使い切った可能性があります。\n\n"
                            "生成回数が残っている場合は、再ログインをお試しください。"
                         )
                        if not is_prem:
                            st.info(
                                "💎 CRAIN PREMIUMなら、"
                                "無料プランより多くの台本を生成できます。"
                            )
                            st.caption("画面上部の「プレミアム」タブからプランを確認できます。")
                        st.stop()
                    
                    with st.spinner("CRAIN Neural Processing..."):
                            trend_instruction = ""
                            if use_trend_ai:
                                trend_instruction = """
                            【CRAIN トレンド・アルゴリズム解析モジュール】
                            台本冒頭に以下の分析セクションを挿入してください:
                            ■ CRAIN ALGORITHM & TREND ANALYSIS
                            - トレンド合致ポイント:
                            - 視聴維持率最適化ロジック:
                            """

                            prompt = f"""
                            あなたは最高峰の映像脚本家およびマーケティングプロデューサーです。
                            以下の条件に従い、洗練された動画台本を作成してください。

                            {trend_instruction}

                            【仕様】
                            - プラットフォーム: {platform}
                            - 時間定義: {target_duration_selection}
                            - ジャンル: {genre}
                            - ペルソナ: {target_audience}
                            - トーン: {speaking_style}
                            - テーマ: {topic}
                            - 指示: {extra_instructions}
                            
                            【構成】
                            1. Hook（最初の3秒の惹きつけ）
                            2. Body（テンポの良い本編解説、映像指示・テロップ指示を含む）
                            3. Call to Action（効果的な結び）
                            """

                            try:
                                response = client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "user", "content": prompt}],
                                temperature=0.7,
                                )
                                generated_script = response.choices[0].message.content
                            
                                st.session_state.last_generated_script = generated_script
                                st.session_state.last_topic_info = f"[{platform} / {target_duration_selection}] {topic}"
                                
                                st.session_state.script_refine_left = 3 if is_prem else 1

                                data = {
                                    "user_id": st.session_state.user.id,
                                    "topic": st.session_state.last_topic_info,
                                    "script": generated_script
                                }
                                supabase.table("generation_history").insert(data).execute()
                                st.rerun()

                            except Exception as e:
                                st.error(f"システムエラーが発生しました: {e}")

        # 出力結果
        if "last_generated_script" in st.session_state and st.session_state.last_generated_script:
            st.markdown("---")
            st.markdown("##### 出力結果")
            
            char_count = len(st.session_state.last_generated_script)
            est_seconds = int((char_count / 300) * 60)
            est_min = est_seconds // 60
            est_sec = est_seconds % 60
            st.caption(f"Volume: 約 {char_count}文字 ｜ Estimated Time: 約 {est_min}分 {est_sec}秒")

            st.text_area("Script Output", value=st.session_state.last_generated_script, height=350, key="current_script_display")

            if st.button("BOOKMARK TO CRAIN LIBRARY"):
                try:
                    fav_data = {
                        "user_id": st.session_state.user.id,
                        "topic": f"⭐ [お気に入り] {st.session_state.get('last_topic_info', '台本')}",
                        "script": st.session_state.last_generated_script
                    }
                    supabase.table("generation_history").insert(fav_data).execute()
                    st.success("CRAINライブラリに保存しました。")
                except Exception as e:
                    st.error(f"保存失敗: {e}")

            st.divider()
            refine_cap = "3回" if is_prem else "1回"
            st.markdown(f"##### リファインメント（残り可能回数: {st.session_state.script_refine_left} / {refine_cap}）")
            
            with st.form(key="script_refine_form"):
                feedback_script = st.text_area("修正指示・フィードバック", placeholder="例: 専門用語の表現をより洗練された言い回しに変更")
                submit_script_fix = st.form_submit_button(t["btn_refine"])

            if submit_script_fix:
                if st.session_state.script_refine_left <= 0:
                    st.error("本セクションの修正回数上限に達しました。")
                elif not feedback_script:
                    st.warning("フィードバック内容を入力してください。")
                else:
                    with st.spinner("Refining Script..."):
                        fix_prompt = f"""
                        既存の台本構造に対して、以下のフィードバックを高度に適用して修正・昇華させてください。

                        【既存台本】
                        {st.session_state.last_generated_script}

                        【フィードバック指示】
                        {feedback_script}
                        """
                        try:
                            res_fix = client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "user", "content": fix_prompt}],
                                temperature=0.7,
                            )
                            fixed_script = res_fix.choices[0].message.content
                            st.session_state.last_generated_script = fixed_script
                            st.session_state.script_refine_left -= 1

                            data = {
                                "user_id": st.session_state.user.id,
                                "topic": f"{st.session_state.last_topic_info} (Refined)",
                                "script": fixed_script
                            }
                            supabase.table("generation_history").insert(data).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")

    # ---------------------------------------------------------
    # TAB 2: アイデア生成
    # ---------------------------------------------------------
    with tab2:
        st.markdown(f"##### {t['tab_idea']}")
        
        idea_genre = st.text_input(t["ideas_genre"], placeholder="例: 次世代AIマーケティング / 資産形成", key="idea_genre_input")
        
        use_trend_ideas = False
        if is_prem:
            use_trend_ideas = st.checkbox("CRAIN トレンド解析モジュールを含める", value=True, key="idea_trend")

        template_pool = [
            "絶対やってはいけないNG行動3選", "プロが教える裏技テクニック", "知らなきゃ損する最新トレンド",
            "1日で人生が変わる習慣", "初心者がやりがちな大きな勘違い", "裏側をすべて見せます",
            "たった1分でできる時短術", "ガチで買ってよかった愛用品", "半年間試してわかった本当の結果"
        ]

        if st.button(t["btn_ideas"], key="generate_ideas_btn", use_container_width=True):
            if not idea_genre.strip():
                st.warning("ジャンルを入力してください。")
            elif not client:
                st.error("OpenAI APIキーの認識に失敗しました。")
            else:
                try:
                    allowed = reserve_generation()
                except Exception as e:
                    allowed = False
                    st.error(f"生成回数の確認に失敗しました: {e}")

                if not allowed:
                    st.warning("本日の生成上限に達したか、利用枠を確認できませんでした。")
                else:
                    with st.spinner("CRAIN Analyzing Market Vectors..."):
                        selected_templates = random.sample(template_pool, min(7, len(template_pool)))
                        
                        trend_idea_text = ""
                        if use_trend_ideas:
                            trend_idea_text = "※冒頭に『CRAIN TREND ANALYSIS: 今この市場領域で成果が出る構成要素』の解説を付与してください。"

                        idea_prompt = f"""
                        あなたは最高峰のSNSマーケティングコンサルタントです。
                        ターゲット領域：「{idea_genre}」
                        {trend_idea_text}

                        市場分析データを基に、極めてバズ精度の高い動画企画コンセプトを7つ生成してください。

                        テンプレート構成基準: {selected_templates}

                        出力フォーマット:
                        - 【コンセプトタイトル】
                        - 【ターゲットフック & ロジック】
                        """
                        try:
                            response = client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "user", "content": idea_prompt}],
                                temperature=0.8,
                            )
                            generated_ideas = response.choices[0].message.content
                            st.session_state.last_generated_ideas = generated_ideas
                            st.session_state.last_idea_genre = idea_genre
                            
                            st.session_state.idea_refine_left = 3 if is_prem else 1

                            st.rerun()
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")

        if "last_generated_ideas" in st.session_state and st.session_state.last_generated_ideas:
            st.markdown("---")
            st.text_area("Ideas Output", value=st.session_state.last_generated_ideas, height=350, key="current_ideas_display")

            if st.button("BOOKMARK TO CRAIN LIBRARY", key="bookmark_script"):
                try:
                    fav_data = {
                        "user_id": st.session_state.user.id,
                        "topic": f"⭐ [お気に入り企画] {st.session_state.get('last_idea_genre', 'ジャンル')}",
                        "script": st.session_state.last_generated_ideas
                    }
                    supabase.table("generation_history").insert(fav_data).execute()
                    st.success("CRAINライブラリに保存しました。")
                except Exception as e:
                    st.error(f"保存失敗: {e}")

    # ---------------------------------------------------------
    # TAB 3: 過去履歴
    # ---------------------------------------------------------
    with tab3:
        st.markdown(f"##### {t['tab_archive']}")
        try:
            res = supabase.table("generation_history")\
                .select("*")\
                .eq("user_id", st.session_state.user.id)\
                .order("created_at")\
                .execute()
            
            history = res.data
            if history:
                normal_history = [item for item in history if not item.get('topic', '').startswith("⭐")]
                if normal_history:
                    for item in reversed(normal_history):
                        with st.expander(f"{item.get('topic', 'Untitled')}"):
                            st.caption(f"Date: {item.get('created_at', '')}")
                            st.markdown(item.get('script', ''))
                else:
                    st.info("アーカイブはありません。")
            else:
                st.info("アーカイブはありません。")
        except Exception:
            st.info("データの取得に失敗しました。")

    # ---------------------------------------------------------
    # TAB 4: ブックマーク
    # ---------------------------------------------------------
    with tab4:
        st.markdown(f"##### {t['tab_saved']}")
        try:
            fav_res = supabase.table("generation_history")\
                .select("*")\
                .eq("user_id", st.session_state.user.id)\
                .order("created_at")\
                .execute()
            
            all_data = fav_res.data
            if all_data:
                favorites = [item for item in all_data if item.get('topic', '').startswith("⭐")]
                if favorites:
                    for item in reversed(favorites):
                        with st.expander(f"{item.get('topic', 'Saved Item')}"):
                            st.caption(f"Date: {item.get('created_at', '')}")
                            st.markdown(item.get('script', ''))
                else:
                    st.info("保存されたコンテンツはありません。")
            else:
                st.info("保存されたコンテンツはありません。")
        except Exception:
            st.info("データの取得に失敗しました。")

        # ---------------------------------------------------------
    # TAB 5: プレミアムプラン
    # ---------------------------------------------------------
    with tab5:
        st.markdown("##### CRAIN PREMIUM SUITE")

        st.write("""
        プロダクションレベルの動画制作スピードと、高精度な市場適合を解禁します。

        - **30 Generations / Day** (Standard: 2/day)
        - **Advanced Refinement Engine** (最大3回までの精密修正)
        - **Algorithm & Trend Real-time Analysis**
        """)

        st.markdown("---")

                # Supabaseから最新の契約状態を取得
        user = st.session_state.get("user")
        
        if st.session_state.get("is_premium", False):
            st.success("PREMIUM PLAN ACTIVE")
            user = st.session_state.get("user")

            if user is not None:
                if st.button("契約内容の確認・解約", use_container_width=True):
                    try:
                        customer_id = get_or_create_stripe_customer(
                            supabase,
                            str(user.id),
                            user.email,
                        )

                        portal_url = create_billing_portal_session(
                            customer_id,
                            f"{APP_BASE_URL}/",
                        )

                        st.link_button(
                            "Stripeの契約管理ページを開く",
                            portal_url,
                            use_container_width=True,
                        )

                    except Exception as e:
                        st.exception(e)
                    
        else:
            col_m, col_y = st.columns(2)

            # 月額プラン
            with col_m:
                st.markdown(f"### {t['monthly']}")
                st.markdown("**¥1,980 / 月**")
                st.caption("月額自動更新")

                if st.button(
                    "月額プランを選択",
                    type="primary",
                    use_container_width=True
                ):
                    user = st.session_state.get("user")

                    if user is None:
                        st.warning("購入するにはログインが必要です。")

                    else:
                        try:
                            customer_id = get_or_create_stripe_customer(
                                supabase,
                                str(user.id),
                                user.email,
                            )

                            checkout_url = create_checkout_session(
                                customer_id=customer_id,
                                user_id=str(user.id),
                                price_id=st.secrets["stripe"]["monthly_price_id"],
                                success_url=f"{APP_BASE_URL}/?payment=success",
                                cancel_url=f"{APP_BASE_URL}/?payment=cancel",
                            )

                            st.success("決済ページの準備ができました！")

                            st.link_button(
                                "Stripeの決済画面へ進む",
                                checkout_url,
                                type="primary",
                                use_container_width=True,
                            )

                        except Exception:
                            import traceback
                            traceback.print_exc()
                            st.error("決済ページの作成に失敗しました。")

            # 年額プラン
            with col_y:
                st.markdown("### 年額プラン")
                st.markdown("**¥19,800 / 年**")
                st.caption("月額換算 ¥1,650・年間3,960円お得")

                if st.button(
                    "年額プランを選択",
                    key="yearly_checkout",
                    use_container_width=True,
                ):
                    user = st.session_state.get("user")

                    if user is None:
                        st.warning("購入するにはログインが必要です。")
                    else:
                        try:
                            customer_id = get_or_create_stripe_customer(
                                supabase,
                                str(user.id),
                                user.email,
                            )

                            checkout_url = create_checkout_session(
                                customer_id=customer_id,
                                user_id=str(user.id),
                                price_id=st.secrets["stripe"]["yearly_price_id"],
                                success_url=f"{APP_BASE_URL}/?payment=success",
                                cancel_url=f"{APP_BASE_URL}/?payment=cancel",
                            )

                            st.success("年間プランの決済ページを準備しました！")
                            st.link_button(
                                "Stripeの決済画面へ進む",
                                checkout_url,
                                type="primary",
                                use_container_width=True,
                            )

                        except Exception:
                            import traceback
                            traceback.print_exc()
                            st.error("年間プランの決済ページ作成に失敗しました。")
    # ---------------------------------------------------------
    # TAB 6: サポート & フィードバック
    # ---------------------------------------------------------
    with tab6:
        st.markdown(f"##### {t['tab_support']}")
        
        with st.expander("Q. 生成制限と更新のタイミングについて"):
            st.write("生成上限は毎日 00:00 (JST) に自動リセットされます。")

        with st.expander("Q. 解約・お支払いについて"):
            st.write("Stripe決済の確認メール、またはサポートへお問い合わせください。")

        st.divider()

        st.markdown(f"##### フィードバックの送信")
        with st.form(key="feedback_form"):
            category = st.selectbox("カテゴリー", ["機能改善要請", "システム不具合報告", "その他"])
            feedback_text = st.text_area("詳細内容", placeholder="改善案や不具合の内容を入力してください", height=150)
            submit_feedback = st.form_submit_button("SEND FEEDBACK")

        if submit_feedback:
            if not feedback_text:
                st.warning("内容を入力してください。")
            else:
                try:
                    fb_data = {
                        "user_id": st.session_state.user.id,
                        "user_email": st.session_state.user.email,
                        "category": category,
                        "content": feedback_text
                    }
                    supabase.table("feedbacks").insert(fb_data).execute()
                    st.success("フィードバックを正常に送信しました。")
                except Exception as e:
                    st.error(f"送信失敗: {e}")
