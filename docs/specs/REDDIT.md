# Specyfikacja: dostawca Reddit API

## Status i warunki (sprawdzone 3.11.2026)
- Od 11.11.2025 obowiązuje **Responsible Builder Policy**. Samoobsługowe tworzenie dostępu do API zamknięto, a każdy nowy token OAuth wymaga **zatwierdzenia przez Reddit** ([ogłoszenie](https://www.reddit.com/r/redditdev/comments/1oug31u/), [polityka](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)).
- **31.10.2026 Reddit przestał przyjmować nowe wnioski o publiczny dostęp do API.** Od 12.01.2027 zacznie odcinać niezarejestrowane aplikacje, a w marcu 2027 publiczne API zostanie zamknięte dla wszystkich i zastąpione platformą Devvit ([harmonogram](https://www.reddit.com/r/redditdev/comments/1wubcvf/)).
- Darmowy limit (dla zatwierdzonych): **100 zapytań na minutę na client_id**, średnio w oknie 10 min. Nagłówki `X-Ratelimit-Used/Remaining/Reset`. Tylko użytek niekomercyjny. Zakaz trenowania modeli AI na danych Reddita i wnioskowania o wrażliwych cechach użytkowników.
- Ruch bez OAuth jest blokowany. Z naszego serwera publiczny `/r/flights/new.json` zwraca **403**, więc fallback na publiczny JSON w praktyce nie działa.
- Wniosek: nowy użytkownik **prawdopodobnie nie dostanie już klucza**. Moduł budujemy, ale z domyślnym statusem „brak klucza”. Jeśli użytkownik ma starą, zatwierdzoną aplikację typu *script*, może jej użyć.

## Implementacja
- Sejf `reddit` = `{client_id, client_secret, username, password}` albo env `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`.
- Aplikacja *script* (tworzona na https://www.reddit.com/prefs/apps, jeśli jeszcze dostępne): `POST https://www.reddit.com/api/v1/access_token` z Basic auth (client_id:secret) i `grant_type=password&username=…&password=…` albo `grant_type=client_credentials` (tylko odczyt).
- Odczyt: `GET https://oauth.reddit.com/r/{flights,Polska,TravelHacks,shoestring}/new?limit=100`, `Authorization: bearer <token>`.
- User-Agent wymagany w formacie: `linux:orbit-bots:0.1 (by /u/<login>)`.
- Throttling: najwyżej 1 zapytanie na 2 s, przestrzeganie `X-Ratelimit-Remaining`, backoff przy 429. Zapisuj tylko ID, tytuł, link, tekst i datę.
- Fallback publiczny JSON: najwyżej 1 zapytanie na 10 s, przy 403 automatycznie wyłączony na 24 h.

## Pozostałe źródła forów (FORUM_PLAN.md)
- Fly4free.pl RSS: `https://www.fly4free.pl/feed/` (HTTP 200, działa, bez klucza). Najlepsze źródło polskich okazji.
- Wykop: oficjalne API v3 wymaga klucza aplikacji (dev.wykop.pl). Status „brak klucza”.
- X: oficjalne API (płatne lub konektor). Status „brak klucza”.
