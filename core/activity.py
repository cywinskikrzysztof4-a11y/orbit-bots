"""Śledzenie aktywności i zadań w tle (thread-safe).
Udostępnia licznik aktywnych zadań, stan kolejki oraz znacznik ostatniej aktywności.
"""
import time
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

class ActivityTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._active_tasks: dict[str, dict] = {}
        self._last_activity: float = time.time()

    def start_task(self, name: str = "task") -> str:
        """Rejestruje rozpoczęcie zadania w tle i aktualizuje znacznik aktywności."""
        tid = f"{name}-{uuid.uuid4().hex[:6]}"
        with self._lock:
            self._active_tasks[tid] = {
                "id": tid,
                "name": name,
                "started_at": time.time()
            }
            self._last_activity = time.time()
        return tid

    def finish_task(self, task_id: str):
        """Rejestruje zakończenie zadania w tle i aktualizuje znacznik aktywności."""
        with self._lock:
            self._active_tasks.pop(task_id, None)
            self._last_activity = time.time()

    @contextmanager
    def track_task(self, name: str = "task"):
        """Menedżer kontekstu do bezpiecznego zliczania aktywnych zadań."""
        tid = self.start_task(name)
        try:
            yield tid
        finally:
            self.finish_task(tid)

    def get_active_count(self) -> int:
        """Zwraca bieżącą liczbę aktywnych zadań w tle."""
        with self._lock:
            return len(self._active_tasks)

    def get_active_tasks(self) -> list[dict]:
        """Zwraca kopię listy aktualnie trwających zadań."""
        with self._lock:
            return list(self._active_tasks.values())

    def record_activity(self):
        """Ręcznie odświeża znacznik ostatniej aktywności."""
        with self._lock:
            self._last_activity = time.time()

    def get_last_activity_time(self) -> float:
        """Zwraca timestamp ostatniej aktywności w sekundach."""
        with self._lock:
            return self._last_activity

    def get_last_activity_iso(self) -> str:
        """Zwraca znacznik ostatniej aktywności w formacie ISO 8601 (UTC)."""
        with self._lock:
            dt = datetime.fromtimestamp(self._last_activity, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def get_busy_status(self) -> dict:
        """Zwraca słownik statusu obciążenia dla endpointu /api/health/busy."""
        # Dynamiczny import kolejki, aby uniknąć cyklicznych zależności
        try:
            from . import queue
            queued = queue.count_queued()
        except Exception:
            queued = 0

        active = self.get_active_count()
        last_activity = self.get_last_activity_iso()

        return {
            "active": active,
            "queued": queued,
            "last_activity": last_activity
        }

# Globalna instancja trackera zadań
tracker = ActivityTracker()

# Skróty funkcyjne dla wygody importu
start_task = tracker.start_task
finish_task = tracker.finish_task
track_task = tracker.track_task
get_active_count = tracker.get_active_count
get_active_tasks = tracker.get_active_tasks
record_activity = tracker.record_activity
get_last_activity_iso = tracker.get_last_activity_iso
get_busy_status = tracker.get_busy_status
