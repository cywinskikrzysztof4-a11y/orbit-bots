# Plan modułu analizy forów (Łowca lotów)
**Źródła:** Fly4free.pl RSS (działa, bez klucza) · Reddit r/flights, r/Polska, r/TravelHacks przez oficjalne OAuth (patrz specs/REDDIT.md; nowe klucze niedostępne) · Wykop API v3 (klucz z dev.wykop.pl) · X przez oficjalne API lub konektor.
**Pozyskanie:** tylko RSS i oficjalne API. Najwyżej 1 zapytanie na 2–10 s na źródło, własny User-Agent, przestrzeganie robots.txt, zero obchodzenia blokad. Deduplikacja po URL/ID w tabeli `forum_posts`.
**LLM:** wsadowo po 20 postów do Gemini (klucz z `/workspace/monitor-polityczny/.gemini_key`, nigdy nie logowany) albo do lokalnego Dolphina. Prompt każe wyodrębnić oferty jako JSON.
**Schemat oferty (`forum_deals`):** `{origin, destination, airline, price, currency, travel_dates[], booking_deadline, url, source, confidence, summary_pl, created}`.
**Wnioski:** oferty z PL i confidence ≥ 0,6 łączymy z trasami użytkownika i wysyłamy alert „okazja z forum”. Do tego dzienne streszczenie trendów (najczęstsze kierunki, linie, średnie ceny).
**Harmonogram:** RSS co 2 h, Reddit co 6 h, streszczenie raz dziennie o 8:00 (Europe/Warsaw).
**Opcjonalnie, Playwright:** tylko dla stron wymagających logowania i tylko po zgodzie użytkownika zapisanej w bazie (strona, zakres, data). Dane logowania pochodzą z sejfu, a sesja jest osobna dla każdej strony. Bez captcha i bez zakupów, sam odczyt.
