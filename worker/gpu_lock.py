"""Zarządzanie pamięcią GPU i blokadami (GPU Lock).
Pozwala na jedno zadanie GPU naraz.
Przed generowaniem wideo:
1. Zwalnia model LLM z pamięci VRAM (keep_alive=0 do Ollama).
2. Czeka, aż ollama ps będzie puste.
Po wideo:
1. Usuwa instancję potoku diffusers (del pipe).
2. Czyści pamięć CUDA: torch.cuda.empty_cache().
"""
import os, time, threading, requests

OLLAMA_API = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "dolphin3:8b")

class GPULock:
    def __init__(self, http_client=requests):
        self.http = http_client
        self._cond = threading.Condition()
        self._is_video_running = False
        self._active_chats = 0

    def unload_ollama(self, model=OLLAMA_MODEL, timeout=5):
        """Wysyła polecenie keep_alive=0 do Ollama, aby zwolnić pamięć VRAM."""
        try:
            r = self.http.post(
                f"{OLLAMA_API}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=timeout
            )
            r.raise_for_status()
        except Exception:
            pass

        start = time.time()
        while time.time() - start < timeout:
            try:
                ps = self.http.get(f"{OLLAMA_API}/api/ps", timeout=2)
                if ps.status_code == 200:
                    models = ps.json().get("models", [])
                    if not models:
                        break
            except Exception:
                break
            time.sleep(0.1)

    def acquire_for_video(self):
        """Przed wideo: czeka na zwolnienie GPU, blokuje i zwalnia Ollamę."""
        with self._cond:
            while self._is_video_running or self._active_chats > 0:
                self._cond.wait(0.05)
            self._is_video_running = True

        self.unload_ollama()

    def release_from_video(self, pipe=None):
        """Po wideo: usuwa potok i czyści cache pamięci CUDA."""
        if pipe is not None:
            del pipe
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, Exception):
            pass

        with self._cond:
            self._is_video_running = False
            self._cond.notify_all()

    def acquire_for_chat(self):
        """Przed czatem: czeka jeśli trwa generowanie wideo."""
        with self._cond:
            while self._is_video_running:
                self._cond.wait(0.05)
            self._active_chats += 1

    def release_from_chat(self):
        """Po czacie: dekrementacja licznika."""
        with self._cond:
            if self._active_chats > 0:
                self._active_chats -= 1
            self._cond.notify_all()

gpu_lock = GPULock()
