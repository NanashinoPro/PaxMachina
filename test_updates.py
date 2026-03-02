import sys
import json
import glob
import os
import subprocess

def run_test():
    print("Running 3-turn simulation...")
    result = subprocess.run([sys.executable, "main.py", "--turns", "3"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Simulation failed to run.")
        print(result.stderr)
        sys.exit(1)
        
    print("Simulation completed. Verifying results...")
    
    # Get the latest simulation log file
    log_files = glob.glob("logs/simulations/sim_*.jsonl")
    if not log_files:
        print("No simulation log files found.")
        sys.exit(1)
        
    latest_log = max(log_files, key=os.path.getctime)
    print(f"Checking log file: {latest_log}")
    
    with open(latest_log, "r") as f:
        lines = f.readlines()
        
    if not lines:
        print("Log file is empty.")
        sys.exit(1)
        
    # Check turn 1 for initial trade agreement
    try:
        turn1_state = json.loads(lines[0])
        active_trades = turn1_state["world_state"].get("active_trades", [])
        
        has_initial_trade = False
        for trade in active_trades:
            if (trade.get("country_a") == "アメリカ" and trade.get("country_b") == "中国") or \
               (trade.get("country_a") == "中国" and trade.get("country_b") == "アメリカ"):
                has_initial_trade = True
                break
                
        if not has_initial_trade:
            print("ERROR: Initial trade agreement not found in Turn 1.")
            sys.exit(1)
        else:
            print("SUCCESS: Initial trade agreement verified.")
            
    except Exception as e:
        print(f"Error reading Turn 1: {e}")
        sys.exit(1)
        
    # Check for summits and forbidden phrases
    forbidden_phrases = ["ワーキンググループ", "専門家会議", "委員会", "協議会", "作業部会"]
    found_summit = False
    summit_violation = False
    
    for line in lines:
        state = json.loads(line)
        summit_logs = state["world_state"].get("summit_logs", [])
        for log in summit_logs:
            found_summit = True
            log_text = log.get("log", "")
            
            # Extract only the summary part if possible, or check the whole log slightly
            # The summary contains the conclusion
            summary_start = log_text.find("【最終結果】")
            text_to_check = log_text[summary_start:] if summary_start != -1 else log_text
            
            for phrase in forbidden_phrases:
                if phrase in text_to_check:
                    print(f"ERROR: Found forbidden phrase '{phrase}' in summit log.")
                    print(text_to_check)
                    summit_violation = True
                    
    if not found_summit:
        print("WARNING: No summits occurred during the 3 turns to verify committee constraints.")
        print("Consider running again or forcing a summit.")
    elif summit_violation:
        sys.exit(1)
    else:
        print("SUCCESS: No forbidden phrases found in summits.")
        
    print("All automated tests passed successfully!")

if __name__ == "__main__":
    run_test()
