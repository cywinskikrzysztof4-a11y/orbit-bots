#!/usr/bin/env bash
set -e

echo "[Orbit Worker] Inicjalizacja środowiska GPU..."

export OLLAMA_HOST=127.0.0.1:11434
export HF_HOME=/workspace/hf
mkdir -p "$HF_HOME"

# 1. Uruchomienie Ollama w tle (tylko localhost!)
echo "[Orbit Worker] Uruchamianie Ollama (127.0.0.1:11434)..."
ollama serve > /var/log/ollama.log 2>&1 &

# Czekaj na start Ollamy
for i in {1..30}; do
    if curl -s http://127.0.0.1:11434/api/version > /dev/null; then
        echo "[Orbit Worker] Ollama działa."
        break
    fi
    sleep 1
done

# 2. Pobranie modelu Dolphin jeśli brak
echo "[Orbit Worker] Weryfikacja modelu dolphin3:8b..."
if ! ollama list | grep -q "dolphin3:8b"; then
    echo "[Orbit Worker] Pobieranie modelu dolphin3:8b..."
    ollama pull dolphin3:8b
fi

# 3. Wstępne pobranie modeli HF do pamięci podręcznej (dysk instancji >= 60 GB)
python3 -c "
import os
from huggingface_hub import snapshot_download
print('[Orbit Worker] Sprawdzanie modeli wideo HF...')
try:
    snapshot_download(repo_id='Wan-AI/Wan2.1-T2V-1.3B-Diffusers', local_dir_use_symlinks=False)
except Exception as e:
    print('[Orbit Worker] Informacja o pobieraniu Wan 2.1:', e)
" || true

# 4. Uruchomienie serwera FastAPI
echo "[Orbit Worker] Start serwera FastAPI na porcie 8000..."
exec uvicorn server:app --host 0.0.0.0 --port 8000
