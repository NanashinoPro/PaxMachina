import os
import glob
import json
import re
from pathlib import Path

def get_max_turn_from_jsonl(file_path):
    """.jsonlファイルの最終行からターン数を取得する"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if not lines:
                return 0
            last_line = lines[-1]
            data = json.loads(last_line)
            return data.get('turn', 0)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0

def get_max_turn_from_system_log(file_path):
    """system_*.logファイル内の '(ターン N)' から最大ターン数を取得する"""
    max_turn = 0
    try:
        content = Path(file_path).read_text(encoding='utf-8')
        # '(ターン 9)' や '│ 🌍 Turn 1 (2025年 Q1) │' などのパターンを探す
        turns = re.findall(r'\(ターン (\d+)\)', content)
        turns += re.findall(r'Turn (\d+)', content)
        if turns:
            max_turn = max(int(t) for t in turns)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return max_turn

def cleanup_logs(threshold=3):
    """指定したターン数以下のログファイルを削除する"""
    print(f"--- ログのクリーンアップを開始します (閾値: {threshold}ターン) ---")
    
    deleted_files = []
    
    # 1. シミュレーションログ (.jsonl, .summary.json)
    jsonl_files = glob.glob("logs/simulations/sim_*.jsonl")
    for jsonl_path in jsonl_files:
        max_turn = get_max_turn_from_jsonl(jsonl_path)
        if max_turn <= threshold:
            # 関連するファイルを特定
            base_path = jsonl_path.replace(".jsonl", "")
            summary_path = base_path + ".summary.json"
            
            # 削除
            for p in [jsonl_path, summary_path]:
                if os.path.exists(p):
                    os.remove(p)
                    deleted_files.append(p)
                    print(f"Deleted: {p} (Max Turn: {max_turn})")
                    
    # 2. システムログ (logs/system/system_*.log)
    system_logs = glob.glob("logs/system/system_*.log")
    for log_path in system_logs:
        max_turn = get_max_turn_from_system_log(log_path)
        if max_turn <= threshold:
            if os.path.exists(log_path):
                os.remove(log_path)
                deleted_files.append(log_path)
                print(f"Deleted: {log_path} (Max Turn: {max_turn})")

    if not deleted_files:
        print("削除対象のファイルは見つかりませんでした。")
    else:
        print(f"\n合計 {len(deleted_files)} 個のファイルを削除しました。")

if __name__ == "__main__":
    # デフォルトで3ターン以下のログを削除
    cleanup_logs(threshold=3)
