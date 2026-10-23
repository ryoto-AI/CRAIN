from CRAIN_ai_config import get_ai_model
from CRAIN_ai_config import get_ai_provider
from CRAIN_gemini import generate_with_gemini
from CRAIN_premium_engine_v23 import generate_premium_five_minute
import os
import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
import random
import base64
# PRODUCTION CANDIDATE: Restore the original Stripe integration unchanged.
from CRAIN_stripe import (
    create_checkout_session,
    get_or_create_stripe_customer,
    create_billing_portal_session,
)
import stripe

# The production quota RPC reads stripe_live_* columns exclusively.
# Fail closed if the app is accidentally started in Stripe test mode.
if st.secrets["stripe"].get("mode") != "live":
    st.error("本番候補はStripe LIVEモード専用です。公開設定を確認してください。")
    st.stop()

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
# Production Supabase connection. No staging keys are used.
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

_service_key = st.secrets["supabase"]["service_role_key"]
if not _service_key:
    st.error("Supabase管理者キーが設定されていません。")
    st.stop()
admin_supabase = create_client(SUPABASE_URL, _service_key)

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
    """Returns a UUID reservation id or None, never a boolean."""
    return supabase.rpc("crain_reserve_generation_v2", {}).execute().data


def _finalize(reservation_id, action):
    if admin_supabase is None:
        raise RuntimeError("service_role_key が未設定です")
    method = {"confirm": "crain_confirm_generation_v2", "refund": "crain_refund_generation_v2"}[action]
    return admin_supabase.rpc(method, {"p_reservation_id": str(reservation_id)}).execute().data


def refund_failed_generation(reservation_id):
    """Refund only when model generation failed before delivering content."""
    try:
        if _finalize(reservation_id, "refund") is True:
            st.warning("生成エラーのため利用回数を返還しました。")
        else:
            st.error("利用回数の返還状態が不明です。サポートへ連絡してください。")
    except Exception:
        st.error("返還処理に失敗しました。予約状態の確認が必要です。")


def confirm_completed_generation(reservation_id):
    """Confirm a delivered result. NEVER auto-refund if confirmation fails."""
    try:
        if _finalize(reservation_id, "confirm") is True:
            return True
    except Exception:
        pass
    st.error("結果は保持しましたが利用枠の確定を確認できません。返還せず管理者による確認が必要です。")
    return False
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
                        allowed = reserve_generation() if admin_supabase is not None else None
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
                    # CRAIN Creative Direction Engine
                            creative_direction = """
                            【CRAIN クリエイティブ設計エンジン】

                            台本を書く前に、以下の工程を内部で検討してください。

                            STEP 1：テーマ分析・情報深掘り設計
                            ・視聴者が最も知りたい核心的な疑問を1つ特定する。
                            ・その疑問に答えるために必要な情報を3〜5個選ぶ。
                            ・情報はジャンルに応じて、仕組み、原因、背景、実例、
                            比較、対立する説、具体的な使用場面などから選択する。
                            ・各情報について「何が起きるか」だけでなく、
                            「なぜ起きるか」「どのように起きるか」まで掘り下げる。
                            ・一般論の繰り返しではなく、視聴者が新しく知る内容を優先する。
                            ・ただし、情報を増やすために事実やデータを創作しない。
                            ・十分な根拠がない場合は断定せず、不確実性を明示する。
                            ・選んだ情報を、視聴者が理解しやすい順序に整理する。

                            STEP 2：構成設計
                            ・テーマに適した異なる構成案を検討する。
                            ・最も視聴者を引きつける構成を採用する。
                            ・ジャンルに応じて展開を変化させる。
                            ・冒頭で提示した疑問を本編で深掘りする。

                            STEP 3：脚本制作
                            ・抽象的な説明より具体的な事実や事例を優先する。
                            ・同じ内容を繰り返さない。
                            ・不自然な比喩やAI特有の決まり文句を避ける。
                            ・各段落に新しい情報や展開を含める。

                            STEP 4：品質確認
                            ・冒頭に視聴する理由があるか。
                            ・内容が薄くなっていないか。
                            ・ジャンルに合った表現になっているか。
                            ・文章が自然につながっているか。
                            ・結末が冒頭の疑問に対応しているか。

                            内部の検討過程は出力せず、完成した台本のみを出力してください。
                            """

                            prompt = f"""
                            {creative_direction}

                            あなたは世界トップクラスの映像脚本家、SNSマーケター、
                            ドキュメンタリー構成作家を兼ねるプロフェッショナルです。

                            あなたの目的は、単なる情報提供ではありません。
                            視聴者が思わず続きを見たくなる、独自性の高い動画台本を制作することです。

                            【基本情報】
                            プラットフォーム：{platform}
                            動画時間：{target_duration_selection}
                            ジャンル：{genre}
                            ターゲット：{target_audience}
                            話し方：{speaking_style}
                            テーマ：{topic}
                            追加指示：{extra_instructions}

                            【最重要ルール】

                            1. ジャンルに応じて動画構成を最適化してください。
                            すべての動画を同じ構成にしてはいけません。

                            2. 冒頭3秒で視聴者の好奇心を刺激してください。
                            ありきたりな挨拶や説明から始めないでください。

                            3. AI特有の不自然な表現を避けてください。
                            人間のプロ脚本家が執筆したような自然な文章にしてください。

                            4. 視聴者が続きを見たくなるように、
                            疑問、伏線、意外性、具体例を適切に使用してください。

                            5. 抽象的な説明だけで終わらせず、
                            具体的なエピソードや実例を取り入れてください。

                            6. 動画時間に適した十分な文章量を確保してください。
                            ナレーションは1分あたり250〜350文字を目安とします。
                            ただし、話し方や映像演出によって調整してください。

                            7. ジャンルごとに適切な表現方法を選択してください。

                            ・都市伝説：謎、証拠、矛盾、考察
                            ・科学：疑問、研究、実験、発見
                            ・自己啓発：共感、具体例、気づき、行動
                            ・ファッション：世界観、特徴、着用イメージ
                            ・商品紹介：課題、魅力、使用場面、購入判断
                            ・エンタメ：意外性、展開、感情の変化

                            上記は参考例です。
                            必ずしも固定された順番で使用する必要はありません。

                            8. 事実、仮説、噂を明確に区別してください。
                            存在しない研究やデータを創作してはいけません。

                            9. 最後まで視聴する価値を作ってください。
                            単に「フォローしてください」で終わらせず、
                            動画のテーマに合った印象的な結末を設計してください。

                            10. ユーザーの追加指示を最大限尊重してください。

                            【トレンド分析】
                            {trend_instruction}

                            【出力形式】

                            ■ 動画タイトル

                            ■ 企画コンセプト

                            ■ 冒頭のフック

                            ■ 本編台本
                            ナレーション、映像指示、テロップ指示を明確に区別してください。

                            ■ 結末

                            ■ 編集・演出のポイント

                            ■ CRAIN ALGORITHM & TREND ANALYSIS
                            トレンドに関する分析が可能な場合のみ記載してください。
                            実際に確認していない最新データを、確認済みの情報として扱わないでください。

                            【品質基準】
                            【ナレーションの長さ・時間厳守】
                            ・動画の指定時間に対して、ナレーション本文だけで十分な文字数を確保してください。
                            ・標準的な読み上げ速度は1分あたり300〜350文字を目安とします。
                            ・5分動画ならナレーション本文だけで1500〜1750文字を目標にしてください。
                            ・ナレーション以外のタイトル、テロップ、映像指示、分析文章は文字数に含めないでください。
                            ・各章のナレーション量は、その章に割り当てた時間に比例させてください。
                            ・内容を水増しするための繰り返しや、意味のない説明は避けてください。
                            ・指定時間に必要な情報量が不足する場合は、具体例、背景、比較、研究内容などを追加してください。ただし、未確認の事実を創作してはいけません。
                            【情報の信頼性・事実と仮説の区別】
                            ・歴史、科学、医学、事件など、事実の正確性が重要なジャンルでは、情報を「確認された事実」「仮説・噂」「演出・比喩」に区別してください。
                            ・事実として断定するのは、信頼できる根拠がある情報だけにしてください。
                            ・情報の出典を実際に確認できていない場合は、確認済みであるかのように表現しないでください。
                            ・研究者名、年代、数値、論文、研究結果、発言、引用を創作しないでください。
                            ・仮説や噂は積極的に紹介して構いません。ただし「〜という説があります」「〜と考える研究者もいます」など、未確定であることを明示してください。
                            ・科学的な測定結果と、その結果から推測される結論を混同しないでください。
                            ・一部の特徴が一致することを、仮説全体が証明された根拠として扱わないでください。
                            ・「完全に証明された」「絶対に不可能」「すべての研究者が認めた」などの強い断定は、十分な根拠がない限り避けてください。
                            ・比喩、擬人化、映画的な演出は積極的に使用してください。ただし、演出を歴史的事実として誤認させないでください。
                            ・未確認の情報を削除するだけでなく、確認できる事実、複数の仮説、未解決の論点を組み合わせ、面白さと情報量を維持してください。
                            ・外部資料を調査していない場合、調査済み・検証済み・最新データに基づく分析であると主張しないでください。
                            【強調テロップの生成ルール】
                            ・テロップはナレーション全文の字幕ではなく、視聴者に強く印象づけたい言葉を表示するためのものです。
                            ・ナレーションの各場面に対応する強調テロップを提案してください。
                            ・単なる章タイトルや内容の要約ではなく、視聴者の感情や好奇心を刺激する表現にしてください。
                            ・重要な数字、意外な事実、対立する仮説、印象的なセリフなどを優先してください。
                            ・原則として1つのテロップは5〜20文字程度とし、瞬時に読める長さにしてください。
                            ・各テロップには、表示するタイミングと対応するナレーションを明示してください。
                            ・重要な場面では、文字の大きさ、色、表示アニメーションなどの演出も提案してください。
                            ・事実と仮説を区別し、未確認の情報を断定的なテロップにしないでください。
                            ・すべての場面に無理やりテロップを入れる必要はありません。強調する価値がある場面を選んでください。
                            ・自然で独自性の高い表現
                            ・ジャンルに適した構成
                            【内容の具体性・情報密度】
                            ・抽象的な説明だけで終わらせず、視聴者が新しい知識や発見を得られる具体的な内容を盛り込んでください。
                            ・人物、出来事、背景、仕組み、研究方法、比較、具体例などから、テーマに適した情報を選んで深掘りしてください。
                            ・単に「研究された」「注目されている」と説明するのではなく、何を、どのように、なぜ調べたのかまで説明してください。
                            ・専門用語は原則として自然な説明を添え、初めて聞く視聴者にも理解できるようにしてください。
                            ・ただし、ユーザーが自由指示欄などで専門性や表現方法を指定した場合は、その指示を優先してください。
                            ・事実だけでなく、考察、仮説、独自の視点も積極的に取り入れ、知的好奇心を刺激してください。
                            ・具体性を高めるために、存在しない人物、研究、数値、発言、証拠を創作しないでください。
                            ・視聴維持を意識した展開
                            ・視聴者に価値を提供する内容

                            以上の条件に従い、完成度の高い動画台本を作成してください。
                            """

                            reservation_id = allowed
                            try:
                                if is_prem and target_duration_selection.startswith("5分"):
                                    fields = dict(platform=platform, genre=genre, topic=topic,
                                        target_audience=target_audience,
                                        speaking_style=speaking_style,
                                        extra_instructions=extra_instructions)
                                    generated_script = generate_premium_five_minute(
                                        openai_api_key,
                                        get_ai_model(plan="premium"), fields)
                                elif get_ai_provider("premium" if is_prem else "free") == "gemini":
                                    generated_script = generate_with_gemini(prompt)
                                else:
                                    response = client.chat.completions.create(
                                        model=get_ai_model(plan="premium" if is_prem else "free"),
                                        messages=[{"role": "user", "content": prompt}],
                                        temperature=0.7, max_completion_tokens=8000)
                                    generated_script = response.choices[0].message.content
                                if not generated_script or not generated_script.strip():
                                    raise RuntimeError("AIの生成結果が空です")
                            except Exception as e:
                                refund_failed_generation(reservation_id)
                                st.error(f"AI生成エラー: {type(e).__name__}")
                            else:
                                # Keep successful content regardless of quota confirmation/history errors.
                                st.session_state.last_generated_script = generated_script
                                st.session_state.last_topic_info = f"[{platform} / {target_duration_selection}] {topic}"
                                st.session_state.script_refine_left = 3 if is_prem else 1
                                if confirm_completed_generation(reservation_id):
                                    try:
                                        supabase.table("generation_history").insert({
                                            "user_id": st.session_state.user.id,
                                            "topic": st.session_state.last_topic_info,
                                            "script": generated_script}).execute()
                                    except Exception:
                                        st.warning("台本は完成しましたが履歴保存に失敗しました。結果は画面に保持しています。")
                                    else:
                                        st.rerun()

        # 出力結果
        if "last_generated_script" in st.session_state and st.session_state.last_generated_script:
            st.markdown("---")
            st.markdown("##### 出力結果")
            
            char_count = len(st.session_state.last_generated_script)
            est_seconds = int((char_count / 300) * 60)
            est_min = est_seconds // 60
            est_sec = est_seconds % 60
            st.caption(f"Volume: 約 {char_count}文字 ｜ Estimated Time: 約 {est_min}分 {est_sec}秒")

            st.text_area(
                "Script Output",
                value=st.session_state.last_generated_script,
                height=350,
                key=f"script_display_{hash(st.session_state.last_generated_script)}"
            )
            if st.button("💾 編集した台本を保存"):
                edited_script = st.session_state[
                    f"script_display_{hash(st.session_state.last_generated_script)}"
                ]

                if edited_script.strip():
                    st.session_state.last_generated_script = edited_script
                    try:
                        edited_data = {
                            "user_id": st.session_state.user.id,
                            "topic": f"{st.session_state.get('last_topic_info', '台本')} (Manually Edited)",
                            "script": edited_script
                        }

                        supabase.table("generation_history").insert(edited_data).execute()

                    except Exception as e:
                        st.error(f"履歴への保存に失敗しました: {e}")
                    else:
                        st.success("編集した台本を保存しました！")
                        st.rerun()
                else:
                    st.warning("台本が空になっています。")
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
                            if get_ai_provider("premium" if is_prem else "free") == "gemini":
                                fixed_script = generate_with_gemini(fix_prompt)
                            else:
                                res_fix = client.chat.completions.create(
                                    model=get_ai_model(
                                        plan="premium" if is_prem else "free"
                                    ),
                                    messages=[{"role": "user", "content": fix_prompt}],
                                    temperature=0.7,
                                )
                                fixed_script = res_fix.choices[0].message.content
                            print("【修正結果の冒頭】", repr(fixed_script[:300]))
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
                    allowed = reserve_generation() if admin_supabase is not None else None
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
                        reservation_id = allowed
                        try:
                            response = client.chat.completions.create(
                                model="gpt-4o-mini",
                                messages=[{"role": "user", "content": idea_prompt}],
                                temperature=0.8)
                            generated_ideas = response.choices[0].message.content
                            if not generated_ideas or not generated_ideas.strip():
                                raise RuntimeError("AIの生成結果が空です")
                        except Exception as e:
                            refund_failed_generation(reservation_id)
                            st.error(f"企画生成エラー: {type(e).__name__}")
                        else:
                            st.session_state.last_generated_ideas = generated_ideas
                            st.session_state.last_idea_genre = idea_genre
                            st.session_state.idea_refine_left = 3 if is_prem else 1
                            if confirm_completed_generation(reservation_id):
                                st.rerun()

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
                            if st.button("✏️ この台本を再編集する", key=f"edit_history_{item['id']}"):
                                st.session_state.last_generated_script = item.get("script", "")
                                st.session_state.last_topic_info = item.get("topic", "履歴から再編集")
                                st.rerun()
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