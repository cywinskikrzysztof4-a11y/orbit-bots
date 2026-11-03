"""Test akceptacyjny 1:
Panel startuje na :5003 i pokazuje 3 boty z animowanymi awatarami (flaga Chin, satelita, kometa z taśmą).
"""
import pytest
from fastapi.testclient import TestClient
from app import app
from core.registry import BOTS

def test_three_bots_registered():
    assert "flights" in BOTS, "Brak bota 'flights' w BOTS"
    assert "daily" in BOTS, "Brak bota 'daily' w BOTS"
    assert "video" in BOTS, "Brak bota 'video' w BOTS"

def test_api_bots_endpoint():
    client = TestClient(app)
    r = client.get("/api/bots")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    bot_ids = {b["id"] for b in data}
    assert bot_ids == {"flights", "daily", "video"}

def test_index_page_contains_animated_avatars():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    html = r.text

    # 1. Łowca lotów: flaga Chin z feTurbulence
    assert "china-flag-svg" in html, "Brak klasy china-flag-svg w HTML"
    assert "feTurbulence" in html, "Brak feTurbulence dla falującej flagi"
    assert "baseFrequency" in html, "Brak animacji baseFrequency"
    assert "#DE2910" in html, "Brak koloru czerwonego tła flagi Chin (#DE2910)"
    assert "#FFDE00" in html, "Brak koloru złotych gwiazd flagi Chin (#FFDE00)"

    # 2. Dzienny: satelita na orbicie
    assert "satellite-svg" in html, "Brak klasy satellite-svg w HTML"
    assert "orbit-sat-group" in html, "Brak grupy orbity satelity"

    # 3. Wideo: kometa z taśmą filmową
    assert "comet-svg" in html, "Brak klasy comet-svg w HTML"
    assert "spinning-reel" in html or "comet-reel-group" in html, "Brak szpuli filmowej komety"

def test_sidebar_and_theme():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "cosmic-theme" in html
    assert "vastTile" in html
