"""
Ollama REST API クライアント
gemini-genai SDKと互換性のあるレスポンスオブジェクトを返す
"""

import json
import subprocess
import time
import requests
from dataclasses import dataclass
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential


OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass
class OllamaUsageMetadata:
    """google-genai互換のusage_metadataラッパー"""
    prompt_token_count: int = 0
    candidates_token_count: int = 0


@dataclass
class OllamaResponse:
    """google-genai互換のレスポンスラッパー"""
    text: str = ""
    usage_metadata: Optional[OllamaUsageMetadata] = None
    function_calls: None = None  # Ollama側ではtool callを使わない


def ensure_ollama_running() -> bool:
    """Ollamaが起動していなければ起動する。起動済みならTrueを返す。"""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            return True
    except requests.ConnectionError:
        pass

    print("🔄 Ollamaが起動していません。起動を試みます...")
    
    # ARM版Homebrew (Apple Silicon Metal GPU対応) を優先
    ollama_paths = [
        "/opt/homebrew/bin/ollama",  # ARM版 (Apple Silicon GPU対応)
        "ollama",                     # PATHから検索
    ]
    
    ollama_cmd = None
    for path in ollama_paths:
        try:
            result = subprocess.run([path, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0 or "Warning" in result.stderr.decode():
                ollama_cmd = path
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    
    if not ollama_cmd:
        print("❌ ollamaコマンドが見つかりません。Ollamaがインストールされていることを確認してください。")
        return False
    
    try:
        subprocess.Popen(
            f"OLLAMA_LOAD_TIMEOUT=15m nohup {ollama_cmd} serve > /tmp/ollama.log 2>&1 &",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 起動を待つ (最大30秒)
        for i in range(30):
            time.sleep(1)
            try:
                resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
                if resp.status_code == 200:
                    print(f"✅ Ollamaが正常に起動しました。({ollama_cmd})")
                    return True
            except requests.ConnectionError:
                continue
        print("⚠️ Ollamaの起動がタイムアウトしました。")
        return False
    except Exception as e:
        print(f"❌ Ollama起動エラー: {e}")
        return False


class OllamaClient:
    """Ollama REST APIを使用してテキスト生成を行うクライアント"""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, default_model: str = "mistral-small3.1:latest"):
        self.base_url = base_url
        self.default_model = default_model
        # 起動チェック
        if not ensure_ollama_running():
            raise ConnectionError("Ollamaサーバーに接続できません。")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def generate(
        self,
        prompt: str,
        model: str = None,
        temperature: float = 0.4,
        json_mode: bool = False,
    ) -> OllamaResponse:
        """
        Ollama REST APIを呼び出してテキストを生成する。
        ストリーミングモードで受信し、非ストリーミングの5分タイムアウトを回避。
        google-genai互換のOllamaResponseを返す。
        """
        target_model = model if model else self.default_model

        payload = {
            "model": target_model,
            "prompt": prompt,
            "stream": True,  # ストリーミングで5分タイムアウトを回避
            "options": {
                "temperature": temperature,
            },
        }

        if json_mode:
            payload["format"] = "json"

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=900,  # 15分タイムアウト（ストリーミングなので各チャンク間のタイムアウト）
            stream=True,
        )
        response.raise_for_status()

        # ストリーミングレスポンスを結合
        text_parts = []
        prompt_eval_count = 0
        eval_count = 0
        
        for line in response.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        text_parts.append(chunk["response"])
                    # 最終チャンク（done=true）にトークン使用量が含まれる
                    if chunk.get("done", False):
                        prompt_eval_count = chunk.get("prompt_eval_count", 0)
                        eval_count = chunk.get("eval_count", 0)
                except json.JSONDecodeError:
                    continue

        text = "".join(text_parts)

        usage = OllamaUsageMetadata(
            prompt_token_count=prompt_eval_count,
            candidates_token_count=eval_count,
        )

        return OllamaResponse(text=text, usage_metadata=usage)
