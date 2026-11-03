"""Bot Dzienny — inteligentny asystent Orbit z pamięcią rozmów (SQLite),
darmowymi narzędziami Fazy 1 (Open-Meteo, NBP, Wikipedia, fetch) oraz narzędziami poczty Gmail (tylko odczyt).
Wspiera autonomicznego agenta Gemini z pętlą function-calling (core.agent.Agent).
"""
import os, json, re, time, uuid, hashlib, shutil, requests
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core import db, config, gemini, llm, alerts, gmail
from core.browser import BROWSER_TOOLS
from core.agent import Agent, Tool, AgentResult
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
    """Pobiera zawartość strony WWW z usunięciem skryptów i styli (requests + BeautifulSoup). Tylko GET, limit rozmiaru."""
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

# ----------------- REJESTR NARZĘDZI DLA AGENTA DZIENNEGO -----------------

DAILY_TOOLS = [
    Tool(
        name="weather",
        description="Pobiera aktualną prognozę pogody dla podanego miasta (Open-Meteo, darmowe bez klucza).",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Nazwa miasta, np. Warszawa, Kraków, Berlin"}
            },
            "required": ["city"]
        },
        handler=get_weather,
        summary_fn=lambda r: f"{r.get('city')}: {r.get('temperature')}°C, {r.get('condition')}"
    ),
    Tool(
        name="nbp_rates",
        description="Pobiera oficjalny średni kurs waluty z Narodowego Banku Polskiego (NBP API).",
        parameters={
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Kod waluty ISO, np. EUR, USD, GBP, CHF"}
            },
            "required": ["currency"]
        },
        handler=lambda currency="EUR": get_nbp_rate(currency),
        summary_fn=lambda r: f"1 {r.get('code')} = {r.get('mid')} PLN ({r.get('effectiveDate')})"
    ),
    Tool(
        name="wikipedia",
        description="Wyszukuje hasło i pobiera streszczenie z Wikipedii.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Szukane hasło lub postać, np. Księżyc, Albert Einstein"},
                "lang": {"type": "string", "description": "Kod języka, domyślnie 'pl'", "default": "pl"}
            },
            "required": ["query"]
        },
        handler=lambda query, lang="pl": get_wikipedia(query, lang),
        summary_fn=lambda r: f"Wikipedia: '{r.get('title')}' (znaleziono artykuł)"
    ),
    Tool(
        name="web_fetch",
        description="Pobiera treść strony WWW (tylko protokoły HTTP/HTTPS, metoda GET, limit rozmiaru, bez skryptów/styli).",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Pełny adres URL strony internetowej (musi zaczynać się od http:// lub https://)"}
            },
            "required": ["url"]
        },
        handler=lambda url: fetch_url(url)[:25000],
        summary_fn=lambda r: f"Pobrano stronę WWW ({len(r)} znaków)"
    ),
    # Narzędzia Gmail (tylko odczyt)
    Tool(
        name="list_recent_emails",
        description="Pobiera listę ostatnich wiadomości z podłączonej skrzynki pocztowej Gmail (tylko odczyt).",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Maksymalna liczba wiadomości do pobrania (1-15, domyślnie 5)", "default": 5}
            }
        },
        handler=lambda max_results=5: gmail.list_recent_emails(max_results),
        summary_fn=lambda r: f"Pobrano {len(r)} ostatnich wiadomości z Gmaila"
    ),
    Tool(
        name="search_emails",
        description="Wyszukuje wiadomości w poczcie Gmail według zapytania tekstowego (np. 'from:jan', 'lot', 'faktura').",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Zapytanie wyszukiwania Gmail"},
                "max_results": {"type": "integer", "description": "Limit wyników (1-15)", "default": 5}
            },
            "required": ["query"]
        },
        handler=lambda query, max_results=5: gmail.search_emails(query, max_results),
        summary_fn=lambda r: f"Znaleziono {len(r)} wiadomości dla zapytania"
    ),
    Tool(
        name="read_email",
        description="Odczytuje pełną treść konkretnej wiadomości e-mail na podstawie jej message_id.",
        parameters={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Identyfikator wiadomości w Gmail"}
            },
            "required": ["message_id"]
        },
        handler=lambda message_id: gmail.read_email(message_id),
        summary_fn=lambda r: f"Odczytano wiadomość od {r.get('from')}: '{r.get('subject')}'"
    ),
    Tool(
        name="summarize_inbox",
        description="Przygotowuje zwięzłe podsumowanie ostatnich wiadomości ze skrzynki odbiorczej Gmail.",
        parameters={
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Liczba wiadomości do podsumowania", "default": 5}
            }
        },
        handler=lambda max_results=5: gmail.summarize_inbox(max_results),
        summary_fn=lambda r: "Wygenerowano podsumowanie skrzynki odbiorczej Gmail"
    )
] + BROWSER_TOOLS

def get_daily_agent() -> Agent:
    """Tworzy instancję Agenta Codziennego z zarejestrowanymi narzędziami."""
    return Agent(
        name="daily",
        system_prompt=(
            "Jesteś Dzienny — inteligentny asystent personalny w centrum dowodzenia Orbit Bots. "
            "Odpowiadasz zawsze w języku polskim, zwięźle, konkretnie i uprzejmie. "
            "Posiadasz zestaw darmowych narzędzi Fazy 1: pogoda (Open-Meteo), kursy walut (NBP), Wikipedia, pobieranie stron WWW (web_fetch), "
            "dostęp do skrzynki Gmail w trybie TYLKO DO ODCZYTU (bez możliwości wysyłania/usuwania) "
            "oraz narzędzia przeglądarki internetowej headless Chromium (browser_navigate, browser_click, browser_fill, browser_register_account) "
            "do otwierania stron, rejestracji kont, przeglądania sklepów i przechodzenia do kasy. "
            "PRZESTROGA: Przed kliknięciem ostatecznego przycisku 'Zapłać' / 'Złóż zamówienie' masz bezwzględny obowiązek zatrzymać się "
            "i przedstawić podsumowanie (sklep, kwota, pozycje) w panelu z prośbą o zatwierdzenie. Bez zatwierdzenia przez użytkownika płatność jest zablokowana. "
            "Nigdy nie loguj ani nie zapisuj w tekście danych kart płatniczych. W przypadku napotkania CAPTCHA lub kodu 2FA/SMS wstrzymaj działanie i poproś o kod."
        ),
        tools=DAILY_TOOLS,
        max_steps=6
    )

class ChatRequest(BaseModel):
    session: str = "default"
    message: str

class DailyBot(BotBase):
    id = "daily"
    name = "Dzienny"
    avatar = "satellite"
    description = "Asystent codzienny: czat z pamięcią, pogoda (Open-Meteo), kursy NBP, Wikipedia i narzędzia webowe."

    def status(self):
        gemini_ok = bool(os.environ.get("LLM_API_KEY")) or gemini.available()
        ollama_ok = config.PHASE2_OLLAMA
        return {
            "mode": "agent (gemini-3.5-flash-lite)" if os.environ.get("LLM_API_KEY") else ("ollama" if ollama_ok else "darmowy dyspozytor narzędzi"),
            "memory_entries": len(db.query("SELECT id FROM daily_memory")),
            "cache_entries": len(db.query("SELECT key FROM daily_cache WHERE expires > ?", (time.time(),))),
            "tools": ["Open-Meteo", "NBP", "Wikipedia", "web_fetch", "Gmail (readonly)", "Chromium Browser"]
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

        # 2. Główna ścieżka Agenta (jeśli jest LLM_API_KEY)
        if os.environ.get("LLM_API_KEY"):
            try:
                agent = get_daily_agent()
                agent_res = agent.run(msg, history=mem)
                answer = agent_res.answer
                db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
                sandbox.write("answer.md", answer)
                return {
                    "answer": answer,
                    "steps": agent_res.steps,
                    "paused": agent_res.paused,
                    "pause_reason": agent_res.pause_reason,
                    "pending_action": agent_res.pending_action,
                    "pending_2fa": agent_res.pending_2fa,
                    "task": tid
                }
            except Exception as e:
                alerts.notify(self.id, "Błąd Agenta Gemini", str(e)[:200])

        # 3. Jeśli Faza 2 z Ollama
        if config.PHASE2_OLLAMA:
            try:
                system_prompt = "Jesteś Dzienny, inteligentny asystent Orbit Bots. Odpowiadasz zwięźle i pomocnie po polsku."
                messages = [{"role": m["role"], "content": m["content"]} for m in mem]
                messages.append({"role": "user", "content": msg})
                answer = llm.chat(messages, system=system_prompt)
                db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
                sandbox.write("answer.md", answer)
                return {"answer": answer, "steps": [{"tool": "ollama", "result_summary": "Odpowiedź modelu lokalnego"}], "task": tid}
            except Exception as e:
                alerts.notify(self.id, "Błąd Ollama / Dolphin", str(e)[:200])

        # 4. Tryb awaryjny / bez klucza (inteligentny dyspozytor darmowych narzędzi)
        msg_l = msg.lower()
        url_match = re.search(r"https?://[^\s]+", msg)

        # Sprawdź intencje: Gmail
        if any(w in msg_l for w in ("mail", "poczta", "skrzynk", "inbox", "wiadomośc")):
            try:
                summary = gmail.summarize_inbox(5)
                answer = f"📬 **Podsumowanie poczty Gmail**:\n\n{summary}"
                trace.append({"tool": "summarize_inbox", "arguments": {"max_results": 5}, "result_summary": "Pobrano skrzynkę Gmail"})
            except Exception as e:
                answer = f"Nie udało się odczytać skrzynki Gmail: {e}"
                trace.append({"tool": "summarize_inbox", "arguments": {}, "result_summary": f"Błąd: {e}"})

        # Sprawdź intencje: pogoda
        elif any(w in msg_l for w in ("pogod", "temperatura", "deszcz", "stopni", "aura", "zimno", "ciepło")):
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
                trace.append({"tool": "weather", "arguments": {"city": city}, "result_summary": f"{city}: {w['temperature']}°C"})
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
                trace.append({"tool": "nbp_rates", "arguments": {"currency": code}, "result_summary": f"1 {code} = {nbp['mid']} PLN"})
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
                trace.append({"tool": "web_fetch", "arguments": {"url": target_url}, "result_summary": f"Pobrano {len(text)} znaków"})
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
                trace.append({"tool": "wikipedia", "arguments": {"query": q}, "result_summary": f"Hasło: {wres['title']}"})
            except Exception as e:
                answer = f"Nie znaleziono hasła w Wikipedii dla: '{q}'. Błąd: {e}"

        else:
            answer = (
                f"Cześć! Jestem **Dzienny** — Twój asystent Orbit Bots.\n\n"
                f"Działam z zestawem narzędzi Fazy 1:\n"
                f"• 🌤 **Pogoda**: zapytaj np. *„Jaka jest pogoda w Warszawie?”* (Open-Meteo)\n"
                f"• 💰 **Kursy walut**: zapytaj np. *„Jaki jest kurs euro / dolara?”* (NBP)\n"
                f"• 📖 **Wikipedia**: zapytaj np. *„Co to jest teleskop Jamesa Webba?”*\n"
                f"• 🌐 **Pobieranie stron**: wklej dowolny link HTTP/HTTPS (web_fetch)\n"
                f"• 📬 **Gmail (tylko odczyt)**: zapytaj np. *„Podsumuj moją skrzynkę”*\n\n"
                f"Wszystkie zadania zapisuję w izolowanym katalogu `{tid}`."
            )

        db.execute("INSERT INTO daily_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, answer))
        sandbox.write("answer.md", answer)
        return {"answer": answer, "steps": trace, "task": tid}

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
