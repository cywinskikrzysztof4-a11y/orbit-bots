# Specyfikacja: dostawca Amadeus for Developers

## Status (sprawdzone 3.11.2026): Self-Service WYŁĄCZONY
- Amadeus zamknął portal **Self-Service 17 lipca 2026**. Klucze unieważniono, a nowe rejestracje wstrzymano już w marcu 2026 ([PhocusWire, 9.02.2026](https://www.phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers)).
- `developers.amadeus.com` pokazuje teraz tylko **Enterprise API Portal**. Repozytoria `amadeus4dev` na GitHubie są zarchiwizowane.
- Z naszego serwera `test.api.amadeus.com` nie odpowiada (curl: brak połączenia).
- **Nie da się dziś założyć darmowego konta Self-Service.** Jedyna droga to **Amadeus Enterprise**: umowa handlowa, zwykle dla agencji z akredytacją IATA/ARC. Kontakt: https://developers.amadeus.com (sekcja Enterprise / „Contact us”).

## Implementacja (zostawić jako moduł, który działa po podaniu kluczy Enterprise)
- Env / sejf: `AMADEUS_API_KEY`, `AMADEUS_API_SECRET`, `AMADEUS_BASE_URL` (domyślnie `https://test.api.amadeus.com`, a dla Enterprise adres z umowy). Sejf: wpis `amadeus` = `{api_key, api_secret}`.
- OAuth2 client credentials: `POST {BASE}/v1/security/oauth2/token`, `Content-Type: application/x-www-form-urlencoded`, `grant_type=client_credentials&client_id=…&client_secret=…`. Odpowiedź: `access_token`, `expires_in` (~1799 s). Token trzymaj w cache do wygaśnięcia.
- Flight Offers Search: `GET /v2/shopping/flight-offers?originLocationCode=WAW&destinationLocationCode=BCN&departureDate=2026-12-13&adults=1&currencyCode=PLN&max=20`.
- Flight Cheapest Date Search: `GET /v1/shopping/flight-dates?origin=WAW&destination=BCN&oneWay=true` (dane z cache, ograniczone pokrycie).
- Flight Inspiration Search: `GET /v1/shopping/flight-destinations?origin=WAW&maxPrice=500`.
- Nagłówek `Authorization: Bearer <token>`. Obsłuż 401 (odśwież token), 429 (backoff) i brak DNS (status „wycofane”).
- Status w UI: „wycofane (Self-Service zamknięty 17.07.2026)” i do tego „brak klucza”, dopóki klucze nie są skonfigurowane.

## Alternatywy oficjalne (wymagania kluczy)
| Dostawca | Klucz | Jak zdobyć | Uwagi |
|---|---|---|---|
| Travelpayouts / Aviasales Data API | `TRAVELPAYOUTS_TOKEN` | darmowe konto partnera: travelpayouts.com → Profile → API token | ceny z cache wyszukiwań (do ok. 48 h), nie na żywo. `GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates` |
| Duffel | `DUFFEL_TOKEN` (`duffel_test_…`) | app.duffel.com, tryb testowy bez karty | test zwraca fikcyjne linie. Realne ceny dopiero w trybie live (weryfikacja firmy, opłaty za rezerwacje) |
| Kiwi.com Tequila | `KIWI_API_KEY` | tequila.kiwi.com, tylko partnerzy po akceptacji | publiczne rejestracje zamknięte (stan wiedzy, do weryfikacji przez użytkownika) |
| Ryanair farfnd | brak | — | **NIEOFICJALNE**, publiczny endpoint strony. Działa (3.11.2026), używać rzadko |

Stan Travelpayouts, Duffel i Kiwi pochodzi z wiedzy ogólnej i nie był dziś weryfikowany na stronach. Przed rejestracją sprawdź aktualne warunki.
