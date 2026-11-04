import os
import time
import threading
import pytest
from fastapi.testclient import TestClient

from app import app
from core import activity, keepalive, queue, scheduler

def test_activity_tracker_basics():
    # Początkowo może być 0 zadań
    initial_active = activity.get_active_count()
    assert initial_active == 0

    with activity.track_task("test_job_1"):
        assert activity.get_active_count() == 1
        with activity.track_task("test_job_2"):
            assert activity.get_active_count() == 2
        assert activity.get_active_count() == 1

    assert activity.get_active_count() == 0

def test_activity_tracker_thread_safety():
    """Weryfikacja thread-safe licznika przy wielu równoległych wątkach."""
    errors = []

    def worker():
        try:
            for _ in range(50):
                with activity.track_task("concurrent_task"):
                    time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert activity.get_active_count() == 0

def test_get_busy_status_format():
    status = activity.get_busy_status()
    assert "active" in status
    assert "queued" in status
    assert "last_activity" in status
    assert isinstance(status["active"], int)
    assert isinstance(status["queued"], int)
    assert isinstance(status["last_activity"], str)
    # Sprawdzenie formatu ISO 8601 (np. 2026-11-04T12:00:00Z)
    assert "T" in status["last_activity"]
    assert status["last_activity"].endswith("Z")

def test_get_health_busy_endpoint():
    client = TestClient(app)
    r = client.get("/api/health/busy")
    assert r.status_code == 200
    data = r.json()
    assert "active" in data
    assert "queued" in data
    assert "last_activity" in data
    assert data["active"] == 0

def test_keepalive_codespaces_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CODESPACES", raising=False)
    assert not keepalive.is_codespaces()

    keepalive.start_keepalive(interval=1)
    # Wątek nie powinien wystartować poza Codespaces
    assert keepalive._thread is None or not keepalive._thread.is_alive()

def test_keepalive_codespaces_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESPACES", "true")
    assert keepalive.is_codespaces()

    # Zastąp generowanie aktywności zliczaniem wywołań
    calls = []
    original_gen = keepalive._generate_activity

    def mock_gen(active):
        calls.append(active)
        original_gen(active)

    monkeypatch.setattr(keepalive, "_generate_activity", mock_gen)

    # Przy 0 zadań aktywność NIE powinna być generowana
    keepalive.start_keepalive(interval=1)
    time.sleep(0.5)
    assert len(calls) == 0, "Gdy active=0, keepalive nie może generować aktywności"

    # Gdy active > 0, aktywność powinna zostać wygenerowana
    with activity.track_task("long_task"):
        time.sleep(1.2)
        assert len(calls) >= 1
        assert calls[0] >= 1

    keepalive.stop_keepalive()

def test_run_scheduled_endpoint_auth(monkeypatch):
    client = TestClient(app)

    # 1. Brak tokena w env -> 500
    monkeypatch.delenv("CODESPACE_PAT", raising=False)
    monkeypatch.delenv("ORBIT_JOB_TOKEN", raising=False)
    monkeypatch.delenv("ORBIT_PANEL_PASSWORD", raising=False)
    r = client.post("/api/jobs/run-scheduled")
    assert r.status_code == 500

    # 2. Ustawiamy sekretny token w env
    test_token = "secret_pat_test_123"
    monkeypatch.setenv("CODESPACE_PAT", test_token)

    # Brak nagłówka autoryzacji -> 401
    r = client.post("/api/jobs/run-scheduled")
    assert r.status_code == 401

    # Błędny token -> 401
    r = client.post("/api/jobs/run-scheduled", headers={"Authorization": "Bearer wrong_token"})
    assert r.status_code == 401

    # Poprawny token przez Bearer -> 200
    r = client.post("/api/jobs/run-scheduled", headers={"Authorization": f"Bearer {test_token}"})
    assert r.status_code == 200
    res = r.json()
    assert res["ok"] is True
    assert "status" in res

    # Poprawny token przez X-Orbit-Token -> 200
    r = client.post("/api/jobs/run-scheduled", headers={"X-Orbit-Token": test_token})
    assert r.status_code == 200

    # Poprawny token przez X-Github-Token -> 200
    r = client.post("/api/jobs/run-scheduled", headers={"X-Github-Token": test_token})
    assert r.status_code == 200

    # Poprawny token w Query param -> 200
    r = client.post(f"/api/jobs/run-scheduled?token={test_token}")
    assert r.status_code == 200

    # Poprawny token w ciele JSON -> 200
    r = client.post("/api/jobs/run-scheduled", json={"token": test_token})
    assert r.status_code == 200

def test_run_scheduled_sync_execution(monkeypatch):
    client = TestClient(app)
    test_token = "my_pat"
    monkeypatch.setenv("CODESPACE_PAT", test_token)

    # Wywołanie z wait=true
    r = client.post(f"/api/jobs/run-scheduled?token={test_token}&wait=true")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "completed"
    assert "results" in data

def test_queue_tracks_active_and_queued():
    job_executed = threading.Event()
    active_in_job = []

    def mock_handler(jid, payload):
        active_in_job.append(activity.get_active_count())
        job_executed.set()
        return {"status": "ok"}

    queue.register_handler("test_bot", "test_kind", mock_handler)
    job_id = queue.enqueue("test_bot", "test_kind", {"msg": "hello"})

    # Bezpośrednio po enqueue zadanie powinno być w stanie queued
    busy = activity.get_busy_status()
    assert busy["queued"] >= 1

    # Wykonaj zadanie
    queue._process_one_job()
    assert job_executed.is_set()
    assert len(active_in_job) == 1
    assert active_in_job[0] >= 1  # w trakcie wykonania active > 0
    assert activity.get_active_count() == 0  # po zakończeniu active wraca do 0

def test_scheduler_tracks_active():
    active_in_sched = []

    def mock_job():
        active_in_sched.append(activity.get_active_count())
        return "done"

    test_sched = scheduler.Scheduler()
    test_sched.add("test_bot", "job_x", 100, mock_job)
    test_sched.run_now("test_bot", "job_x")

    assert len(active_in_sched) == 1
    assert active_in_sched[0] >= 1
    assert activity.get_active_count() == 0

