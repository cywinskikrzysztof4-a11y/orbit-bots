"""Łowca lotów — śledzenie cen tras z polskich lotnisk + alerty (próg / spadek o X%).
Ceny z Ryanair farfnd (etykieta „NIEOFICJALNE”, zapytania co 6 h).
Okazje z RSS Fly4free.pl (co 2 h, deduplikacja po linku).
"""
import os, json
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from core import db, alerts
from core.registry import BotBase, register
from .providers import PROVIDERS
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
""")

INTERVAL_H = float(os.environ.get("ORBIT_FLIGHTS_EVERY_H", "6"))

class RouteCreate(BaseModel):
    origin: str
    dest: str
    month: str
    provider: str = "ryanair"
    threshold: float | None = None
    drop_pct: float | None = None

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
            "airports": PL_AIRPORTS
        }

    def init(self, app):
        router = APIRouter(prefix="/api/flights", tags=["flights"])

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
