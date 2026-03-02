import os
import json
import argparse
import glob
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

SIM_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs", "simulations")

class SimulationSummary(BaseModel):
    summary: str = Field(description="シミュレーション全体を通した各国の動き、戦略の変遷、主要な出来事の定性的な要約。Markdown形式で記述してください。")

def generate_summary(log_filepath: str) -> str:
    """
    シミュレーションのJSONLログを読み込み、Geminiで要約を生成して保存する
    """
    if not os.path.exists(log_filepath):
        print(f"File not found: {log_filepath}")
        return

    summary_filepath = log_filepath.replace(".jsonl", ".summary.json")
    
    # すでに要約が存在する場合はスキップ（上書きしたい場合は要修正）
    if os.path.exists(summary_filepath):
        print(f"Summary already exists for {log_filepath}")
        return

    print(f"Generating summary for {log_filepath}...")
    
    turns = []
    with open(log_filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not turns:
        print("No valid turn data found.")
        return

    # 要約用のプロンプトを作成するためのデータを抽出
    # 全部のテキストを送ると長すぎる可能性があるが、80ターン程度ならGemini 2.5 Flashのコンテキストウィンドウに十分収まる
    # 抽出する要素: ターン数、各国の状況変化、ニュースイベント、エージェントの思考プロセス
    
    prompt_text = "以下は、AIエージェントによる国家間外交・内政シミュレーションの実行ログです。\n"
    prompt_text += "各ターンにおける、各国の思考プロセスと主要な出来事（ニュースイベント）が時系列で記録されています。\n\n"
    prompt_text += "【指示】\n"
    prompt_text += "シミュレーション全体を通して、各国がどのような戦略を取り、どのように動いたのかを分析し、全体を総括する定性的な要約を作成してください。\n"
    prompt_text += "・各国の初期戦略と途中の戦略変更（もしあれば）\n"
    prompt_text += "・主要な対立や協力、諜報活動の成果など\n"
    prompt_text += "・最終的な結果や情勢\n"
    prompt_text += "をわかりやすく、Markdown形式のテキストとして記述してください。\n\n"
    
    prompt_text += "【シミュレーションログ】\n"
    
    for t in turns:
        turn_num = t.get("turn")
        year = t.get("world_state", {}).get("year", t.get("state", {}).get("year"))
        quarter = t.get("world_state", {}).get("quarter", t.get("state", {}).get("quarter"))
        
        prompt_text += f"\n--- Turn {turn_num} ({year}年 Q{quarter}) ---\n"
        
        news = t.get("world_state", {}).get("news_events", t.get("state", {}).get("news_events", []))
        if news:
            prompt_text += "📰 ニュース・イベント:\n"
            for n in news:
                prompt_text += f"  - {n}\n"
                
        actions = t.get("actions", {})
        for country_name, action_data in actions.items():
            thought = action_data.get("thought_process", "")
            if thought:
                prompt_text += f"🧠 {country_name}の思考: {thought}\n"

    # Gemini APIの呼び出し
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is not set.")
        return

    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_text,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SimulationSummary,
                temperature=0.4
            ),
        )
        
        # 保存
        summary_data = json.loads(response.text)
        with open(summary_filepath, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
            
        print(f"Successfully generated summary and saved to {summary_filepath}")
        
    except Exception as e:
        print(f"Error generating summary: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate summary for simulation logs.")
    parser.add_argument("--all", action="store_true", help="Generate summary for all logs in logs/simulations/")
    parser.add_argument("--file", type=str, help="Generate summary for a specific log file")
    
    args = parser.parse_args()
    
    if args.all:
        if os.path.exists(SIM_LOG_DIR):
            for filename in os.listdir(SIM_LOG_DIR):
                if filename.endswith(".jsonl"):
                    filepath = os.path.join(SIM_LOG_DIR, filename)
                    generate_summary(filepath)
    elif args.file:
        generate_summary(args.file)
    else:
        print("Please specify --all or --file <filename>")
