import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def search_historical_events(query: str) -> str:
    """Search for historical events in the database."""
    return "Dummy data"

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
try:
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents="日本の100年前の事件を教えて",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            tools=[search_historical_events],
            temperature=0.4
        )
    )
    print("Success:", response.text)
    if response.function_calls:
        for f in response.function_calls:
            print(f"Tool Call: {f.name}, args={f.args}")
except Exception as e:
    import traceback
    traceback.print_exc()
