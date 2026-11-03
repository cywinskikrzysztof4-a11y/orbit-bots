"""Satelita — ogólny agent zadań webowych: pamięć rozmów + cache HTTP z TTL (SQLite),
izolowany katalog roboczy na każde zadanie, narzędzia fetch/scrape (requests+BeautifulSoup), rozumowanie Gemini."""
import os, json, re, time, uuid, hashlib, shutil, requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from flask import Blueprint, request, jsonify
from core import db, gemini
from core.registry import BotBase, register
TASKS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "tasks")
UA = {"User-Agent": "OrbitBots-Satelita/0.1 (personal research agent)"}
db.init("""
CREATE TABLE IF NOT EXISTS sat_memory(id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sat_cache(key TEXT PRIMARY KEY, value TEXT, expires REAL);
""")
def cache_get(k):
    r = db.query("SELECT value,expires FROM sat_cache WHERE key=?", (k,))
    return r[0]["value"] if r and r[0]["expires"] > time.time() else None
def cache_put(k, v, ttl): db.execute("INSERT OR REPLACE INTO sat_cache VALUES(?,?,?)", (k, v, time.time() + ttl))

class Sandbox:
    """Izolowany katalog na zadanie; narzędzia piszą tylko tutaj."""
    def __init__(self, tid): self.dir = os.path.realpath(os.path.join(TASKS, tid)); os.makedirs(self.dir, exist_ok=True)
    def write(self, name, text):
        p = os.path.realpath(os.path.join(self.dir, re.sub(r"[^\w.\-]", "_", name)))
        assert p.startswith(self.dir); open(p, "w").write(text); return p
    def fetch(self, url, ttl=3600):
        if urlparse(url).scheme not in ("http", "https"): raise ValueError("tylko http/https")
        k = "url:" + hashlib.sha256(url.encode()).hexdigest(); hit = cache_get(k)
        if hit: text = hit
        else:
            r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for t in soup(["script", "style", "noscript", "svg"]): t.decompose()
            title = soup.title.get_text(strip=True) if soup.title else ""
            text = (title + "\n" + re.sub(r"\n\s*\n+", "\n", soup.get_text("\n", strip=True)))[:20000]
            cache_put(k, text, ttl)
        self.write(hashlib.md5(url.encode()).hexdigest()[:10] + ".txt", text); return text
    def wiki(self, q, lang="pl"):
        k = f"wiki:{lang}:{q}"; hit = cache_get(k)
        if hit: return hit
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=20, params=dict(
            action="query", list="search", srsearch=q, format="json", srlimit=5)); r.raise_for_status()
        out = "\n".join(f'- {x["title"]}: https://{lang}.wikipedia.org/wiki/{x["title"].replace(" ", "_")} — ' +
                        re.sub("<[^>]+>", "", x["snippet"]) for x in r.json()["query"]["search"])
        cache_put(k, out, 86400); return out

SYSTEM = """Jesteś Satelita, agent zadań webowych aplikacji Orbit Bots. Odpowiadasz po polsku.
Masz narzędzia. W KAŻDYM kroku zwróć wyłącznie JSON:
{"action":"fetch","url":"https://..."} – pobiera tekst strony
{"action":"wiki","q":"..."} – wyszukuje w Wikipedii (zwraca tytuły i linki)
{"action":"answer","text":"..."} – końcowa odpowiedź (podaj źródła jako linki)
Nie logujesz się nigdzie, nic nie kupujesz, nie wysyłasz formularzy. Maks. 5 kroków."""

class Satelita(BotBase):
    id = "satelita"; name = "Satelita"; avatar = "satellite"
    description = "Ogólny agent webowy: czyta strony, streszcza, pamięta rozmowy."
    def status(self): return {"gemini": "ok" if gemini.available() else "brak klucza"}
    def run(self, session, msg):
        tid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]; sb = Sandbox(tid); trace = []
        mem = db.query("SELECT role,content FROM sat_memory WHERE session=? ORDER BY id DESC LIMIT 12", (session,))[::-1]
        db.execute("INSERT INTO sat_memory(session,role,content) VALUES(?,?,?)", (session, "user", msg))
        ctx = "\n".join(f'{m["role"]}: {m["content"][:1500]}' for m in mem)
        scratch = f"Historia rozmowy:\n{ctx}\n\nNowe zadanie użytkownika: {msg}\n"
        answer = None
        for step in range(5):
            raw = gemini.generate(scratch + "\nTwój następny krok (JSON):", SYSTEM)
            m = re.search(r"\{.*\}", raw, re.S)
            try: act = json.loads(m.group(0)) if m else {"action": "answer", "text": raw}
            except Exception: act = {"action": "answer", "text": raw}
            if act.get("action") == "answer" or step == 4 and act.get("action") != "answer":
                answer = act.get("text") or raw; break
            try:
                obs = sb.fetch(act["url"]) if act["action"] == "fetch" else sb.wiki(act["q"])
            except Exception as e: obs = f"BŁĄD: {e}"
            trace.append({"action": act.get("action"), "arg": act.get("url") or act.get("q"), "chars": len(obs)})
            scratch += f"\nKrok {step+1}: {json.dumps(act, ensure_ascii=False)}\nWynik:\n{obs[:6000]}\n"
        if answer is None:
            answer = gemini.generate(scratch + "\nNapisz teraz końcową odpowiedź po polsku z linkami do źródeł (zwykły tekst, nie JSON).")
        db.execute("INSERT INTO sat_memory(session,role,content) VALUES(?,?,?)", (session, "assistant", answer))
        sb.write("answer.md", answer); return {"answer": answer, "trace": trace, "task": tid}
    def init(self, app):
        bp = Blueprint("satelita", __name__, url_prefix="/api/satelita")
        @bp.post("/chat")
        def chat():
            j = request.json
            try: return jsonify(self.run(j.get("session", "default"), j["message"]))
            except Exception as e: return jsonify(error=str(e)[:300]), 502
        @bp.get("/history")
        def hist(): return jsonify(db.query("SELECT role,content,created FROM sat_memory WHERE session=? ORDER BY id", (request.args.get("session", "default"),)))
        @bp.post("/forget")
        def forget(): db.execute("DELETE FROM sat_memory WHERE session=?", (request.json.get("session", "default"),)); return jsonify(ok=1)
        @bp.get("/status")
        def st(): return jsonify(self.status())
        app.register_blueprint(bp)
    def jobs(self):
        def cleanup():  # czyści wygasły cache i katalogi zadań starsze niż 7 dni
            db.execute("DELETE FROM sat_cache WHERE expires<?", (time.time(),)); n = 0
            for d in os.listdir(TASKS) if os.path.isdir(TASKS) else []:
                p = os.path.join(TASKS, d)
                if time.time() - os.path.getmtime(p) > 7 * 86400: shutil.rmtree(p); n += 1
            return f"usunięto {n} katalogów"
        return [("cleanup", 86400, cleanup)]
register(Satelita())
