"""Flagi konfiguracji (env). Faza 1 = darmowe źródła; Faza 2 = modele open-source na Vast (domyślnie WYŁĄCZONE)."""
import os
def flag(n, d="0"): return os.environ.get(n, d).lower() in ("1", "true", "yes", "on")
PHASE2_OLLAMA = flag("ORBIT_USE_OLLAMA")          # bot dzienny -> Dolphin przez Ollama
PHASE2_LOCAL_VIDEO = flag("ORBIT_USE_LOCAL_VIDEO") # bot wideo -> worker GPU (Wan/LTX diffusers)
OLLAMA_BASE = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.environ.get("OPENAI_MODEL", "dolphin3:8b")
WORKER_URL = os.environ.get("ORBIT_WORKER_URL", "")   # albo sejf 'worker' {url, token}
PORT = int(os.environ.get("PORT", "5003"))
VAST_IDLE_MIN = int(os.environ.get("VAST_IDLE_MIN", "10"))
