import os
import subprocess
import requests
import json

def send_notification(title: str, message: str):
    """
    シミュレーション完了などの通知を送る。
    1. macOS システム通知
    2. Discord Webhook (DISCORD_WEBHOOK_URL環境変数がある場合)
    """
    # 1. macOS システム通知
    try:
        apple_script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", apple_script], check=True)
        print(f"macOS通知を送信しました: {title}")
    except Exception as e:
        print(f"macOS通知の送信に失敗しました: {e}")

    # 2. Discord Webhook
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try:
            payload = {
                "embeds": [
                    {
                        "title": title,
                        "description": message,
                        "color": 3447003 # Blue
                    }
                ]
            }
            response = requests.post(webhook_url, json=payload)
            response.raise_for_status()
        except Exception as e:
            print(f"Discordへの通知送信に失敗しました: {e}")

if __name__ == "__main__":
    # テスト用
    send_notification("AI外交シミュレーション", "通知システムのテスト出力です。")
