"""Pętla keep-alive dla środowiska GitHub Codespaces.
Działa WYŁĄCZNIE gdy CODESPACES=true.
Dopóki liczba aktywnych zadań w tle (active) > 0, co ~4 min generuje aktywność
(wypisanie na terminal stdout z flushem + modyfikacja pliku w przestrzeni roboczej),
którą GitHub Codespaces liczy przeciw idle timeout (domyślnie 30 min).
Gdy active == 0, pętla nie generuje żadnej aktywności, pozwalając Codespace
na bezpieczne przejście w stan uśpienia.
"""
import os
import sys
import time
import threading
from datetime import datetime, timezone
from . import activity

DEFAULT_INTERVAL_SECONDS = 240  # ~4 minuty (domyślny idle timeout Codespaces to 30 min)

_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_ping_time: float = 0.0

def is_codespaces() -> bool:
    """Sprawdza, czy aplikacja działa w środowisku GitHub Codespaces."""
    return os.environ.get("CODESPACES", "").strip().lower() == "true"

def _generate_activity(active: int):
    """Generuje aktywność rozpoznawaną przez mechanizmy monitorowania Codespaces:
    1. Wypisanie danych na strumień terminala (stdout z wymuszeniem flush).
    2. Zapis/aktualizacja znacznika czasu w pliku przestrzeni roboczej (inotify/file watcher).
    3. Odświeżenie znacznika czasu w activity trackerze.
    """
    iso_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Terminal stdout (Codespaces monitoruje I/O konsoli)
    try:
        sys.stdout.write(f"[Codespaces keep-alive] {iso_now} | Zadania aktywne: {active} | Reset idle timeout\n")
        sys.stdout.flush()
    except Exception:
        pass

    # 2. Dotknięcie/aktualizacja pliku w katalogu roboczym (Codespaces inotify)
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(root_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        keepalive_file = os.path.join(data_dir, ".codespace_keepalive")
        with open(keepalive_file, "w", encoding="utf-8") as f:
            f.write(f"{iso_now} active={active}\n")
    except Exception:
        pass

    # 3. Odświeżenie activity w trackerze
    activity.record_activity()

def _keepalive_loop(interval: int):
    global _last_ping_time
    _last_ping_time = 0.0

    while not _stop_event.is_set():
        active = activity.get_active_count()
        now = time.time()

        if active > 0:
            if now - _last_ping_time >= interval:
                _last_ping_time = now
                _generate_activity(active)
        else:
            # Gdy 0 zadań — absolutna cisza, by po 30 min Codespace naturalnie zasnął
            pass

        # Czekamy w krótkich interwałach (1s lub ułamek interwału), by szybko reagować
        wait_step = min(float(interval) / 4.0, 1.0) if interval else 1.0
        _stop_event.wait(wait_step)

def start_keepalive(interval: int | None = None):
    """Uruchamia wątek keep-alive tylko gdy CODESPACES=true."""
    global _thread
    if not is_codespaces():
        # Poza Codespaces (np. na Renderze lub lokalnie) pętla nie jest uruchamiana
        return

    if _thread is not None and _thread.is_alive():
        return

    sec = interval or int(os.environ.get("CODESPACE_KEEPALIVE_INTERVAL", DEFAULT_INTERVAL_SECONDS))
    _stop_event.clear()
    _thread = threading.Thread(
        target=_keepalive_loop,
        args=(sec,),
        daemon=True,
        name="CodespaceKeepAlive"
    )
    _thread.start()
    print(f"[Orbit] Uruchomiono pętlę Codespaces keep-alive (interwał: {sec}s, tylko gdy active>0)")

def stop_keepalive():
    """Zatrzymuje wątek keep-alive."""
    global _thread
    _stop_event.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=2.0)
        _thread = None
