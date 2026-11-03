"""Wspólny interfejs LLM. Faza 1: Gemini (darmowy klucz z pliku) lub brak LLM. Faza 2: Ollama/Dolphin (OpenAI-compatible)."""
import requests
from . import config, gemini, vault
def backend():
    if config.PHASE2_OLLAMA: return "ollama"
    return "gemini" if gemini.available() else "none"
def chat(messages, system=None, temperature=0.3):
    b = backend()
    if b == "ollama":
        tok = vault.secret("worker", "token", "WORKER_TOKEN") or "ollama"
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        r = requests.post(config.OLLAMA_BASE.rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + tok},
                          json={"model": config.OLLAMA_MODEL, "messages": msgs, "temperature": temperature}, timeout=180)
        r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
    if b == "gemini":
        return gemini.generate("\n".join(f'{m["role"]}: {m["content"]}' for m in messages), system)
    return None
