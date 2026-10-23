import streamlit as st
from google import genai
from google.genai import types

from CRAIN_ai_config import get_gemini_model


def generate_with_gemini(prompt, mode="standard"):

    client = genai.Client(
        api_key=st.secrets["GEMINI_API_KEY"]
    )

    response = client.models.generate_content(
        model=get_gemini_model(mode),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8000,
        ),
    )

    if not response.text:
        raise RuntimeError("Geminiから文章が返されませんでした。")

    return response.text