import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing")

client = genai.Client(api_key=api_key)

MODEL = "gemini-2.5-flash"


def ask_gemini(message, history="", language="English"):
    conversation = history.strip() or "(no earlier messages)"

    prompt = f"""You are SwasthyaAI, a multilingual health-awareness assistant.

Your role:
- Give clear, educational health information in plain language.
- Do NOT diagnose the user or name a specific condition they "have".
- Do NOT claim certainty about medical conditions.
- For serious, worsening, or emergency symptoms, tell the user to seek
  professional medical care promptly.
- Be warm, concise, and non-alarming. Use short paragraphs or bullet points.

Always reply in {language}.

Previous conversation:
{conversation}

User:
{message}
"""

    response = client.models.generate_content(model=MODEL, contents=prompt)

    return response.text
