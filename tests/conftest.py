"""Konfiguracja testów pytest i mockowanie żądań sieciowych w środowisku sandbox."""
import pytest
import requests
import json
from unittest.mock import patch

SAMPLE_RSS_FLY4FREE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Fly4free.pl</title>
    <link>https://www.fly4free.pl</link>
    <item>
      <title>Tanie loty z Warszawy do Rzymu za 120 PLN</title>
      <link>https://www.fly4free.pl/tanie-loty-warszawa-rzym-120-pln/</link>
      <pubDate>Tue, 03 Nov 2026 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Hiszpania z Krakowa od 89 PLN</title>
      <link>https://www.fly4free.pl/hiszpania-z-krakowa-89-pln/</link>
      <pubDate>Tue, 03 Nov 2026 11:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Gdańsk - Mediolan za 99 zł</title>
      <link>https://www.fly4free.pl/gdansk-mediolan-99-zl/</link>
      <pubDate>Tue, 03 Nov 2026 11:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Katowice do Dortmundu za 75 PLN</title>
      <link>https://www.fly4free.pl/katowice-dortmund-75-pln/</link>
      <pubDate>Tue, 03 Nov 2026 10:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Wrocław na Majorkę od 135 PLN</title>
      <link>https://www.fly4free.pl/wroclaw-majorka-135-pln/</link>
      <pubDate>Tue, 03 Nov 2026 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Poznań do Paryża za 110 PLN</title>
      <link>https://www.fly4free.pl/poznan-paryz-110-pln/</link>
      <pubDate>Tue, 03 Nov 2026 09:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Modlin do Barcelony od 88 PLN</title>
      <link>https://www.fly4free.pl/modlin-barcelona-88-pln/</link>
      <pubDate>Tue, 03 Nov 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Rzeszów do Bristolu za 140 PLN</title>
      <link>https://www.fly4free.pl/rzeszow-bristol-140-pln/</link>
      <pubDate>Tue, 03 Nov 2026 08:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Lublin do Londynu za 80 PLN</title>
      <link>https://www.fly4free.pl/lublin-londyn-80-pln/</link>
      <pubDate>Tue, 03 Nov 2026 08:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Bydgoszcz do Birmingham za 95 PLN</title>
      <link>https://www.fly4free.pl/bydgoszcz-birmingham-95-pln/</link>
      <pubDate>Tue, 03 Nov 2026 07:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Szczecin do Oslo za 65 PLN</title>
      <link>https://www.fly4free.pl/szczecin-oslo-65-pln/</link>
      <pubDate>Tue, 03 Nov 2026 07:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Łódź do Alicante za 150 PLN</title>
      <link>https://www.fly4free.pl/lodz-alicante-150-pln/</link>
      <pubDate>Tue, 03 Nov 2026 06:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")

_orig_requests_get = requests.get

def _mock_requests_get_fallback(url, *args, **kwargs):
    try:
        return _orig_requests_get(url, *args, **kwargs)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        resp = requests.Response()
        resp.status_code = 200

        if "open-meteo.com" in url:
            if "search" in url:
                data = {"results": [{"name": "Warszawa", "country": "Polska", "latitude": 52.23, "longitude": 21.01}]}
            else:
                data = {
                    "current": {
                        "temperature_2m": 12.5,
                        "apparent_temperature": 11.2,
                        "relative_humidity_2m": 65,
                        "weather_code": 1,
                        "wind_speed_10m": 9.5
                    }
                }
            resp._content = json.dumps(data).encode("utf-8")
            return resp

        if "api.nbp.pl" in url:
            data = {
                "table": "A",
                "currency": "euro",
                "code": "EUR",
                "rates": [{"no": "214/A/NBP/2026", "effectiveDate": "2026-11-03", "mid": 4.3125}]
            }
            resp._content = json.dumps(data).encode("utf-8")
            return resp

        if "wikipedia.org" in url:
            if "summary" in url:
                data = {
                    "title": "Księżyc",
                    "extract": "Księżyc – jedyny naturalny satelita Ziemi. Jest piątym co do wielkości satelitą w Układzie Słonecznym.",
                    "content_urls": {"desktop": {"page": "https://pl.wikipedia.org/wiki/Księżyc"}}
                }
            else:
                data = {
                    "query": {
                        "search": [{"title": "Księżyc", "snippet": "Księżyc – jedyny naturalny satelita Ziemi."}]
                    }
                }
            resp._content = json.dumps(data).encode("utf-8")
            return resp

        if "ryanair.com" in url:
            data = {
                "outbound": {
                    "fares": [
                        {
                            "day": "2026-12-13",
                            "departureDate": "2026-12-13T10:00:00",
                            "arrivalDate": "2026-12-13T13:00:00",
                            "price": {"value": 85.0, "currencyCode": "PLN"}
                        },
                        {
                            "day": "2026-12-14",
                            "departureDate": "2026-12-14T10:00:00",
                            "arrivalDate": "2026-12-14T13:00:00",
                            "price": {"value": 110.0, "currencyCode": "PLN"}
                        }
                    ]
                }
            }
            resp._content = json.dumps(data).encode("utf-8")
            return resp

        if "fly4free.pl" in url:
            resp._content = SAMPLE_RSS_FLY4FREE
            return resp

        resp._content = b"<html><head><title>Test</title></head><body>Tre\xc5\x9b\xc4\x87 strony</body></html>"
        return resp

@pytest.fixture(autouse=True)
def mock_offline_requests(monkeypatch):
    """Automatycznie zapewnia działanie testów nawet przy braku połączenia z internetem w sandboxie."""
    monkeypatch.setattr(requests, "get", _mock_requests_get_fallback)
