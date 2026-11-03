"""Test akceptacyjny 2:
Trasa WMI→BCN na grudzień 2026 zapisuje realne ceny (3.11.2026 najtaniej ~75-88 PLN, 13.12),
wykres się rysuje, a próg wyższy od ceny tworzy alert.
"""
import pytest, json
from core import db, alerts
from bots.flights.bot import FlightBot
from bots.flights.providers import Ryanair

def test_ryanair_wmi_bcn_december_2026():
    provider = Ryanair()
    # Pobierz ceny na grudzień 2026
    fares = provider.month("WMI", "BCN", "2026-12")
    assert len(fares) > 0, "Brak lotów z Ryanair farfnd dla WMI->BCN 2026-12"

    best = min(fares, key=lambda f: f["price"])
    print(f"Najtańszy lot WMI->BCN 2026-12: {best['date']} za {best['price']} {best['currency']}")
    assert best["price"] > 0
    assert best["currency"] == "PLN"
    # Sprawdź czy jest data w grudniu 2026
    assert best["date"].startswith("2026-12")

def test_route_save_and_alert_trigger():
    bot = FlightBot()
    # Wyczyść poprzednie testowe dane dla tej trasy
    db.execute("DELETE FROM fl_routes WHERE origin='WMI' AND dest='BCN' AND month='2026-12'")

    # Dodaj trasę z progiem 200 PLN (wyższym niż cena ~75-88 PLN)
    rid = db.execute(
        "INSERT INTO fl_routes(origin, dest, month, provider, threshold, drop_pct) VALUES ('WMI', 'BCN', '2026-12', 'ryanair', 200.0, 10.0)"
    )
    route = db.query("SELECT * FROM fl_routes WHERE id = ?", (rid,))[0]

    # Sprawdź trasę
    res = bot.check_route(route)
    assert res["min"] > 0
    assert res["min"] <= 200.0
    assert len(res["alerts"]) > 0, "Powinien powstać alert, ponieważ cena <= próg 200 PLN"

    # Sprawdź czy ceny zapisały się w bazie fl_prices
    prices = db.query("SELECT * FROM fl_prices WHERE route_id = ? ORDER BY id DESC", (rid,))
    assert len(prices) >= 1
    days = json.loads(prices[0]["days_json"])
    assert len(days) > 0, "fl_prices powienien zawierać days_json z cenami poszczególnych dni"

    # Sprawdź czy alert został zapisany w alerts_log
    al = db.query("SELECT * FROM alerts_log WHERE bot='flights' ORDER BY id DESC LIMIT 5")
    assert any("WMI→BCN" in a["title"] for a in al), "Brak wpisu alertu dla WMI→BCN w alerts_log"
