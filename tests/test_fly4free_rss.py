"""Test akceptacyjny 3:
Fly4free RSS zapisuje co najmniej 10 wpisów bez duplikatów po dwóch pobraniach.
"""
import pytest
from core import db
from bots.flights.forums import fetch_and_save_fly4free, fly4free_rss

def test_fly4free_rss_fetch_and_deduplication():
    # Wyczyść poprzednie wpisy dla czystości testu
    db.execute("DELETE FROM fly4free_deals")

    # Pierwsze pobranie
    res1 = fetch_and_save_fly4free()
    total1 = res1["total_saved"]
    assert total1 >= 10, f"Oczekiwano co najmniej 10 wpisów z RSS Fly4free, pobrano {total1}"

    # Drugie pobranie z tego samego źródła
    res2 = fetch_and_save_fly4free()
    total2 = res2["total_saved"]
    new_in_second = res2["new"]

    # Deduplikacja: drugie pobranie powinno dodać 0 nowych wpisów (lub minimalnie, jeśli coś wpadło w ułamku sekundy)
    assert new_in_second == 0, f"Deduplikacja nie zadziałała: dodano ponownie {new_in_second} wpisów"
    assert total2 == total1, f"Liczba wpisów po drugim pobraniu wzrosła ({total1} -> {total2})"

    # Sprawdź unikalność linków w bazie
    links = db.query("SELECT link, COUNT(*) as c FROM fly4free_deals GROUP BY link HAVING c > 1")
    assert len(links) == 0, f"Znaleziono zduplikowane linki: {links}"
