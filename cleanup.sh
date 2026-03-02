#!/bin/bash

# AI Diplomacy Simulation - Log Cleanup Utility
# 3ターン以下のシミュレーションログを自動的に削除します。

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."

cd "$PROJECT_ROOT"

if command -v python3 &> /dev/null
then
    python3 scripts/cleanup_logs.py
else
    echo "Error: python3 is not installed."
    exit 1
fi
