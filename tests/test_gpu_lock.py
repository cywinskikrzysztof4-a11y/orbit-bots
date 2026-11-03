"""Test akceptacyjny 6:
Lock GPU (mock): zadanie wideo najpierw wywołuje keep_alive=0,
czat i wideo nigdy nie biegną równocześnie.
"""
import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from gpu_lock import GPULock

class MockOllamaHttp:
    def __init__(self):
        self.calls = []
        self.loaded_models = ["dolphin3:8b"]

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        if json and json.get("keep_alive") == 0:
            self.loaded_models = []
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"response": "ok"}
        return R()

    def get(self, url, timeout=None):
        self.calls.append(("GET", url, None))
        models = [{"name": m} for m in self.loaded_models]
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"models": models}
        return R()

def test_video_calls_keep_alive_zero():
    mock_http = MockOllamaHttp()
    lock = GPULock(http_client=mock_http)

    # Przed generowaniem wideo zwalniamy pamięć Ollama
    lock.acquire_for_video()
    try:
        # Sprawdź czy poszło zapytanie POST z keep_alive: 0
        keep_alive_calls = [
            c for c in mock_http.calls
            if c[0] == "POST" and c[2] and c[2].get("keep_alive") == 0
        ]
        assert len(keep_alive_calls) > 0, "Brak wywołania keep_alive=0 przed generowaniem wideo!"
        assert keep_alive_calls[0][2]["model"] == "dolphin3:8b"
    finally:
        lock.release_from_video()

def test_video_and_chat_never_run_concurrently():
    mock_http = MockOllamaHttp()
    lock = GPULock(http_client=mock_http)

    execution_log = []
    active_states = []

    def run_video():
        lock.acquire_for_video()
        execution_log.append("video_start")
        active_states.append(("video", True))
        time.sleep(0.3)
        execution_log.append("video_end")
        active_states.append(("video", False))
        lock.release_from_video()

    def run_chat():
        time.sleep(0.05)  # poczekaj aż wideo przejmie lock
        lock.acquire_for_chat()
        execution_log.append("chat_start")
        active_states.append(("chat", True))
        time.sleep(0.1)
        execution_log.append("chat_end")
        active_states.append(("chat", False))
        lock.release_from_chat()

    t_video = threading.Thread(target=run_video)
    t_chat = threading.Thread(target=run_chat)

    t_video.start()
    t_chat.start()

    t_video.join()
    t_chat.join()

    # Czat nie może wystartować przed zakończeniem wideo
    video_start_idx = execution_log.index("video_start")
    video_end_idx = execution_log.index("video_end")
    chat_start_idx = execution_log.index("chat_start")

    assert video_start_idx < video_end_idx < chat_start_idx, \
        f"Czat i wideo wystartowały współbieżnie! Kolejność zdarzeń: {execution_log}"
