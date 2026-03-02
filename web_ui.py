import os
import json
from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
SIM_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs", "simulations")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/simulations")
def list_simulations():
    if not os.path.exists(SIM_LOG_DIR):
        return jsonify([])
    files = [f for f in os.listdir(SIM_LOG_DIR) if f.endswith(".jsonl")]
    files.sort(reverse=True)
    return jsonify(files)

@app.route("/api/simulations/<filename>")
def get_simulation(filename):
    filepath = os.path.join(SIM_LOG_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    turns = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return jsonify(turns)

@app.route("/api/simulations/<filename>/summary")
def get_simulation_summary(filename):
    summary_filename = filename.replace(".jsonl", ".summary.json")
    filepath = os.path.join(SIM_LOG_DIR, summary_filename)
    if not os.path.exists(filepath):
        return jsonify({"summary": ""}), 404
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/simulations/<filename>/chat", methods=["POST"])
def chat_about_simulation(filename):
    data = request.json
    user_query = data.get("query", "")
    
    if not user_query:
        return jsonify({"error": "Query is required"}), 400
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set on the server."}), 500
        
    log_filepath = os.path.join(SIM_LOG_DIR, filename)
    if not os.path.exists(log_filepath):
        return jsonify({"error": "Simulation file not found"}), 404

    # ログデータを読み込んでコンテキストを作成
    context = ""
    try:
        with open(log_filepath, "r", encoding="utf-8") as f:
            turn_count = 0
            for line in f:
                if line.strip():
                    try:
                        t = json.loads(line)
                        turn_count += 1
                        turn_num = t.get("turn")
                        year = t.get("world_state", {}).get("year", t.get("state", {}).get("year"))
                        quarter = t.get("world_state", {}).get("quarter", t.get("state", {}).get("quarter"))
                        
                        context += f"--- Turn {turn_num} ({year}年 Q{quarter}) ---\n"
                        news = t.get("world_state", {}).get("news_events", t.get("state", {}).get("news_events", []))
                        if news:
                            context += "ニュース:\n" + "\n".join(news) + "\n"
                        actions = t.get("actions", {})
                        for c_name, c_action in actions.items():
                            thought = c_action.get("thought_process", "")
                            if thought:
                                context += f"{c_name}の思考: {thought}\n"
                    except:
                        pass
    except Exception as e:
        return jsonify({"error": f"Failed to read logs: {str(e)}"}), 500

    prompt = f"以下はAI外交シミュレーションのログです。\n\n{context}\n\nこのシミュレーション内容に基づいて、以下のユーザーの質問に日本語で簡潔に答えてください。\nユーザーの質問: {user_query}"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": f"Gemini API Error: {str(e)}"}), 500

if __name__ == "__main__":
    print("🌍 AI Diplomacy Web Viewer を起動します: http://localhost:8081")
    app.run(host="0.0.0.0", port=8081, debug=True)
