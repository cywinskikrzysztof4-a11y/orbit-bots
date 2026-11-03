"""Kolejka zadań (SQLite).
Tabela jobs: id, bot, kind, payload_json, status[queued|running|done|error], gpu bool, result_json, created, started, finished.
Zadania GPU wykonuje worker po kolei (jedno naraz).
"""
import os, json, time, threading, traceback
from . import db

db.init("""
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'queued',
    gpu INTEGER DEFAULT 0,
    result_json TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP,
    started TEXT,
    finished TEXT
);
""")

_handlers = {}
_executor_thread = None
_stop_event = threading.Event()
_gpu_lock = threading.Lock()

def register_handler(bot: str, kind: str, fn):
    """Rejestruje funkcję obsługującą zadanie danego bota i rodzaju."""
    _handlers[(bot, kind)] = fn

def enqueue(bot: str, kind: str, payload: dict, gpu: bool = False) -> int:
    """Dodaje zadanie do kolejki."""
    payload_str = json.dumps(payload, ensure_ascii=False)
    job_id = db.execute(
        "INSERT INTO jobs(bot, kind, payload_json, status, gpu) VALUES (?, ?, ?, 'queued', ?)",
        (bot, kind, payload_str, 1 if gpu else 0)
    )
    return job_id

def get_job(job_id: int) -> dict | None:
    """Pobiera zadanie po ID."""
    rows = db.query("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not rows:
        return None
    r = rows[0]
    try:
        r["payload"] = json.loads(r.get("payload_json") or "{}")
    except Exception:
        r["payload"] = {}
    try:
        r["result"] = json.loads(r.get("result_json") or "{}") if r.get("result_json") else None
    except Exception:
        r["result"] = {"raw": r.get("result_json")}
    return r

def list_jobs(limit: int = 50, bot: str = None, status: str = None) -> list:
    """Zwraca listę zadań."""
    sql = "SELECT * FROM jobs WHERE 1=1"
    args = []
    if bot:
        sql += " AND bot = ?"
        args.append(bot)
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = db.query(sql, args)
    for r in rows:
        try:
            r["payload"] = json.loads(r.get("payload_json") or "{}")
        except Exception:
            r["payload"] = {}
        try:
            r["result"] = json.loads(r.get("result_json") or "{}") if r.get("result_json") else None
        except Exception:
            r["result"] = {"raw": r.get("result_json")}
    return rows

def count_pending_gpu() -> int:
    """Liczba oczekujących lub trwających zadań GPU."""
    rows = db.query("SELECT COUNT(*) AS c FROM jobs WHERE gpu = 1 AND status IN ('queued', 'running')")
    return rows[0]["c"] if rows else 0

def set_status(job_id: int, status: str, result: dict = None, error: str = None):
    """Aktualizuje status zadania."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if status == "running":
        db.execute("UPDATE jobs SET status = ?, started = ? WHERE id = ?", (status, now, job_id))
    elif status in ("done", "error"):
        res_data = result or {}
        if error:
            res_data["error"] = error
        res_str = json.dumps(res_data, ensure_ascii=False)
        db.execute("UPDATE jobs SET status = ?, result_json = ?, finished = ? WHERE id = ?", (status, res_str, now, job_id))

def _process_one_job():
    """Pobiera jedno zadanie w stanie 'queued' i wykonuje je."""
    # Zadania GPU wykonujemy pojedynczo z lockiem
    rows = db.query("SELECT id, bot, kind, payload_json, gpu FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1")
    if not rows:
        return False
    job = rows[0]
    jid = job["id"]
    bot = job["bot"]
    kind = job["kind"]
    is_gpu = bool(job["gpu"])

    fn = _handlers.get((bot, kind))
    if not fn:
        set_status(jid, "error", error=f"Brak zarejestrowanego handlera dla ({bot}, {kind})")
        return True

    def _execute():
        set_status(jid, "running")
        try:
            payload = json.loads(job.get("payload_json") or "{}")
            res = fn(jid, payload)
            set_status(jid, "done", result=res if isinstance(res, dict) else {"result": res})
        except Exception as e:
            tb = traceback.format_exc()
            set_status(jid, "error", error=str(e), result={"traceback": tb[-1000:]})

    if is_gpu:
        with _gpu_lock:
            _execute()
    else:
        _execute()
    return True

def _queue_loop():
    while not _stop_event.is_set():
        try:
            handled = _process_one_job()
            if not handled:
                _stop_event.wait(1.5)
        except Exception as e:
            time.sleep(2)

def start_worker():
    global _executor_thread
    if _executor_thread is None or not _executor_thread.is_alive():
        _stop_event.clear()
        _executor_thread = threading.Thread(target=_queue_loop, daemon=True, name="QueueWorker")
        _executor_thread.start()

def stop_worker():
    _stop_event.set()
