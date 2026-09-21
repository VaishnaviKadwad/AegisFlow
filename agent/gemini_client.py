import os

from dotenv import load_dotenv
from google import genai


load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY is not set")

client = genai.Client(api_key=api_key)


def ask_gemini(prompt: str) -> str:
    response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
)
    

    return response.text


if __name__ == "__main__":
    result = ask_gemini(
        "Reply with exactly: AEGISFLOW_OK"
    )

    print(result)