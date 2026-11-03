"""Klient darmowego Gemini API. Klucz czytany z pliku, nigdy nie logowany."""
import os, requests
KEY_FILE = os.environ.get("GEMINI_KEY_FILE", "/workspace/monitor-polityczny/.gemini_key")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
def available(): return bool(os.environ.get("GEMINI_API_KEY")) or os.path.exists(KEY_FILE)
def _key(): return os.environ.get("GEMINI_API_KEY") or open(KEY_FILE).read().strip()
def generate(prompt, system=None, timeout=90):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system: body["system_instruction"] = {"parts": [{"text": system}]}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                      headers={"x-goog-api-key": _key()}, json=body, timeout=timeout)
    if r.status_code != 200: raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
