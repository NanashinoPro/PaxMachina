import os
import time
from google import genai
from google.genai import types

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key, http_options={'timeout': 1})

try:
    print("Sending...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello"
    )
    print("Success?", response.text)
except Exception as e:
    print("Caught Exception:", type(e).__name__, str(e))
