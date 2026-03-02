from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

prompt = """あなたはアメリカに住む一般の国民です。
現在の自国の状況は以下の通りです：
- 政治体制: Democracy
- 経済状況: 25000.0
- 政府支持率: 55.0%
- 最近の世界的ニュース:
- シミュレーションが開始されました。世界のリーダーたちが行動を開始します。

**指示**:
現在の政府への支持率や経済状況、ニュースを踏まえ、あなたがSNSに投稿するであろう内容を5件作成してください。
支持率が低ければ不満や批判を、高ければ称賛や日常の平和を反映させてください。
1件あたり最大140文字程度で、リアルな国民の声を表現してください。
出力は以下のJSONリストフォーマットで厳密に返してください。

```json
{{
  "posts": [
    "投稿テキスト1",
    "投稿テキスト2"
  ]
}}
```
"""

try:
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    print("Success:")
    print(response.text)
except Exception as e:
    import traceback
    print("Error occurred!")
    print(e)
    traceback.print_exc()
