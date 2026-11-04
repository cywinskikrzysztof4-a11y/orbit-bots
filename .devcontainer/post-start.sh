#!/usr/bin/env bash
# Przy każdym starcie Codespace: ollama serve w tle, pobranie modeli, start Orbit.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
if ! pgrep -x ollama >/dev/null; then
  nohup ollama serve > /tmp/ollama.log 2>&1 &
fi
for i in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null && break; sleep 1; done
# Pobieranie modeli (pierwszy raz kilka GB, potem z cache) i start aplikacji - w tle, by nie blokować edytora.
nohup bash -c '
  ollama pull "${ORBIT_SMALL_MODEL:-qwen3:4b}"
  ollama pull "${LLM_MODEL:-dolphin3:8b}"
' > /tmp/ollama-pull.log 2>&1 &
if ! pgrep -f "uvicorn app:app" >/dev/null; then
  nohup uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" > /tmp/orbit.log 2>&1 &
fi
echo "Orbit: port ${PORT:-8000} | logi: /tmp/orbit.log, /tmp/ollama.log, /tmp/ollama-pull.log"
