"""Test akceptacyjny 5:
Kontroler Vast (mock API): kolejka z zadaniem GPU daje start, a 10 min bez zadań daje stop.
Nigdy nie ma destroy ani create.
"""
import time, os
from core.vast import VastController
import core.config as config

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

class MockVastHttp:
    def __init__(self):
        self.calls = []
        self.instance_state = "stopped"

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        return MockResponse({
            "instances": [{
                "actual_status": self.instance_state,
                "dph_total": 0.12,
                "id": 12345
            }]
        })

    def put(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PUT", url, json))
        if json and "state" in json:
            self.instance_state = json["state"]
        return MockResponse({"success": True})

    def delete(self, url, headers=None, timeout=None):
        self.calls.append(("DELETE", url, None))
        raise AssertionError("ZABRONIONE: Kontroler wywołał metodę DELETE (destroy)!")

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        raise AssertionError("ZABRONIONE: Kontroler wywołał metodę POST (create)!")

def test_vast_controller_start_and_idle_stop(monkeypatch):
    mock_http = MockVastHttp()
    ctrl = VastController(http=mock_http)

    # Włącz flagi i konfigurację
    monkeypatch.setattr(config, "PHASE2_LOCAL_VIDEO", True)
    monkeypatch.setattr(ctrl, "key", lambda: "mock-vast-key-123")
    monkeypatch.setattr(ctrl, "instance", lambda: "12345")

    assert ctrl.enabled() is True

    # 1. Kolejka ma zadanie GPU, a instancja jest zatrzymana -> POWINNO URUCHOMIĆ INSTANCJĘ (start)
    action1 = ctrl.tick(gpu_jobs_pending=1, running=False)
    assert action1 == "running"
    assert mock_http.instance_state == "running"
    # Sprawdź czy był PUT ze state: running
    assert ("PUT", "https://console.vast.ai/api/v0/instances/12345/", {"state": "running"}) in mock_http.calls

    # 2. Instancja działa, są zadania -> nic nie zmienia
    action2 = ctrl.tick(gpu_jobs_pending=1, running=True)
    assert action2 is None

    # 3. Brak zadań przez krótki czas (< 10 min) -> nic nie zmienia
    ctrl.last_gpu_job = time.time() - 300  # 5 min temu
    action3 = ctrl.tick(gpu_jobs_pending=0, running=True)
    assert action3 is None
    assert mock_http.instance_state == "running"

    # 4. Brak zadań GPU przez > 10 min (np. 650 s) -> POWINNO ZATRZYMAĆ INSTANCJĘ (stop)
    ctrl.last_gpu_job = time.time() - 650  # > 10 minut
    action4 = ctrl.tick(gpu_jobs_pending=0, running=True)
    assert action4 == "stopped"
    assert mock_http.instance_state == "stopped"
    assert ("PUT", "https://console.vast.ai/api/v0/instances/12345/", {"state": "stopped"}) in mock_http.calls

    # 5. Sprawdź, czy ŻADNE wywołanie nie było DELETE (destroy) ani POST (create)
    methods = [call[0] for call in mock_http.calls]
    assert "DELETE" not in methods, "Wykryto niedozwolone wywołanie DELETE (destroy)"
    assert "POST" not in methods, "Wykryto niedozwolone wywołanie POST (create)"
