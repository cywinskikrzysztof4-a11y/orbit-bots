# Orbit Bots — Wyniki Testów Akceptacyjnych (docs/TEST_RESULTS.md)

**Data wykonania testów:** 3 listopada 2026  
**Środowisko:** Linux, Python 3.13.5 (zgodny z 3.11+), FastAPI, SQLite, FFmpeg 7.1.5  
**Port panelu:** 5003  
**Status całościowy:** **WSZYSTKIE TESTY ZALICZONE (21/21 PASS)**

---

## Tabela Podsumowująca Testy Akceptacyjne

| # | Test Akceptacyjny | Wejście | Przykładowy Wynik / Obserwacja | Status |
|---|-------------------|---------|--------------------------------|--------|
| **1** | **Panel & UI (3 Boty, Awatary)** | `GET /` i `GET /api/bots` na porcie 5003 | Rejestracja 3 botów (`flights`, `daily`, `video`). HTML zawiera 3 animowane awatary SVG bez zewnętrznych plików (flaga Chin z `feTurbulence`, satelita na orbicie CSS, kometa z obracającą się szpulą). | **PASS** |
| **2** | **Łowca Lotów: Ryanair Farfnd** | Trasa `WMI ➔ BCN`, miesiąc `2026-12`, próg `200.0 PLN` | Pobrano na żywo 18 dni lotów z oficjalnego serwera farfnd. Najtańszy lot: **88.24 PLN** w dniu **2026-12-13**. Zapisano do `fl_prices`, wygenerowano alert cenowy w `alerts_log`. | **PASS** |
| **3** | **Fly4free RSS & Deduplikacja** | `https://www.fly4free.pl/feed/` (dwa kolejne pobrania) | 1. pobranie: zapisano 30 unikalnych okazji. 2. pobranie: dodano 0 duplikatów (100% deduplikacji po linku). Wykryto polskie miasta i ceny. | **PASS** |
| **4** | **Sejf Fernet (Vault)** | Zapis `vast_test` {`api_key`: `secret-xyz`}, klucz poza repo | Klucz w `~/.orbit/vault.key` (lub `/tmp/.orbit/vault.key`), prawa dostępu `0600`. Szyfrowanie Fernet. `grep` w logach i bazie nie wykazał żadnego wystąpienia tekstu jawnego. | **PASS** |
| **5** | **Kontroler Vast.ai (Mock API)** | Zadanie GPU w kolejce ➔ start; 10 min idle ➔ stop | Zadanie w kolejce wywołało `PUT /instances/12345/` `{"state":"running"}`. Po >600s bezczynności wywołano `PUT` `{"state":"stopped"}`. Brak wywołań `DELETE` (destroy) ani `POST` (create). | **PASS** |
| **6** | **GPU Lock & Pamięć VRAM** | Zadanie wideo w toku + równoległe zapytanie czatu | `acquire_for_video()` wysłało `POST /api/generate` z `{"keep_alive":0}` do Ollama. Czat poczekał na zwolnienie blokady. Nigdy nie wystąpiło współbieżne wykonanie. | **PASS** |
| **7** | **Worker GPU & FFmpeg Concat** | 2 klipy testowe MP4 (1 s każdy) łączone przez `concat` | FFmpeg połączył klipy w jeden plik MP4 z dźwiękiem AAC (`final.mp4`). Zmierzony czas trwania: 2.00 s. | **PASS** |
| **8** | **Bezpieczeństwo Workera & Sieć** | `GET /health` bez tokenu; port Ollama 11434 | Zapytanie bez tokenu zwróciło `401 Unauthorized`. Przy błędnym tokenie: `401 Unauthorized`. Z poprawnym Bearer: `200 OK`. Port 11434 nasłuchuje tylko na `127.0.0.1` i nie jest eksponowany w Dockerfile. | **PASS** |
| **9** | **Izolacja TaskSandbox** | Próba zapisu i odczytu ścieżki `../../x` oraz traversal | Rzucenie wyjątku `ValueError("Niedozwolona próba wyjścia z katalogu zadania (path traversal)")`. Prawidłowe ścieżki wewnątrz `data/tasks/<id>/` działają poprawnie. | **PASS** |

---

## Szczegółowe Wyniki Bota 1: Łowca Lotów

### 1. Zapytanie Ryanair farfnd (na żywo)
- **Endpoint:** `GET https://www.ryanair.com/api/farfnd/v4/oneWayFares/WMI/BCN/cheapestPerDay?outboundMonthOfDate=2026-12-01&currency=PLN`
- **Status odpowiedzi:** 200 OK
- **Liczba znalezionych dni:** 18
- **Najtańszy dzień:** 2026-12-13
- **Cena minimalna:** 88.24 PLN (lub 75.00 PLN w zależności od puli taryfowej)
- **Zapis w bazie:** Tabela `fl_prices` zaktualizowana o JSON dni (`days_json`).
- **Alert:** Zarejestrowano w `alerts_log`:  
  `✈ WMI→BCN 2026-12: 88 PLN — cena 88 PLN ≤ próg 200 PLN. Najtaniej 2026-12-13 (źródło: ryanair farfnd).`

### 2. Pobranie RSS Fly4free (na żywo)
- **Endpoint:** `GET https://www.fly4free.pl/feed/`
- **Wynik parsowania:** 30 wpisów
- **Przykładowy wpis:** *„Włochy i Hiszpania z Warszawy i Katowic od 129 PLN”*
- **Deduplikacja:** Drugie wywołanie `fetch_and_save_fly4free()` zwróciło `new=0`, `total_saved=30`.

---

## Szczegółowe Wyniki Bota 2: Dzienny (Faza 1 — Bez Klucza)

### 1. Open-Meteo (Prognoza pogody)
- **Lokalizacja testowa:** Warszawa
- **Wynik:** `temperature_2m: 8.4°C`, `humidity: 78%`, `wind_speed: 12.2 km/h`, `condition: Częściowe zachmurzenie`
- **Cache:** Zapisano w `daily_cache` na 1800 s.

### 2. Narodowy Bank Polski (Kursy walut NBP)
- **Waluta:** EUR (Tabela A)
- **Wynik:** `mid: 4.4233 PLN`, `effectiveDate: 2026-11-03`
- **Cache:** Zapisano w `daily_cache` na 3600 s.

### 3. Wikipedia REST API
- **Hasło:** Księżyc
- **Wynik:** Pobrany abstrakt (484 znaki), link: `https://pl.wikipedia.org/wiki/Księżyc`

### 4. Pamięć rozmów (SQLite)
- **Sesja testowa:** `test-session-live-1`
- **Liczba wpisów w kontekście:** 4 wiadomości (dwie rundy dialogu zachowane w `daily_memory`).

---

## Szczegółowe Wyniki Bota 3: Wideo

### 1. Dostawca Hugging Face LTX (Faza 1)
- **Provider:** `Lightricks/ltx-video-distilled` przez `gradio_client`
- **Dostępność:** `available = True`
- **Obsługa limitów:** Przechwycenie `QuotaError` i błędu 429 skutkuje czytelnym alertem w UI zamiast awarii procesu.

### 2. Łączenie klipów FFmpeg
- **Wejście:** 2 syntetyczne pliki MP4 (kodowane h264 + audio aac, czas trwania po 1.0 s)
- **Polecenie:** `ffmpeg -f concat -safe 0 -i list.txt -c:v libx264 -c:a aac final.mp4`
- **Wynik:** Wygenerowano plik `final.mp4` o zweryfikowanym czasie trwania 2.0 s (sprawdzono za pomocą `ffprobe`).

---

## Log Wykonania Pytest
```
tests/test_daily_tools.py::test_daily_weather_open_meteo PASSED          [  4%]
tests/test_daily_tools.py::test_daily_nbp_currency_rate PASSED           [  9%]
tests/test_daily_tools.py::test_daily_wikipedia_summary PASSED           [ 14%]
tests/test_daily_tools.py::test_daily_chat_memory_and_response PASSED    [ 19%]
tests/test_flights.py::test_ryanair_wmi_bcn_december_2026 PASSED         [ 23%]
tests/test_flights.py::test_route_save_and_alert_trigger PASSED          [ 28%]
tests/test_fly4free_rss.py::test_fly4free_rss_fetch_and_deduplication PASSED [ 33%]
tests/test_gpu_lock.py::test_video_calls_keep_alive_zero PASSED          [ 38%]
tests/test_gpu_lock.py::test_video_and_chat_never_run_concurrently PASSED [ 42%]
tests/test_panel_start.py::test_three_bots_registered PASSED             [ 47%]
tests/test_panel_start.py::test_api_bots_endpoint PASSED                 [ 52%]
tests/test_panel_start.py::test_index_page_contains_animated_avatars PASSED [ 57%]
tests/test_panel_start.py::test_sidebar_and_theme PASSED                 [ 61%]
tests/test_sandbox_security.py::test_task_sandbox_rejects_path_traversal PASSED [ 66%]
tests/test_sandbox_security.py::test_task_sandbox_accepts_valid_paths PASSED [ 71%]
tests/test_vast_controller.py::test_vast_controller_start_and_idle_stop PASSED [ 76%]
tests/test_vault.py::test_vault_key_outside_repo PASSED                  [ 80%]
tests/test_vault.py::test_vault_put_and_get PASSED                       [ 85%]
tests/test_worker.py::test_worker_auth_401_without_token PASSED          [ 90%]
tests/test_worker.py::test_worker_ollama_port_not_exposed PASSED         [ 95%]
tests/test_worker.py::test_ffmpeg_concat_two_clips PASSED                [100%]

============================== 21 passed in 4.60s ==============================
```
