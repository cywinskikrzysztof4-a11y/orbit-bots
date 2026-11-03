import sqlite3, os, threading
DB = os.environ.get("ORBIT_DB", os.path.join(os.path.dirname(__file__), "..", "data", "orbit.db"))
os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
_lock = threading.Lock()
def conn():
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False); c.row_factory = sqlite3.Row; return c
def execute(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, args); return cur.lastrowid
def query(sql, args=()):
    with conn() as c: return [dict(r) for r in c.execute(sql, args).fetchall()]
def init(schema_sql):
    with _lock, conn() as c: c.executescript(schema_sql)
init("""
CREATE TABLE IF NOT EXISTS alerts_log(id INTEGER PRIMARY KEY, bot TEXT, title TEXT, body TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS jobs_log(id INTEGER PRIMARY KEY, bot TEXT, job TEXT, status TEXT, info TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
""")
