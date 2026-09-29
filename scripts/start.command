#!/usr/bin/env bash
# macOS: ダブルクリックで起動(初回は chmod +x が必要: chmod +x scripts/*.command scripts/*.sh)
cd "$(dirname "$0")/.." || exit 1
exec bash scripts/start.sh
