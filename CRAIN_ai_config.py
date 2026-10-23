# CRAIN AI Engine Configuration
# モデルは比較テスト後に確定する

AI_MODELS = {
    "free": "gpt-4o-mini",
    "premium": "gpt-4o-mini",
    "deep": "gpt-4o-mini",
}

GEMINI_MODELS = {
    "standard": "gemini-3.8-flash",
}

def get_ai_model(plan="free", mode="standard"):
    if plan == "premium":
        if mode == "deep":
            return AI_MODELS["deep"]
        return AI_MODELS["premium"]

    return AI_MODELS["free"]
# =====================================
# CRAIN AI Provider Configuration
# =====================================

AI_PROVIDERS = {
    "free": "openai",
    "premium": "gemini",
    "deep": "gemini",
}


def get_ai_provider(plan="free", mode="standard"):
    if plan == "premium" and mode == "deep":
        return AI_PROVIDERS["deep"]

    if plan == "premium":
        return AI_PROVIDERS["premium"]

    return AI_PROVIDERS["free"]


def get_gemini_model(mode="standard"):
    return GEMINI_MODELS["standard"]