"""Testy darmowych narzędzi bota Dziennego (Faza 1 — bez klucza):
- Open-Meteo (pogoda)
- NBP (kursy walut)
- Wikipedia REST (streszczenia)
- Fetch + BeautifulSoup
- Pamięć rozmów (daily_memory)
"""
import pytest
from bots.daily.bot import get_weather, get_nbp_rate, get_wikipedia, DailyBot
from core import db

def test_daily_weather_open_meteo():
    w = get_weather("Warszawa")
    assert w is not None
    assert "Warszaw" in w["city"]
    assert "temperature" in w
    assert "condition" in w
    assert "Open-Meteo" in w["source"]

def test_daily_nbp_currency_rate():
    nbp = get_nbp_rate("EUR")
    assert nbp is not None
    assert nbp["code"] == "EUR"
    assert float(nbp["mid"]) > 3.0
    assert "effectiveDate" in nbp

def test_daily_wikipedia_summary():
    wiki = get_wikipedia("Księżyc")
    assert wiki is not None
    assert "extract" in wiki
    assert len(wiki["extract"]) > 30
    assert "Księżyc" in wiki["title"]

def test_daily_chat_memory_and_response():
    bot = DailyBot()
    session_id = "test-session-live-1"

    # Wyczyść poprzednie
    db.execute("DELETE FROM daily_memory WHERE session=?", (session_id,))

    # Pytanie 1: pogoda
    resp1 = bot.run(session_id, "Jaka jest pogoda w Gdańsku?")
    assert "answer" in resp1
    assert "Gdańsk" in resp1["answer"] or "Prognoza" in resp1["answer"]

    # Pytanie 2: kurs euro
    resp2 = bot.run(session_id, "Jaki jest kurs euro?")
    assert "answer" in resp2
    assert "EUR" in resp2["answer"] or "kurs" in resp2["answer"].lower()

    # Sprawdź czy obie wiadomości są w pamięci sesji
    history = db.query("SELECT role, content FROM daily_memory WHERE session=? ORDER BY id ASC", (session_id,))
    assert len(history) == 4  # 2 user + 2 assistant
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "user"
    assert history[3]["role"] == "assistant"
