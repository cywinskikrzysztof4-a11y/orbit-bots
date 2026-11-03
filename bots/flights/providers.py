"""Dostawcy cen lotów. Każdy zwraca listę dict(date, price, currency, dep, arr, flight, source).
OFFICIAL=True -> oficjalne API z kluczem; False -> publiczny, NIEOFICJALNY endpoint (oznaczony w UI)."""
import requests, time
from core import vault
UA = {"User-Agent": "OrbitBots/0.1 (personal price tracker; low rate)", "Accept": "application/json"}

class Provider:
    id = ""; name = ""; official = True; needs = []; howto = ""
    def configured(self): return True
    def status(self):
        return {"id": self.id, "name": self.name, "official": self.official,
                "state": "ok" if self.configured() else "brak klucza", "needs": self.needs, "howto": self.howto}

class Ryanair(Provider):
    id = "ryanair"; name = "Ryanair farfnd (publiczny, NIEOFICJALNY)"; official = False
    howto = "Bez klucza. Publiczny endpoint strony ryanair.com, bez gwarancji i umowy — używany rzadko (raz na kilka godzin)."
    def month(self, o, d, month, currency="PLN"):
        r = requests.get(f"https://www.ryanair.com/api/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay",
                         params={"outboundMonthOfDate": f"{month}-01", "currency": currency}, headers=UA, timeout=30)
        r.raise_for_status(); out = []
        for f in r.json().get("outbound", {}).get("fares", []):
            if f.get("price") and not f.get("unavailable") and not f.get("soldOut"):
                out.append(dict(date=f["day"], price=float(f["price"]["value"]), currency=f["price"]["currencyCode"],
                                dep=f.get("departureDate"), arr=f.get("arrivalDate"), flight="FR", source=self.id))
        return out

class Amadeus(Provider):
    id = "amadeus"; name = "Amadeus Self-Service (oficjalne)"; needs = ["AMADEUS_API_KEY", "AMADEUS_API_SECRET"]
    howto = ("WYŁĄCZONE PRZEZ AMADEUS: portal Self-Service zamknięto 17.07.2026, klucze unieważniono, nowych rejestracji brak. "
             "Dostęp tylko przez Amadeus Enterprise (umowa handlowa). Kod zostawiony dla zgodności: klucze w sejfie 'amadeus' (api_key, api_secret) lub env.")
    base = "https://test.api.amadeus.com"
    def _k(self): return vault.secret("amadeus", "api_key", "AMADEUS_API_KEY"), vault.secret("amadeus", "api_secret", "AMADEUS_API_SECRET")
    def configured(self): return all(self._k())
    def status(self):
        s = super().status(); s["state"] = "wycofane (decommissioned 17.07.2026)" + ("" if self.configured() else " · brak klucza"); return s
    def _token(self):
        k, s = self._k()
        r = requests.post(self.base + "/v1/security/oauth2/token", data={"grant_type": "client_credentials", "client_id": k, "client_secret": s}, timeout=20)
        r.raise_for_status(); return r.json()["access_token"]
    def month(self, o, d, month, currency="PLN"):
        t = self._token()  # Flight Cheapest Date Search
        r = requests.get(self.base + "/v1/shopping/flight-dates", params={"origin": o, "destination": d, "oneWay": "true"},
                         headers={"Authorization": "Bearer " + t}, timeout=30); r.raise_for_status()
        return [dict(date=x["departureDate"], price=float(x["price"]["total"]), currency=currency, dep=None, arr=None, flight="", source=self.id)
                for x in r.json().get("data", []) if x["departureDate"].startswith(month)]

class Travelpayouts(Provider):
    id = "travelpayouts"; name = "Travelpayouts / Aviasales Data API (oficjalne)"; needs = ["TRAVELPAYOUTS_TOKEN"]
    howto = ("Darmowe konto partnera na travelpayouts.com → Profile → API token. Dane to ceny z cache wyszukiwań (do ~48h), "
             "nie na żywo. Zapisz w sejfie 'travelpayouts' (token) lub env TRAVELPAYOUTS_TOKEN.")
    def configured(self): return bool(vault.secret("travelpayouts", "token", "TRAVELPAYOUTS_TOKEN"))
    def month(self, o, d, month, currency="PLN"):
        r = requests.get("https://api.travelpayouts.com/aviasales/v3/prices_for_dates", params=dict(
            origin=o, destination=d, departure_at=month, one_way="true", currency=currency.lower(), sorting="price", limit=100,
            token=vault.secret("travelpayouts", "token", "TRAVELPAYOUTS_TOKEN")), timeout=30); r.raise_for_status()
        return [dict(date=x["departure_at"][:10], price=float(x["price"]), currency=currency, dep=x["departure_at"], arr=None,
                     flight=f'{x.get("airline","")}{x.get("flight_number","")}', source=self.id) for x in r.json().get("data", [])]

class Duffel(Provider):
    id = "duffel"; name = "Duffel (oficjalne, tryb testowy)"; needs = ["DUFFEL_TOKEN"]
    howto = ("Rejestracja na app.duffel.com (bez karty w trybie testowym) → Developers → Access tokens → token 'duffel_test_…'. "
             "UWAGA: tryb testowy zwraca linie testowe (Duffel Airways), realne ceny wymagają trybu live (weryfikacja firmy). "
             "Sejf 'duffel' (token) lub env DUFFEL_TOKEN.")
    def configured(self): return bool(vault.secret("duffel", "token", "DUFFEL_TOKEN"))
    def month(self, o, d, month, currency="PLN"):
        raise NotImplementedError("Duffel szuka per dzień (POST /air/offer_requests) — do dodania po zdobyciu tokenu.")

class Kiwi(Provider):
    id = "kiwi"; name = "Kiwi.com Tequila (oficjalne)"; needs = ["KIWI_API_KEY"]
    howto = ("Tequila od 2024 nie przyjmuje publicznych rejestracji — tylko partnerzy po akceptacji (tequila.kiwi.com). "
             "Gdy dostaniesz klucz: sejf 'kiwi' (api_key) lub env KIWI_API_KEY.")
    def configured(self): return bool(vault.secret("kiwi", "api_key", "KIWI_API_KEY"))
    def month(self, o, d, month, currency="PLN"):
        y, m = map(int, month.split("-")); import calendar; last = calendar.monthrange(y, m)[1]
        r = requests.get("https://api.tequila.kiwi.com/v2/search", headers={"apikey": vault.secret("kiwi", "api_key", "KIWI_API_KEY")},
                         params=dict(fly_from=o, fly_to=d, date_from=f"01/{m:02d}/{y}", date_to=f"{last}/{m:02d}/{y}", curr=currency, one_for_city=0, limit=200), timeout=30)
        r.raise_for_status()
        return [dict(date=x["local_departure"][:10], price=float(x["price"]), currency=currency, dep=x["local_departure"], arr=x["local_arrival"],
                     flight=",".join(s["airline"] for s in x["route"]), source=self.id) for x in r.json().get("data", [])]

PROVIDERS = {p.id: p for p in [Ryanair(), Amadeus(), Travelpayouts(), Duffel(), Kiwi()]}
