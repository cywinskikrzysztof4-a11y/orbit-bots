"""Kontroler Vast.ai (oficjalne API console.vast.ai/api/v0). Tylko start/stop istniejącej instancji, NIGDY create/destroy.
Aktywny wyłącznie gdy ORBIT_USE_LOCAL_VIDEO/ORBIT_USE_OLLAMA i jest klucz w sejfie 'vast' + VAST_INSTANCE_ID. Faza 1: nieużywany."""
import os, time, requests
from . import vault, config, db
API = "https://console.vast.ai/api/v0"

class VastController:
    def __init__(self, http=requests):
        self.http = http
        self.last_gpu_job = time.time()
        self.session_started = None
        self.session_dph = 0.12  # domyślnie ~0.12 $/h dla RTX 3090

    def key(self):
        return vault.secret("vast", "api_key", "VAST_API_KEY")

    def instance(self):
        return os.environ.get("VAST_INSTANCE_ID")

    def enabled(self):
        return (config.PHASE2_OLLAMA or config.PHASE2_LOCAL_VIDEO) and bool(self.key() and self.instance())

    def status(self):
        if not self.key() or not self.instance():
            return {
                "state": "brak klucza" if not self.key() else "brak VAST_INSTANCE_ID",
                "enabled": False,
                "dph": self.session_dph,
                "session_cost": 0.0,
                "session_minutes": 0
            }
        if not (config.PHASE2_OLLAMA or config.PHASE2_LOCAL_VIDEO):
            return {
                "state": "wyłączony (faza 1)",
                "enabled": False,
                "dph": self.session_dph,
                "session_cost": 0.0,
                "session_minutes": 0
            }
        try:
            r = self.http.get(f"{API}/instances/{self.instance()}/", headers={"Authorization": "Bearer " + self.key()}, timeout=20)
            r.raise_for_status()
            res = r.json()
            inst = res.get("instances", res) if isinstance(res, dict) else {}
            if isinstance(inst, list) and inst:
                inst = inst[0]
            st = inst.get("actual_status", "unknown")
            dph = float(inst.get("dph_total") or self.session_dph)
            self.session_dph = dph

            if st == "running" and self.session_started is None:
                self.session_started = time.time()
            elif st != "running":
                self.session_started = None

            duration_h = (time.time() - self.session_started) / 3600 if self.session_started else 0
            cost = round(duration_h * dph, 4)
            mins = int(duration_h * 60)

            return {
                "state": st,
                "enabled": True,
                "dph": dph,
                "session_cost": cost,
                "session_minutes": mins,
                "instance_id": self.instance()
            }
        except Exception as e:
            return {
                "state": f"błąd połączenia: {str(e)[:100]}",
                "enabled": True,
                "dph": self.session_dph,
                "session_cost": 0.0,
                "session_minutes": 0
            }

    def _set(self, state):
        if state not in ("running", "stopped"):
            raise ValueError(f"Dozwolone tylko 'running' lub 'stopped', zabronione: {state}")
        db.execute("INSERT INTO jobs_log(bot,job,status,info) VALUES('core','vast',?,?)", (state, self.instance()))
        r = self.http.put(
            f"{API}/instances/{self.instance()}/",
            headers={"Authorization": "Bearer " + (self.key() or "")},
            json={"state": state},
            timeout=30
        )
        r.raise_for_status()
        if state == "running":
            self.session_started = time.time()
        else:
            self.session_started = None
        return state

    def start_instance(self):
        """Ręczny lub automatyczny start instancji."""
        return self._set("running")

    def stop_instance(self):
        """Ręczny lub automatyczny stop instancji."""
        return self._set("stopped")

    def tick(self, gpu_jobs_pending: int, running: bool):
        """Wywoływane co 60 s. Zwraca akcję: start/stop/None."""
        if not self.enabled():
            return None
        now = time.time()
        if gpu_jobs_pending:
            self.last_gpu_job = now
        if gpu_jobs_pending and not running:
            return self._set("running")
        if running and not gpu_jobs_pending and (now - self.last_gpu_job > config.VAST_IDLE_MIN * 60):
            return self._set("stopped")
        return None
