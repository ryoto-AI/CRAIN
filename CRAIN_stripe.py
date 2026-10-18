import stripe
import streamlit as st
from supabase import create_client

# 決済環境の切り替え（初期設定はテスト環境）
STRIPE_MODE = st.secrets["stripe"].get("mode", "test")

if STRIPE_MODE not in ("test", "live"):
    raise ValueError("Stripe mode must be 'test' or 'live'")

stripe.api_key = st.secrets["stripe"]["secret_key"]

# 使用中のStripe環境を確認
if STRIPE_MODE == "live" and not stripe.api_key.startswith(("sk_live_", "rk_live_")):
    raise ValueError("本番モードには本番用Stripeキーが必要です")

if STRIPE_MODE == "test" and not stripe.api_key.startswith(("sk_test_", "rk_test_")):
    raise ValueError("テストモードにはテスト用Stripeキーが必要です")

# Stripe決済管理専用のSupabaseクライアント
admin_supabase = create_client(
    st.secrets["supabase"]["url"],
    st.secrets["supabase_admin"]["service_role_key"],
)

def create_checkout_session(
    customer_id,
    user_id,
    price_id,
    success_url,
    cancel_url,
):
    """Stripeのサブスクリプション決済画面を作成する"""

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user_id,
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "supabase_user_id": user_id,
        },
        subscription_data={
            "metadata": {
                "supabase_user_id": user_id,
            }
        },
    )

    return session.url
def get_or_create_stripe_customer(supabase, user_id, email):
    """Stripe環境に応じた顧客を取得・作成する"""

    customer_column = (
        "stripe_live_customer_id"
        if STRIPE_MODE == "live"
        else "stripe_customer_id"
    )

    result = (
        admin_supabase.table("subscriptions")
        .select(customer_column)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if result.data:
        customer_id = result.data[0].get(customer_column)

        if customer_id:
            try:
                stripe.Customer.retrieve(customer_id)
                return customer_id
            except stripe.error.InvalidRequestError as e:
                if e.code != "resource_missing":
                    raise

    customer = stripe.Customer.create(
        email=email,
        metadata={"supabase_user_id": user_id},
        idempotency_key=f"crain-{STRIPE_MODE}-customer-{user_id}",
    )

    admin_supabase.table("subscriptions").upsert(
        {
            "user_id": user_id,
            customer_column: customer.id,
        },
        on_conflict="user_id",
    ).execute()

    return customer.id
def create_billing_portal_session(customer_id, return_url):
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )

    return session.url