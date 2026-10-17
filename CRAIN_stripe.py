import stripe
import streamlit as st
from supabase import create_client

stripe.api_key = st.secrets["stripe"]["secret_key"]

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
    """Supabaseユーザーに紐づくStripe顧客を取得・作成する"""

    result = (
        admin_supabase.table("subscriptions")
        .select("stripe_customer_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if result is None:
        raise RuntimeError(
            "Supabaseの検索結果がNoneです。execute()の処理を確認してください。"
        )

    if result.data:
        existing_customer_id = result.data[0].get("stripe_customer_id")

        if existing_customer_id:
            return existing_customer_id

    # Stripeに新しい顧客を作成
    customer = stripe.Customer.create(
        email=email,
        metadata={"supabase_user_id": user_id},
        idempotency_key=f"crain-customer-{user_id}",
    )

    # Supabaseに顧客IDを保存
    admin_supabase.table("subscriptions").upsert(
        {
            "user_id": user_id,
            "stripe_customer_id": customer.id,
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