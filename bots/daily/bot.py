"""Bot Dzienny — czat po polsku z pamięcią rozmów (SQLite), cache HTTP z TTL,
izolowanym katalogiem na każde zadanie (z walidacją realpath) oraz darmowymi narzędziami Fazy 1
(Open-Meteo, NBP, Wikipedia, fetch+BeautifulSoup) i opcjonalnym Gemini / Dolphin Ollama.
"""
import os, json, re, time, uuid, hashlib, shutil, requests
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core import db, config, gemini, llm, alerts
from core.registry import BotBase, register

TASKS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "tasks"))
os.makedirs(TASKS_DIR, exist_ok=True)
UA = {"User-Agent": "OrbitBots-Daily/1.0 (personal assistant agent; contact via app owner)"}

db.init("""
CREATE TABLE IF NOT EXISTS daily_memory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS daily_cache(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires REAL NOT NULL
);
""")

def cache_get(key: str) -> str | None:
    rows = db.query("SELECT value, expires FROM daily_cache WHERE key = ?", (key,))
    if rows and rows[0]["expires"] > time.time():
        return rows[0]["value"]
    return None

def cache_put(key: str, value: str, ttl: float):
    db.execute("INSERT OR REPLACE INTO daily_cache(key, value, expires) VALUES (?, ?, ?)",
               (key, value, time.time() + ttl))

class TaskSandbox:
    """Izolowany katalog zadania w data/tasks/<id>/ z rygorystyczną walidacją realpath."""
    def __init__(self, task_id: str):
        safe_id = re.sub(r"[^\w\-]", "", task_id)
        self.dir = os.path.realpath(os.path.join(TASKS_DIR, safe_id))
        os.makedirs(self.dir, exist_ok=True)

    def validate_path(self, filename: str) -> str:
        """Ścieżki typu '../../x' lub próby wyjścia z katalogu zadania są bezwzględnie odrzucane."""
        if not filename or filename.strip() == "":
            raise ValueError("Pusta nazwa pliku")
        # Wykryj próbę directory traversal
        parts = re.split(r"[/\\]", filename)
        if ".." in parts or any(p == ".." for p in parts):
            raise ValueError(f"Niedozwolona próba wyjścia z katalogu zadania (path traversal): {filename}")

        target = os.path.realpath(os.path.join(self.dir, filename))
        if os.path.commonpath([self.dir, target]) != self.dir or target == self.dir:
            raise ValueError(f"Ścieżka poza dozwolonym katalogiem zadania: {filename}")
        return target

    def write(self, filename: str, content: str) -> str:
        target_path = self.validate_path(filename)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return target_path

    def read(self, filename: str) -> str:
        target_path = self.validate_path(filename)
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Plik nie istnieje: {filename}")
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()

# Narzędzia bez klucza
def fetch_url(url: str, sandbox: TaskSandbox = None, ttl: float = 3600) -> str:
    """Pobiera zawartość strony WWW z usunięciem skryptów i styli (requests + BeautifulSoup)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Dozwolone tylko http/https: {url}")
    ckey = "fetch:" + hashlib.sha256(url.encode()).hexdigest()
    hit = cache_get(ckey)
    if hit:
        text = hit
    else:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
            tag.decompose()
        title = soup.title.get_text(strip=True) if soup.title else ""
        raw_body = soup.get_text("\n", strip=True)
        cleaned_body = re.sub(r"\n\s*\n+", "\n", raw_body)
        text = (f"Tytuł: {title}\nURL: {url}\n\nTreść:\n" + cleaned_body)[:25000]
        cache_put(ckey, text, ttl)

    if sandbox:
        fname = "fetch_" + hashlib.md5(url.encode()).hexdigest()[:8] + ".txt"
        sandbox.write(fname, text)
    return text

def get_weather(city: str) -> dict:
    """Pobiera pogodę z darmowego API Open-Meteo bez klucza."""
    ckey = f"weather:{city.lower().strip()}"
    hit = cache_get(ckey)
    if hit:
        return json.loads(hit)

    # 1. Geokodowanie
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    geo_res = requests.get(geo_url, params={"name": city, "count": 1, "language": "pl", "format": "json"}, headers=UA, timeout=15)
    geo_res.raise_for_status()
    geo_data = geo_res.json()
    if not geo_data.get("results"):
        raise ValueError(f"Nie znaleziono lokalizacji: {city}")

    loc = geo_data["results"][0]
    lat, lon = loc["latitude"], loc["longitude"]
    loc_name = f"{loc.get('name')}, {loc.get('country', '')}"

    # 2. Prognoza pogody
    w_url = "https://api.open-meteo.com/v1/forecast"
    w_res = requests.get(w_url, params={
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
    }, headers=UA, timeout=15)
    w_res.raise_for_status()
    w_data = w_res.json()
    curr = w_data.get("current", {})

    weather_codes = {
        0: "Bezchmurnie / słonecznie",
        1: "Prawie bezchmurnie",
        2: "Częściowe zachmurzenie",
        3: "Pochmurno",
        45: "Mgła",
        48: "Marznąca mgła",
        51: "Lekka mżawka",
        53: "Umiarkowana mżawka",
        55: "Gęsta mżawka",
        61: "Lekki deszcz",
        63: "Umiarkowany deszcz",
        65: "Silny deszcz",
        71: "Lekki śnieg",
        73: "Umiarkowany śnieg",
        75: "Silny śnieg",
        80: "Lekkie opady przelotne",
        81: "Umiarkowane opady przelotne",
        82: "Gwałtowne opady deszczu",
        95: "Burza",
        96: "Burza z gradem"
    }
    w_desc = weather_codes.get(curr.get("weather_code", 0), "Zmienna aura")

    result = {
        "city": loc_name,
        "temperature": curr.get("temperature_2m"),
        "apparent_temperature": curr.get("apparent_temperature"),
        "humidity": curr.get("relative_humidity_2m"),
        "wind_speed": curr.get("wind_speed_10m"),
        "condition": w_desc,
        "source": "Open-Meteo (darmowe, bez klucza)"
    }
    cache_put(ckey, json.dumps(result, ensure_ascii=False), ttl=1800)
    return result

def get_nbp_rate(currency: str = "EUR") -> dict:
    """Pobiera kurs waluty z oficjalnego darmowego API Narodowego Banku Polskiego."""
    code = currency.upper().strip()
    ckey = f"nbp:{code}"
    hit = cache_get(ckey)
    if hit:
        return json.loads(hit)

    url = f"https://api.nbp.pl/api/exchangerates/rates/a/{code}/?format=json"
    r = requests.get(url, headers=UA, timeout=15)
    if r.status_code == 404:
        raise ValueError(f"Nieznana waluta w tabeli A NBP: {code}")
    r.raise_for_status()
    data = r.json()
    rate = data["rates"][0]
    result = {
        "currency": data.get("currency"),
        "code": code,
        "mid": rate.get("mid"),
        "effectiveDate": rate.get("effectiveDate"),
        "source": "Narodowy Bank Polski (NBP API, darmowe)"
    }
    cache_put(ckey, json.dumps(result, ensure_ascii=False), ttl=3600)
    return result

def get_wikipedia(query: str, lang: str = "pl") -> dict:
    """Pobiera streszczenie z polskiej Wikipedii (darmowe REST API)."""
    ckey = f"wiki:{lang}:{query.lower().strip()}"
    hit = cache_get(ckey)
    if hit:
        return json.loads(hit)

    # Najpierw spróbuj REST API summary
    sum_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
    try:
        r = requests.get(sum_url, headers=UA, timeout=15)
        if r.status_code == 200:
            data = r.json()
            res = {
                "title": data.get("title"),
                "extract": data.get("extract"),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
                "source": "Wikipedia REST API"
            }
            cache_put(ckey, json.dumps(res, ensure_ascii=False), ttl=86400)
            return res
    except Exception:
        pass

    # Wyszukiwanie OpenSearch / API search
    search_url = f"https://{lang}.wikipedia.org/w/api.php"
    r = requests.get(search_url, params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 3}, headers=UA, timeout=15)
    r.raise_for_status()
    s_data = r.json()
    results = s_data.get("query", {}).get("search", [])
    if not results:
        raise ValueError(f"Brak wyników w Wikipedii dla: {query}")

    first = results[0]
    title = first["title"]
    snippet = re.sub(r"<[^>]+>", "", first.get("snippet", ""))
    page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    res = {
        "title": title,
        "extract": snippet,
        "url": page_url,
        "source": "Wikipedia Search API"
    }
    cache_put(ckey, json.dumps(res, ensure_ascii=False), ttl=86400)
    return res

class ChatRequest(BaseModel):
    session: str = "default"
    message: str

class DailyBot(BotBase):
    id = "daily"
    name = "Dzienny"
    avatar = "satellite"
    description = "Asystent codzienny: czat z pamięcią, pogoda (Open-Meteo), kursy NBP, Wikipedia i narzędzia webowe."

    def status(self):
        gemini_ok = gemini.available()
        ollama_ok = config.PHASE2_OLLAMA
        return {
            "mode": "ollama (faza 2)" if ollama_ok else ("gemini" if gemini_ok else "darmowy (bez klucza: Open-Meteo, NBP, Wiki)"),
            "memory_entries": len(db.query("SELECT id FROM daily_memory")),
            "cache_entries": len(db.query("SELECT key FROM daily_cache WHERE expires > ?", (time.time(),))),
            "tools": ["Open-Meteo (pogoda)", "NBP (kursy walut)", "Wikipedia REST", "fetch (BeautifulSoup)"]
        }

    def run(self, session: str, msg: str) -> dict:
        tid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        sandbox = TaskSandbox(tid)
        trace = []

        # 1. Pobierz pamięć kontekstu (ostatnie 12 wiadomości)
        mem = db.query(
            "SELECT role, content FROM daily_memory WHERE session=? ORDER BY id DESC LIMIT 12",
            (session,)
        )[::-1]

        db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'user', ?)", (session, msg))

        # 2. Czy Faza 2 z Ollama?
        if config.PHASE2_OLLAMA:
            try:
                system_prompt = "Jesteś Dzienny, inteligentny asystent Orbit Bots. Odpowiadasz zwięźle i pomocnie po polsku."
                messages = [{"role": m["role"], "content": m["content"]} for m in mem]
                messages.append({"role": "user", "content": msg})
                answer = llm.chat(messages, system=system_prompt)
                db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
                sandbox.write("answer.md", answer)
                return {"answer": answer, "trace": [{"action": "ollama_dolphin", "status": "ok"}], "task": tid}
            except Exception as e:
                # Jeśli worker nie działa lub błąd połączenia
                alerts.notify(self.id, "Błąd Ollama / Dolphin", str(e)[:200])
                # przejdź do trybu awaryjnego

        # 3. Czy mamy klucz Gemini?
        if gemini.available():
            try:
                system_prompt = (
                    "Jesteś Dzienny, asystent zadań webowych aplikacji Orbit Bots. Odpowiadasz po polsku.\n"
                    "Dostępne narzędzia (zwróć JSON jeśli chcesz użyć narzędzia):\n"
                    "{\"action\":\"weather\",\"city\":\"...\"}\n"
                    "{\"action\":\"nbp\",\"currency\":\"EUR\"}\n"
                    "{\"action\":\"wiki\",\"q\":\"...\"}\n"
                    "{\"action\":\"fetch\",\"url\":\"https://...\"}\n"
                    "{\"action\":\"answer\",\"text\":\"...\"}\n"
                    "Maksymalnie 4 kroki. Zawsze odpowiadaj po polsku."
                )
                ctx = "\n".join(f'{m["role"]}: {m["content"][:1000]}' for m in mem)
                scratch = f"Historia rozmowy:\n{ctx}\n\nZapytanie użytkownika: {msg}\n"
                answer = None

                for step in range(4):
                    raw = gemini.generate(scratch + "\nTwój krok (JSON):", system_prompt)
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    try:
                        act = json.loads(m.group(0)) if m else {"action": "answer", "text": raw}
                    except Exception:
                        act = {"action": "answer", "text": raw}

                    if act.get("action") == "answer" or step == 3:
                        answer = act.get("text") or raw
                        break

                    obs = ""
                    action_type = act.get("action")
                    try:
                        if action_type == "weather":
                            obs = json.dumps(get_weather(act["city"]), ensure_ascii=False)
                        elif action_type == "nbp":
                            obs = json.dumps(get_nbp_rate(act.get("currency", "EUR")), ensure_ascii=False)
                        elif action_type == "wiki":
                            obs = json.dumps(get_wikipedia(act["q"]), ensure_ascii=False)
                        elif action_type == "fetch":
                            obs = fetch_url(act["url"], sandbox)[:5000]
                        else:
                            obs = f"Nieznana akcja: {action_type}"
                    except Exception as ex:
                        obs = f"BŁĄD narzędzia: {ex}"

                    trace.append({"step": step + 1, "action": action_type, "chars": len(obs)})
                    scratch += f"\nKrok {step+1}: {json.dumps(act, ensure_ascii=False)}\nWynik narzędzia:\n{obs[:3000]}\n"

                if not answer:
                    answer = gemini.generate(scratch + "\nNapisz końcową odpowiedź po polsku dla użytkownika:", system_prompt)

                db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
                sandbox.write("answer.md", answer)
                return {"answer": answer, "trace": trace, "task": tid}
            except Exception as e:
                trace.append({"error": f"Błąd Gemini: {e}"})

        # 4. Faza 1 bez klucza (inteligentny dyspozytor darmowych narzędzi)
        msg_l = msg.lower()
        url_match = re.search(r"https?://[^\s]+", msg)

        # Sprawdź intencje: pogoda
        if any(w in msg_l for w in ("pogod", "temperatura", "deszcz", "stopni", "aura", "zimno", "ciepło")):
            # Wyciągnij miasto
            words = [w for w in re.findall(r"[A-Za-zĄ-ż]+", msg) if w.lower() not in ("jaka", "jest", "pogoda", "w", "dla", "na", "czy", "będzie", "dziś", "dzisiaj", "jutro")]
            city = words[-1] if words else "Warszawa"
            try:
                w = get_weather(city)
                answer = (
                    f"🌤 **Prognoza pogody dla: {w['city']}**\n\n"
                    f"• Stan: **{w['condition']}**\n"
                    f"• Temperatura: **{w['temperature']}°C** (odczuwalna: {w['apparent_temperature']}°C)\n"
                    f"• Wilgotność: {w['humidity']}%\n"
                    f"• Wiatr: {w['wind_speed']} km/h\n\n"
                    f"*Źródło: {w['source']}*"
                )
                trace.append({"tool": "Open-Meteo", "city": city})
            except Exception as e:
                answer = f"Nie udało się pobrać pogody dla {city}: {e}"

        # Sprawdź intencje: waluta / NBP
        elif any(w in msg_l for w in ("kurs", "nbp", "dolar", "euro", "funt", "frank", "walut", "usd", "eur", "gbp", "chf")):
            code = "EUR"
            if "dolar" in msg_l or "usd" in msg_l:
                code = "USD"
            elif "funt" in msg_l or "gbp" in msg_l:
                code = "GBP"
            elif "frank" in msg_l or "chf" in msg_l:
                code = "CHF"
            try:
                nbp = get_nbp_rate(code)
                answer = (
                    f"💰 **Średni kurs waluty NBP**\n\n"
                    f"• Waluta: **{nbp['currency']} ({nbp['code']})**\n"
                    f"• Kurs średni: **{nbp['mid']} PLN**\n"
                    f"• Tabela z dnia: {nbp['effectiveDate']}\n\n"
                    f"*Źródło: {nbp['source']}*"
                )
                trace.append({"tool": "NBP", "code": code})
            except Exception as e:
                answer = f"Błąd pobierania kursu {code}: {e}"

        # Sprawdź intencje: URL do pobrania
        elif url_match:
            target_url = url_match.group(0)
            try:
                text = fetch_url(target_url, sandbox=sandbox)
                first_lines = "\n".join(text.split("\n")[:8])
                answer = (
                    f"📄 **Pobrano stronę WWW**:\n{first_url_summary(first_lines, target_url)}\n\n"
                    f"Pełna treść ({len(text)} znaków) została zapisana w izolowanym katalogu zadania `{tid}`."
                )
                trace.append({"tool": "fetch_url", "url": target_url, "bytes": len(text)})
            except Exception as e:
                answer = f"Błąd podczas pobierania {target_url}: {e}"

        # Sprawdź intencje: wikipedia / szukanie
        elif any(w in msg_l for w in ("kto to", "co to", "kim był", "kim jest", "wikipedia", "wiki", "czym jest", "definicja")):
            q = re.sub(r"^(kto to|co to|kim był|kim jest|czym jest|wikipedia|wiki|definicja)\s*(jest)?\s*", "", msg_l, flags=re.I).strip(" ?.")
            if not q:
                q = msg.strip(" ?.")
            try:
                wres = get_wikipedia(q)
                answer = (
                    f"📖 **Wikipedia: {wres['title']}**\n\n"
                    f"{wres['extract']}\n\n"
                    f"🔗 Więcej: {wres['url']}\n"
                    f"*Źródło: {wres['source']}*"
                )
                trace.append({"tool": "Wikipedia", "query": q})
            except Exception as e:
                answer = f"Nie znaleziono hasła w Wikipedii dla: '{q}'. Błąd: {e}"

        else:
            answer = (
                f"Cześć! Jestem **Dzienny** — Twój asystent Orbit Bots.\n\n"
                f"Działam w trybie darmowym (Faza 1) i mam wbudowane narzędzia bez klucza:\n"
                f"• 🌤 **Pogoda**: zapytaj np. *„Jaka jest pogoda w Warszawie?”* (Open-Meteo)\n"
                f"• 💰 **Kursy walut**: zapytaj np. *„Jaki jest kurs euro / dolara?”* (NBP)\n"
                f"• 📖 **Wikipedia**: zapytaj np. *„Co to jest teleskop Jamesa Webba?”*\n"
                f"• 🌐 **Pobieranie stron**: wklej dowolny link HTTP/HTTPS (fetch + BeautifulSoup)\n\n"
                f"Wszystkie zadania zapisuję w izolowanym katalogu roboczym `{tid}`.\n"
                f"Twoja wiadomość: *„{msg}”* została zapisana w historii sesji `{session}`."
            )

        db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
        sandbox.write("answer.md", answer)
        return {"answer": answer, "trace": trace, "task": tid}

    def init(self, app):
        router = APIRouter(prefix="/api/daily", tags=["daily"])

        @router.post("/chat")
        def chat(req: ChatRequest):
            try:
                return self.run(req.session or "default", req.message)
            except Exception as e:
                raise HTTPException(status_code=502, detail=str(e)[:300])

        @router.get("/history")
        def history(session: str = "default"):
            return db.query(
                "SELECT role, content, created FROM daily_memory WHERE session=? ORDER BY id ASC",
                (session,)
            )

        @router.post("/forget")
        def forget(req: dict):
            session = req.get("session", "default")
            db.execute("DELETE FROM daily_memory WHERE session=?", (session,))
            return {"ok": 1, "session": session}

        @router.get("/status")
        def st():
            return self.status()

        # Dedykowane endpointy narzędziowe
        @router.post("/tools/weather")
        def tool_weather(req: dict):
            city = req.get("city", "Warszawa")
            try:
                return get_weather(city)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @router.post("/tools/nbp")
        def tool_nbp(req: dict):
            curr = req.get("currency", "EUR")
            try:
                return get_nbp_rate(curr)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @router.post("/tools/wiki")
        def tool_wiki(req: dict):
            q = req.get("query", "")
            if not q:
                raise HTTPException(status_code=400, detail="Brak parametru query")
            try:
                return get_wikipedia(q)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @router.post("/tools/fetch")
        def tool_fetch(req: dict):
            url = req.get("url", "")
            if not url:
                raise HTTPException(status_code=400, detail="Brak parametru url")
            try:
                tid = "tool-fetch-" + uuid.uuid4().hex[:6]
                sb = TaskSandbox(tid)
                content = fetch_url(url, sb)
                return {"url": url, "chars": len(content), "preview": content[:1000], "task_id": tid}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        app.include_router(router)

    def jobs(self):
        def cleanup():
            db.execute("DELETE FROM daily_cache WHERE expires < ?", (time.time(),))
            deleted = 0
            if os.path.isdir(TASKS_DIR):
                for d in os.listdir(TASKS_DIR):
                    p = os.path.join(TASKS_DIR, d)
                    if os.path.isdir(p) and (time.time() - os.path.getmtime(p) > 7 * 86400):
                        try:
                            shutil.rmtree(p)
                            deleted += 1
                        except Exception:
                            pass
            return f"Wyczyszczono wygasły cache i {deleted} starych katalogów zadań"
        return [("cleanup", 86400, cleanup)]

def first_url_summary(text: str, url: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines[:6])

register(DailyBot())
