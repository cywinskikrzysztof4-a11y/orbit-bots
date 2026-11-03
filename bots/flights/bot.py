"""Łowca lotów — śledzenie cen tras z polskich lotnisk + alerty (próg / spadek o X%).
Ceny z Ryanair farfnd (etykieta „NIEOFICJALNE”, zapytania co 6 h).
Okazje z RSS Fly4free.pl (co 2 h, deduplikacja po linku).
Wspiera autonomicznego agenta Gemini (core.agent.Agent) z narzędziami:
- ryanair_search, fly4free_search, price_alert_add, price_alert_list, price_alert_remove.
"""
import os, json, re
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from core import db, alerts
from core.agent import Agent, Tool, AgentResult
from core.registry import BotBase, register
from .providers import PROVIDERS, Ryanair
from .forums import fetch_and_save_fly4free

PL_AIRPORTS = ["WAW", "WMI", "KRK", "KTW", "GDN", "WRO", "POZ", "LCJ", "RZE", "LUZ", "SZZ", "BZG", "IEG", "RDO", "SZY"]

db.init("""
CREATE TABLE IF NOT EXISTS fl_routes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,
    dest TEXT NOT NULL,
    month TEXT NOT NULL,
    provider TEXT DEFAULT 'ryanair',
    threshold REAL,
    drop_pct REAL,
    active INTEGER DEFAULT 1,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fl_prices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER,
    checked TEXT DEFAULT CURRENT_TIMESTAMP,
    min_price REAL,
    min_date TEXT,
    currency TEXT,
    days_json TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS fl_memory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
""")

INTERVAL_H = float(os.environ.get("ORBIT_FLIGHTS_EVERY_H", "6"))

class RouteCreate(BaseModel):
    origin: str
    dest: str
    month: str
    provider: str = "ryanair"
    threshold: float | None = None
    drop_pct: float | None = None

class FlightChatRequest(BaseModel):
    session: str = "default"
    message: str

# ----------------- FUNKCJE NARZĘDZI AGENTA LOTNICZEGO -----------------

def tool_ryanair_search(origin: str, dest: str, month: str) -> dict:
    """Wyszukuje najtańsze loty z Ryanair farfnd dla danej trasy i miesiąca."""
    o = origin.upper().strip()
    d = dest.upper().strip()
    m = month.strip()
    provider = Ryanair()
    fares = provider.month(o, d, m)
    if not fares:
        return {"origin": o, "dest": d, "month": m, "fares_count": 0, "message": "Brak dostępnych taryf"}
    cheapest = min(fares, key=lambda f: f["price"])
    return {
        "origin": o,
        "dest": d,
        "month": m,
        "fares_count": len(fares),
        "cheapest": cheapest,
        "sample_fares": fares[:8]
    }

def tool_fly4free_search(query: str = "", limit: int = 10) -> dict:
    """Przeszukuje zapisane okazje lotnicze z Fly4free.pl."""
    lim = max(1, min(int(limit), 30))
    if query:
        rows = db.query(
            "SELECT id, title, link, price, origin, pub_date FROM fly4free_deals WHERE title LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", lim)
        )
    else:
        rows = db.query(
            "SELECT id, title, link, price, origin, pub_date FROM fly4free_deals ORDER BY id DESC LIMIT ?",
            (lim,)
        )
    if not rows:
        try:
            fetch_and_save_fly4free()
            if query:
                rows = db.query(
                    "SELECT id, title, link, price, origin, pub_date FROM fly4free_deals WHERE title LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{query}%", lim)
                )
            else:
                rows = db.query(
                    "SELECT id, title, link, price, origin, pub_date FROM fly4free_deals ORDER BY id DESC LIMIT ?",
                    (lim,)
                )
        except Exception:
            pass
    return {"query": query, "count": len(rows), "deals": [dict(r) for r in rows]}

def tool_price_alert_add(origin: str, dest: str, month: str, threshold: float = None, drop_pct: float = None) -> dict:
    """Dodaje trasę do bazy alertów cenowych i natychmiast sprawdza aktualne ceny."""
    o = origin.upper().strip()
    d = dest.upper().strip()
    m = month.strip()
    if o not in PL_AIRPORTS:
        return {"error": f"Lotnisko wylotu '{o}' nie jest polskim lotniskiem ({', '.join(PL_AIRPORTS)})"}
    rid = db.execute(
        "INSERT INTO fl_routes(origin, dest, month, provider, threshold, drop_pct) VALUES (?, ?, ?, 'ryanair', ?, ?)",
        (o, d, m, threshold, drop_pct)
    )
    route = db.query("SELECT * FROM fl_routes WHERE id = ?", (rid,))[0]
    bot = FlightBot()
    check_res = bot.check_route(route)
    return {"route_id": rid, "status": "added", "check": check_res}

def tool_price_alert_list() -> dict:
    """Zwraca listę wszystkich aktywnych tras i ich ostatnio sprawdzonych cen."""
    routes = db.query("SELECT id, origin, dest, month, threshold, drop_pct, active, created FROM fl_routes ORDER BY id DESC")
    out = []
    for r in routes:
        last = db.query("SELECT min_price, min_date, currency, checked FROM fl_prices WHERE route_id = ? ORDER BY id DESC LIMIT 1", (r["id"],))
        out.append({
            "route": dict(r),
            "latest_price": dict(last[0]) if last else None
        })
    return {"count": len(out), "alerts": out}

def tool_price_alert_remove(route_id: int) -> dict:
    """Usuwa monitorowaną trasę i jej historię cen."""
    db.execute("DELETE FROM fl_routes WHERE id = ?", (route_id,))
    db.execute("DELETE FROM fl_prices WHERE route_id = ?", (route_id,))
    return {"route_id": route_id, "status": "removed"}

FLIGHT_TOOLS = [
    Tool(
        name="ryanair_search",
        description="Wyszukuje ceny lotów z polskich lotnisk przez Ryanair farfnd dla danego miesiąca.",
        parameters={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Kod IATA lotniska wylotu z Polski (np. WMI, WAW, KRK, GDN)"},
                "dest": {"type": "string", "description": "Kod IATA lotniska docelowego (np. BCN, FCO, ALC, AGP)"},
                "month": {"type": "string", "description": "Miesiąc w formacie YYYY-MM (np. 2026-12)"}
            },
            "required": ["origin", "dest", "month"]
        },
        handler=tool_ryanair_search,
        summary_fn=lambda r: f"Znaleziono {r.get('fares_count', 0)} dni lotów; najtaniej: {r.get('cheapest', {}).get('price')} {r.get('cheapest', {}).get('currency')} w dniu {r.get('cheapest', {}).get('date')}" if r.get('cheapest') else "Brak lotów"
    ),
    Tool(
        name="fly4free_search",
        description="Wyszukuje okazje podróżnicze i tanie loty z serwisu Fly4free.pl.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Fraza wyszukiwania (np. Hiszpania, Włochy, Rzym)", "default": ""},
                "limit": {"type": "integer", "description": "Maksymalna liczba okazji (1-20)", "default": 10}
            }
        },
        handler=tool_fly4free_search,
        summary_fn=lambda r: f"Znaleziono {r.get('count', 0)} okazji z Fly4free"
    ),
    Tool(
        name="price_alert_add",
        description="Tworzy nowy alert cenowy dla wybranej trasy lotniczej.",
        parameters={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Lotnisko wylotu (kod IATA, np. WMI)"},
                "dest": {"type": "string", "description": "Lotnisko docelowe (kod IATA, np. BCN)"},
                "month": {"type": "string", "description": "Miesiąc w formacie YYYY-MM"},
                "threshold": {"type": "number", "description": "Próg ceny w PLN (alert gdy cena <= próg)"},
                "drop_pct": {"type": "number", "description": "Spadek ceny w % (alert gdy spadek >= %)"}
            },
            "required": ["origin", "dest", "month"]
        },
        handler=tool_price_alert_add,
        summary_fn=lambda r: f"Dodano alert dla trasy ID: {r.get('route_id')}"
    ),
    Tool(
        name="price_alert_list",
        description="Zwraca listę wszystkich aktualnie monitorowanych tras i alertów cenowych.",
        parameters={"type": "object", "properties": {}},
        handler=tool_price_alert_list,
        summary_fn=lambda r: f"Pobrano {r.get('count', 0)} aktywnych alertów cenowych"
    ),
    Tool(
        name="price_alert_remove",
        description="Usuwa alert cenowy dla wskazanej trasy po jej identyfikatorze (route_id).",
        parameters={
            "type": "object",
            "properties": {
                "route_id": {"type": "integer", "description": "Identyfikator trasy do usunięcia"}
            },
            "required": ["route_id"]
        },
        handler=tool_price_alert_remove,
        summary_fn=lambda r: f"Usunięto alert trasy #{r.get('route_id')}"
    )
]

def get_flight_agent() -> Agent:
    return Agent(
        name="flights",
        system_prompt=(
            "Jesteś Łowca Lotów — inteligentny agent podróżniczy Orbit Bots. "
            "Odpowiadasz po polsku, zwięźle i konkretnie. "
            "Posiadasz narzędzia do wyszukiwania najtańszych połączeń Ryanair (ryanair_search), "
            "przeszukiwania okazji Fly4free (fly4free_search) oraz zarządzania alertami cenowymi "
            "(price_alert_add, price_alert_list, price_alert_remove). "
            "Gdy użytkownik pyta o ceny lub chce monitorować trasę, używaj odpowiednich narzędzi."
        ),
        tools=FLIGHT_TOOLS,
        max_steps=6
    )

class FlightBot(BotBase):
    id = "flights"
    name = "Łowca lotów"
    avatar = "china-flag"
    description = "Śledzi najtańsze loty z Polski i wysyła alerty cenowe."

    def check_route(self, r, force_alert=False):
        p = PROVIDERS.get(r["provider"])
        if not p:
            return {"route": r["id"], "error": f"Nieznany dostawca: {r['provider']}"}
        if not p.configured():
            return {"route": r["id"], "error": f"brak klucza: {p.id}"}

        fares = p.month(r["origin"], r["dest"], r["month"])
        if not fares:
            return {"route": r["id"], "error": "brak lotów w tym miesiącu"}

        best = min(fares, key=lambda f: f["price"])
        prev = db.query("SELECT min_price FROM fl_prices WHERE route_id=? ORDER BY id DESC LIMIT 1", (r["id"],))

        db.execute(
            "INSERT INTO fl_prices(route_id,min_price,min_date,currency,days_json,source) VALUES(?,?,?,?,?,?)",
            (r["id"], best["price"], best["date"], best["currency"], json.dumps(fares), p.id)
        )

        label = f'{r["origin"]}→{r["dest"]} {r["month"]}'
        fired = []
        if r["threshold"] and best["price"] <= r["threshold"]:
            fired.append(f'cena {best["price"]:.0f} {best["currency"]} ≤ próg {r["threshold"]:.0f}')
        if r["drop_pct"] and prev and prev[0]["min_price"] and best["price"] <= prev[0]["min_price"] * (1 - r["drop_pct"] / 100):
            fired.append(f'spadek z {prev[0]["min_price"]:.0f} do {best["price"]:.0f} (≥{r["drop_pct"]:.0f}%)')
        if force_alert:
            fired.append("alert testowy")

        for why in fired:
            alerts.notify(
                self.id,
                f"✈ {label}: {best['price']:.0f} {best['currency']}",
                f"{why}. Najtaniej {best['date']} (źródło: {p.name})."
            )

        return {"route": r["id"], "min": best["price"], "date": best["date"], "currency": best["currency"], "alerts": fired}

    def check_all(self):
        routes = db.query("SELECT * FROM fl_routes WHERE active=1")
        return [self.check_route(r) for r in routes]

    def jobs(self):
        return [
            ("check_all", INTERVAL_H * 3600, self.check_all),
            ("fly4free_rss", 2 * 3600, fetch_and_save_fly4free)
        ]

    def status(self):
        return {
            "providers": [p.status() for p in PROVIDERS.values()],
            "every_h": INTERVAL_H,
            "airports": PL_AIRPORTS,
            "agent_tools": [t.name for t in FLIGHT_TOOLS]
        }

    def run(self, session: str, msg: str) -> dict:
        """Pętla konwersacyjna Agenta Łowcy Lotów."""
        mem = db.query("SELECT role, content FROM fl_memory WHERE session=? ORDER BY id DESC LIMIT 10", (session,))[::-1]
        db.execute("INSERT INTO fl_memory(session, role, content) VALUES(?, 'user', ?)", (session, msg))

        if os.environ.get("LLM_API_KEY"):
            try:
                agent = get_flight_agent()
                agent_res = agent.run(msg, history=mem)
                db.execute("INSERT INTO fl_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, agent_res.answer))
                return {
                    "answer": agent_res.answer,
                    "steps": agent_res.steps,
                    "paused": agent_res.paused,
                    "pause_reason": agent_res.pause_reason
                }
            except Exception as e:
                alerts.notify(self.id, "Błąd Agenta Łowcy Lotów", str(e)[:200])

        # Tryb awaryjny / bez klucza
        msg_l = msg.lower()
        trace = []
        if "alert" in msg_l or "monitoruj" in msg_l:
            routes = tool_price_alert_list()
            ans = f"📋 **Twoje aktywne alerty cenowe ({routes['count']})**:\n"
            for a in routes["alerts"]:
                r = a["route"]
                lp = a.get("latest_price")
                ans += f"• {r['origin']} ➔ {r['dest']} ({r['month']}): min {lp['min_price'] if lp else '?'} PLN\n"
            trace.append({"tool": "price_alert_list", "result_summary": f"{routes['count']} tras"})
        elif "okazj" in msg_l or "fly4free" in msg_l:
            deals = tool_fly4free_search(limit=5)
            ans = f"🔥 **Ostatnie okazje Fly4free ({len(deals['deals'])})**:\n"
            for d in deals["deals"]:
                ans += f"• [{d['title']}]({d['link']}) — {d.get('price','')}\n"
            trace.append({"tool": "fly4free_search", "result_summary": f"{len(deals['deals'])} okazji"})
        else:
            ans = (
                "✈ Cześć! Jestem **Łowca Lotów** — Twój agent podróżniczy.\n\n"
                "Mogę wyszukiwać tanie loty Ryanair z polskich lotnisk, sprawdzać okazje Fly4free oraz ustawiać alerty cenowe.\n"
                "O co chcesz zapytać? (np. *Znajdź loty z Modlina do Barcelony w grudniu 2026*)"
            )

        db.execute("INSERT INTO fl_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, ans))
        return {"answer": ans, "steps": trace}

    def init(self, app):
        router = APIRouter(prefix="/api/flights", tags=["flights"])

        @router.post("/chat")
        def chat(req: FlightChatRequest):
            try:
                return self.run(req.session or "default", req.message)
            except Exception as e:
                raise HTTPException(status_code=502, detail=str(e)[:300])

        @router.get("/history")
        def history(session: str = "default"):
            return db.query("SELECT role, content, created FROM fl_memory WHERE session=? ORDER BY id ASC", (session,))

        @router.get("/routes")
        def routes():
            out = db.query("SELECT * FROM fl_routes ORDER BY id DESC")
            for r in out:
                r["history"] = db.query("SELECT checked,min_price,min_date,currency FROM fl_prices WHERE route_id=? ORDER BY id", (r["id"],))
                last = db.query("SELECT days_json FROM fl_prices WHERE route_id=? ORDER BY id DESC LIMIT 1", (r["id"],))
                r["days"] = json.loads(last[0]["days_json"]) if last and last[0]["days_json"] else []
            return out

        @router.post("/routes")
        def add(payload: RouteCreate):
            o = payload.origin.upper().strip()
            d = payload.dest.upper().strip()
            if o not in PL_AIRPORTS:
                raise HTTPException(status_code=400, detail="Lotnisko wylotu musi być w Polsce: " + ", ".join(PL_AIRPORTS))

            rid = db.execute(
                "INSERT INTO fl_routes(origin,dest,month,provider,threshold,drop_pct) VALUES(?,?,?,?,?,?)",
                (o, d, payload.month, payload.provider, payload.threshold, payload.drop_pct)
            )
            r = db.query("SELECT * FROM fl_routes WHERE id=?", (rid,))[0]
            try:
                res = self.check_route(r)
            except Exception as e:
                res = {"error": str(e)}
            return {"id": rid, "check": res}

        @router.delete("/routes/{rid}")
        def rm(rid: int):
            db.execute("DELETE FROM fl_routes WHERE id=?", (rid,))
            db.execute("DELETE FROM fl_prices WHERE route_id=?", (rid,))
            return {"ok": 1}

        @router.post("/routes/{rid}/check")
        def chk(rid: int, test: bool = Query(False)):
            rows = db.query("SELECT * FROM fl_routes WHERE id=?", (rid,))
            if not rows:
                raise HTTPException(status_code=404, detail="Trasa nie znaleziona")
            try:
                return self.check_route(rows[0], force_alert=test)
            except Exception as e:
                raise HTTPException(status_code=502, detail=str(e))

        @router.get("/deals")
        def deals(limit: int = 30):
            return db.query("SELECT * FROM fly4free_deals ORDER BY id DESC LIMIT ?", (limit,))

        @router.post("/deals/refresh")
        def refresh_deals():
            try:
                return fetch_and_save_fly4free()
            except Exception as e:
                raise HTTPException(status_code=502, detail=str(e))

        @router.get("/status")
        def st():
            return self.status()

        app.include_router(router)

register(FlightBot())
