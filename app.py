"""Orbit Bots — modułowa aplikacja wielobotowa (FastAPI + SQLite, UI po polsku).
Start: .venv/bin/python app.py  (port 5003).
"""
import os, importlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import db, alerts, vault, config, queue
from core.registry import BOTS
from core.scheduler import Scheduler
from core.vast import VastController

BOT_MODULES = [
    "bots.flights.bot",
    "bots.daily.bot",
    "bots.video.bot"
]

sched = Scheduler()
vast_ctrl = VastController()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: uruchomienie harmonogramu i wątku kolejki
    queue.start_worker()
    sched.start()
    yield
    # Shutdown
    sched.stop()
    queue.stop_worker()

app = FastAPI(title="Orbit Bots", version="2.0.0", lifespan=lifespan)


# Opcjonalne hasło panelu (HTTP Basic) z env ORBIT_PANEL_PASSWORD
import base64, secrets as _secrets
from fastapi.responses import Response
@app.middleware("http")
async def _panel_auth(request: Request, call_next):
    pw = os.environ.get("ORBIT_PANEL_PASSWORD", "")
    if pw and request.url.path != "/healthz":
        h = request.headers.get("authorization", "")
        ok = False
        if h.startswith("Basic "):
            try:
                ok = _secrets.compare_digest(base64.b64decode(h[6:]).decode().split(":", 1)[-1], pw)
            except Exception:
                ok = False
        if not ok:
            return Response("Wymagane hasło", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Orbit"'})
    return await call_next(request)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Montowanie plików statycznych
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Import botów i rejestracja w aplikacji
for m in BOT_MODULES:
    try:
        importlib.import_module(m)
    except Exception as e:
        print(f"[Orbit] Błąd ładowania modułu {m}: {e}")

for b in BOTS.values():
    b.init(app)
    for name, every, fn in b.jobs():
        sched.add(b.id, name, every, fn)

# Zadanie okresowe dla kontrolera Vast.ai (co 60 s)
def vast_tick_job():
    st = vast_ctrl.status()
    is_running = st.get("state") == "running"
    pending_gpu = queue.count_pending_gpu()
    act = vast_ctrl.tick(pending_gpu, is_running)
    return f"pending={pending_gpu}, running={is_running}, action={act}"

sched.add("core", "vast_tick", 60, vast_tick_job)

# Endpointy główne
@app.get("/", response_class=HTMLResponse)
def index():
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(tpl_path):
        with open(tpl_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Orbit Bots — index.html nie znaleziony</h1>"

@app.get("/api/bots")
def get_bots():
    return [
        {
            "id": b.id,
            "name": b.name,
            "description": b.description,
            "avatar": b.avatar,
            "status": b.status()
        }
        for b in BOTS.values()
    ]

@app.get("/api/alerts")
def get_alerts(limit: int = 50):
    return alerts.recent(limit)

@app.post("/api/alerts/read")
def mark_alerts_read():
    alerts.mark_all_read()
    return {"ok": 1}

@app.get("/api/jobs")
def get_jobs_status():
    return {
        "jobs": [
            {
                "bot": j["bot"],
                "name": j["name"],
                "every_h": round(j["every"] / 3600, 2)
            }
            for j in sched.jobs
        ],
        "queue": queue.list_jobs(limit=20),
        "log": db.query("SELECT bot, job, status, substr(info, 1, 200) AS info, created FROM jobs_log ORDER BY id DESC LIMIT 25")
    }

# Sejf danych dostępowych (Fernet)
class VaultEntry(BaseModel):
    name: str
    data: dict

@app.get("/api/vault")
def get_vault_names():
    # Zgodnie z zasadami bezpieczeństwa: zwraca WYŁĄCZNIE nazwy wpisów, nigdy ich wartości!
    return vault.names()

@app.post("/api/vault")
def put_vault_secret(entry: VaultEntry):
    vault.put(entry.name, entry.data)
    return {"ok": 1, "name": entry.name}

@app.delete("/api/vault/{name}")
def delete_vault_secret(name: str):
    vault.delete(name)
    return {"ok": 1, "deleted": name}

# Kontroler Vast.ai
@app.get("/api/vast/status")
def get_vast_status():
    return vast_ctrl.status()

@app.post("/api/vast/start")
def start_vast():
    try:
        return {"status": vast_ctrl.start_instance()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/api/vast/stop")
def stop_vast():
    try:
        return {"status": vast_ctrl.stop_instance()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5003))
    print(f"[Orbit Bots] Uruchamianie na porcie {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
