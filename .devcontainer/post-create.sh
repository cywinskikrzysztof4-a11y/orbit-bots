#!/usr/bin/env bash
# Jednorazowo przy tworzeniu Codespace: Ollama + zależności Pythona + Chromium dla Playwright.
set -euo pipefail
curl -fsSL https://ollama.com/install.sh | sh
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium || echo "UWAGA: instalacja Chromium nie powiodła się (narzędzia przeglądarki nie zadziałają)"
mkdir -p data
