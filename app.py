"""Orbit Bots — modułowa aplikacja wielobotowa (FastAPI + SQLite, UI po polsku).
Start: .venv/bin/python app.py  (port 5003).
"""
import os, importlib, base64, threading, secrets as _secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Header, Query, Body
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import db, alerts, vault, config, queue, accounts, gmail, activity, keepalive
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
    # Startup: uruchomienie harmonogramu, wątku kolejki i pętli keep-alive (tylko w Codespaces)
    queue.start_worker()
    sched.start()
    keepalive.start_keepalive()
    yield
    # Shutdown
    keepalive.stop_keepalive()
    sched.stop()
    queue.stop_worker()

app = FastAPI(title="Orbit Bots", version="2.0.0", lifespan=lifespan)

# Bezpieczeństwo (Wymóg 6): hasło ORBIT_PANEL_PASSWORD chroni wszystkie strony i API (poza callbackiem OAuth i /health).
# Gdy podłączona poczta/konta, a hasła brak – odmów dostępu (403 Forbidden).
EXEMPT_PATHS = ("/health", "/healthz", "/auth/google/callback", "/api/health/busy", "/api/jobs/run-scheduled")

@app.middleware("http")
async def _panel_auth(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    pw = os.environ.get("ORBIT_PANEL_PASSWORD", "").strip()
    accounts_connected = accounts.has_connected_accounts()

    # Kiedy podłączono konta/pocztę, a hasło ORBIT_PANEL_PASSWORD nie jest ustawione -> bezwzględna odmowa dostępu
    if accounts_connected and not pw:
        return Response(
            "Odmowa dostępu: Wykryto podłączone konta/pocztę, ale hasło ORBIT_PANEL_PASSWORD nie zostało ustawione w zmiennych środowiskowych. "
            "Ustaw ORBIT_PANEL_PASSWORD w konfiguracji Render / .env, aby zabezpieczyć aplikację.",
            status_code=403,
            media_type="text/plain; charset=utf-8"
        )

    # Jeśli hasło jest ustawione -> weryfikacja HTTP Basic Auth
    if pw:
        h = request.headers.get("authorization", "")
        ok = False
        if h.startswith("Basic "):
            try:
                decoded = base64.b64decode(h[6:]).decode().split(":", 1)[-1]
                ok = _secrets.compare_digest(decoded, pw)
            except Exception:
                ok = False
        if not ok:
            return Response("Wymagane hasło panelu", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Orbit"'})

    return await call_next(request)

@app.get("/health")
@app.get("/healthz")
def health_check():
    return {"ok": True, "status": "healthy"}

@app.get("/api/health/busy")
def get_health_busy():
    """Zwraca status obciążenia: liczbę aktywnych zadań, zadań w kolejce i znacznik ostatniej aktywności."""
    return activity.get_busy_status()

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

@app.post("/api/jobs/run-scheduled")
def run_scheduled_jobs(
    authorization: str | None = Header(None),
    x_orbit_token: str | None = Header(None),
    x_github_token: str | None = Header(None),
    token: str | None = Query(None),
    wait: bool = Query(False),
    payload: dict | None = Body(None)
):
    """Uruchamia zaplanowane zadania botów.
    Chroniony tokenem ze zmiennych środowiskowych (CODESPACE_PAT lub ORBIT_JOB_TOKEN).
    Token można przekazać w nagłówku Authorization (Bearer), X-Orbit-Token, X-Github-Token,
    w parametrze query ?token=... lub w ciele JSON {"token": "..."}.
    """
    expected = (
        os.environ.get("CODESPACE_PAT", "").strip()
        or os.environ.get("ORBIT_JOB_TOKEN", "").strip()
        or os.environ.get("ORBIT_PANEL_PASSWORD", "").strip()
    )
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="Brak skonfigurowanego tokenu w zmiennych środowiskowych serwera (ustaw CODESPACE_PAT lub ORBIT_JOB_TOKEN)"
        )

    provided = ""
    if authorization:
        provided = authorization[7:].strip() if authorization.startswith("Bearer ") else authorization.strip()
    elif x_orbit_token:
        provided = x_orbit_token.strip()
    elif x_github_token:
        provided = x_github_token.strip()
    elif token:
        provided = token.strip()
    elif payload and isinstance(payload, dict) and payload.get("token"):
        provided = str(payload.get("token")).strip()

    if not provided or not _secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Nieprawidłowy token autoryzacji")

    bot_filter = None
    if payload and isinstance(payload, dict) and payload.get("bots"):
        bot_filter = payload.get("bots")

    scheduled_jobs = [f"{j['bot']}:{j['name']}" for j in sched.jobs if j["bot"] != "core"]

    if wait:
        with activity.track_task("scheduled_jobs_sync_batch"):
            results = sched.run_all_scheduled(bots=bot_filter)
        return {
            "ok": True,
            "status": "completed",
            "results": results,
            "active": activity.get_active_count()
        }

    def _run_batch_in_background():
        with activity.track_task("scheduled_jobs_batch"):
            sched.run_all_scheduled(bots=bot_filter)

    t = threading.Thread(target=_run_batch_in_background, daemon=True, name="ScheduledJobsRunner")
    t.start()

    return {
        "ok": True,
        "status": "started",
        "jobs": scheduled_jobs,
        "active": activity.get_active_count()
    }

# ----------------- GMAIL OAUTH 2.0 WEB FLOW -----------------

def get_redirect_uri(request: Request) -> str:
    env_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if env_uri:
        return env_uri
    # Domyślny produkcyjny URI na Renderze zgodnie ze specyfikacją
    if request.base_url.hostname and "localhost" not in request.base_url.hostname and "127.0.0.1" not in request.base_url.hostname:
        return "https://orbit-bots.onrender.com/auth/google/callback"
    return str(request.base_url).rstrip("/") + "/auth/google/callback"

@app.get("/auth/google/start")
def auth_google_start(request: Request):
    """Rozpoczyna przepływ autoryzacji Google OAuth 2.0 (scope gmail.readonly)."""
    redirect_uri = get_redirect_uri(request)
    try:
        url, state = gmail.generate_auth_url(redirect_uri)
        return RedirectResponse(url)
    except ValueError as e:
        return HTMLResponse(
            f"<h3>Błąd konfiguracji OAuth</h3><p>{e}</p>"
            f"<p>Skonfiguruj zmienne <code>GOOGLE_CLIENT_ID</code> i <code>GOOGLE_CLIENT_SECRET</code> w środowisku Render.</p>"
            f"<p><a href='/'>Powrót do panelu</a></p>",
            status_code=400
        )

@app.get("/auth/google/callback")
def auth_google_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Odbiera kod autoryzacji od Google, weryfikuje stan i zapisuje token w sejfie Fernet."""
    if error:
        return HTMLResponse(
            f"<h3>Odmowa dostępu / Błąd autoryzacji</h3><p>{error}</p><p><a href='/'>Powrót</a></p>",
            status_code=400
        )
    if not code or not state:
        return HTMLResponse("<h3>Brak wymaganych parametrów code/state</h3><p><a href='/'>Powrót</a></p>", status_code=400)

    if not gmail.verify_state(state):
        return HTMLResponse("<h3>Błąd weryfikacji tokenu state (możliwa próba CSRF lub wygasła sesja). Spróbuj ponownie.</h3><p><a href='/'>Powrót</a></p>", status_code=400)

    redirect_uri = get_redirect_uri(request)
    try:
        tokens = gmail.exchange_code_for_tokens(code, redirect_uri)
        email = tokens.get("email", "Google")
        alerts.notify("daily", "Poczta Gmail podłączona", f"Pomyślnie powiązano konto Gmail: {email} (tryb tylko do odczytu)")
        return RedirectResponse("/?gmail_connected=1")
    except Exception as e:
        return HTMLResponse(f"<h3>Błąd wymiany tokenów:</h3><pre>{e}</pre><p><a href='/'>Powrót</a></p>", status_code=500)

# ----------------- MODUŁ KONT (core/accounts.py) API -----------------

class CredentialsAccountRequest(BaseModel):
    id: str
    name: str
    service: str
    username: str
    password: str
    consent: bool = True

class ConsentUpdateRequest(BaseModel):
    consent: bool

class Submit2FARequest(BaseModel):
    code: str

@app.get("/api/accounts")
def get_accounts():
    return accounts.list_accounts()

@app.post("/api/accounts/credentials")
def add_credentials_account(payload: CredentialsAccountRequest):
    return accounts.register_credentials_account(
        account_id=payload.id,
        name=payload.name,
        service=payload.service,
        username=payload.username,
        password=payload.password,
        consent=payload.consent
    )

@app.post("/api/accounts/{account_id}/consent")
def update_account_consent(account_id: str, payload: ConsentUpdateRequest):
    accounts.set_consent(account_id, payload.consent)
    return {"ok": 1, "account_id": account_id, "consent": payload.consent}

@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str):
    accounts.disconnect_account(account_id)
    return {"ok": 1, "disconnected": account_id}

@app.get("/api/actions/pending")
def get_pending_actions(status: str = "pending"):
    return accounts.list_pending_actions(status=status)

@app.post("/api/actions/{action_id}/approve")
def approve_action(action_id: str):
    return accounts.approve_action(action_id)

@app.post("/api/actions/{action_id}/reject")
def reject_action(action_id: str):
    return accounts.reject_action(action_id)

@app.post("/api/actions/{action_id}/execute")
def execute_action(action_id: str):
    from core.browser import get_browser_controller
    return get_browser_controller().execute_approved_purchase(action_id)

@app.get("/api/2fa/pending")
def get_pending_2fa():
    return accounts.list_pending_2fa()

@app.post("/api/2fa/{req_id}/submit")
def submit_2fa(req_id: str, payload: Submit2FARequest):
    return accounts.submit_2fa_code(req_id, payload.code)

# ----------------- SEJF KLUCZY (Fernet) -----------------
class VaultEntry(BaseModel):
    name: str
    data: dict

@app.get("/api/vault")
def get_vault_names():
    # Zwraca WYŁĄCZNIE nazwy wpisów, nigdy ich zawartości
    return vault.names()

@app.post("/api/vault")
def put_vault_secret(entry: VaultEntry):
    vault.put(entry.name, entry.data)
    return {"ok": 1, "name": entry.name}

@app.delete("/api/vault/{name}")
def delete_vault_secret(name: str):
    vault.delete(name)
    return {"ok": 1, "deleted": name}

# ----------------- KONTROLER VAST.AI -----------------
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
