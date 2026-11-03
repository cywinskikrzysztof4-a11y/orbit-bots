# Orbit Bots: zadanie dla Antigravity (wersja docelowa)

Zbuduj **Orbit Bots**, modułową aplikację w Pythonie 3.11 (FastAPI + SQLite, UI po polsku) z trzema botami. Działa w **architekturze dzielonej**:
- **Panel** (zawsze włączony, mały, np. Render free / dowolny VPS): UI, bot lotów, kolejka zadań, sejf, kontroler Vast.ai.
- **Worker GPU** na **Vast.ai RTX 3090 24 GB** (~0,12 $/h, Kanada): Ollama (Dolphin) i generowanie wideo. Włączany tylko wtedy, gdy w kolejce są zadania GPU.

Katalog `/workspace/orbit` zawiera szkic referencyjny (`core/`, `bots/`). Możesz go użyć albo napisać od nowa.

## Zasady (obowiązkowe)
- Nic nie kupuj i nie loguj się na konta użytkownika bez jego zgody zapisanej w bazie (strona, zakres, data, możliwość cofnięcia).
- Tylko legalne źródła, bez obchodzenia captcha i blokad. Nieoficjalne endpointy mają etykietę **„NIEOFICJALNE”** w UI i dokumentacji, a zapytania do nich idą rzadko.
- Sekrety nigdy nie trafiają do logów, UI ani gita. Brak klucza oznacza status „brak klucza”, nie wyjątek.
- Worker nie wystawia publicznie portu Ollama. Komunikacja panel ↔ worker idzie po HTTPS z tokenem Bearer (`WORKER_TOKEN`).

## Struktura
```
orbit/
  panel/   app.py  core/{registry,db,vault,alerts,queue,scheduler,vast}.py  bots/{flights,daily,video}/  templates/ static/
  worker/  server.py  gpu_lock.py  video/{wan,ltx}.py  Dockerfile  onstart.sh  requirements.txt
  tests/   docs/
```

## Rdzeń (panel)
- `BotBase`: `id, name, avatar, init(app), jobs() -> [(nazwa, co_ile_s, fn)], status() -> dict`. Nowy bot to nowy moduł zarejestrowany w `BOT_MODULES`.
- `vault.py`: Fernet. Klucz w pliku poza repo (`ORBIT_VAULT_KEY`, domyślnie `~/.orbit/vault.key`, chmod 600) albo w env `ORBIT_VAULT_KEY_B64` na Renderze. Wpisy: `vast` {api_key}, `worker` {url, token}, opcjonalnie `travelpayouts`, `reddit`. UI pokazuje tylko nazwy wpisów.
- `queue.py`: tabela `jobs(id, bot, kind, payload_json, status[queued|running|done|error], gpu bool, result_json, created, started, finished)`. Zadania GPU wykonuje worker po kolei (jedno naraz).
- `alerts.py`: `notify(bot, title, body)` zapisuje do SQLite i opcjonalnie wysyła webhook.
- `scheduler.py`: wątek z zadaniami okresowymi.

## Kontroler Vast.ai (`core/vast.py`)
- Używa **oficjalnego API Vast.ai** (`https://console.vast.ai/api/v0/`, nagłówek `Authorization: Bearer <api_key>`) albo CLI `vastai` (`pip install vastai`). Klucz z sejfu `vast`.
- Konfiguracja: `VAST_INSTANCE_ID` (instancja utworzona raz ręcznie, patrz DEPLOY_VAST.md), `VAST_IDLE_MIN` (domyślnie 10).
- Logika co 60 s:
  - kolejka ma zadania GPU, a instancja jest zatrzymana: `vastai start instance <id>` (API: `PUT /instances/<id>/` `{"state":"running"}`), potem czeka na `/health` workera (timeout 10 min)
  - brak zadań GPU od `VAST_IDLE_MIN` minut, a instancja działa: `vastai stop instance <id>` (`{"state":"stopped"}`)
  - nigdy nie wywołuje `create`/`destroy` automatycznie; wszystkie akcje loguje w `jobs_log`
- UI: kafel „Worker GPU” ze stanem (stopped/starting/running), kosztem sesji (czas × $/h) i przyciskami Start/Stop. Ręczny start wymaga potwierdzenia.

## Worker GPU (`worker/`)
- `server.py` (FastAPI, port 8000, Bearer `WORKER_TOKEN`): `GET /health`, `POST /chat`, `POST /video`, `GET /files/<id>.mp4`.
- `gpu_lock.py`: globalny lock, który pozwala na jedno zadanie GPU naraz.
  - Przed wideo: `POST http://127.0.0.1:11434/api/generate {"model":"dolphin3:8b","keep_alive":0}`, potem czeka, aż `ollama ps` będzie pusty.
  - Po wideo: `del pipe; torch.cuda.empty_cache()`.
  - Czat ładuje Ollama automatycznie.
- Dolphin: Ollama z API zgodnym z OpenAI na `127.0.0.1:11434/v1`, model `dolphin3:8b`, nasłuch tylko na localhost.
- Wideo przez **diffusers**, z modelem wybieranym parametrem:
  - `Wan-AI/Wan2.1-T2V-1.3B-Diffusers` (`WanPipeline`): 480p (832×480), 81 klatek, ok. 8 GB VRAM z `enable_model_cpu_offload()`
  - `Lightricks/LTX-Video` (`LTXPipeline`): 704×480, 121 klatek
  - Parametry: prompt, negative_prompt, steps, seed, liczba klipów. Klipy łączy FFmpeg (`concat`) w jeden MP4.
- `Dockerfile`: bazuje na `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`, doinstalowuje ffmpeg, Ollama, diffusers, transformers, accelerate, fastapi i uvicorn.
- `onstart.sh`:
  - uruchamia `ollama serve` (OLLAMA_HOST=127.0.0.1) i `ollama pull dolphin3:8b`, jeśli modelu brak
  - wstępnie pobiera modele HF do `/workspace/hf` (`HF_HOME`), dysk instancji ≥ 60 GB, żeby nie pobierać ich przy każdym starcie
  - startuje `uvicorn server:app --port 8000`
  - dostęp z panelu przez porty Vast z HTTPS albo tunel Cloudflare (`cloudflared tunnel --url http://localhost:8000`); adres trafia do sejfu `worker`

## Bot 1: Łowca lotów (panel, bez GPU)
- Trasy: lotnisko wylotu z PL (WAW, WMI, KRK, KTW, GDN, WRO, POZ, LCJ, RZE, LUZ, SZZ, BZG, IEG, RDO, SZY), cel IATA i miesiąc.
- Źródło cen: Ryanair farfnd **(NIEOFICJALNE)** `GET https://www.ryanair.com/api/farfnd/v4/oneWayFares/{O}/{D}/cheapestPerDay?outboundMonthOfDate=YYYY-MM-01&currency=PLN`. Dni z `price` nie null i `unavailable=false`. Sprawdzaj co 6 h (`ORBIT_FLIGHTS_EVERY_H`).
- Okazje: RSS **Fly4free.pl** `https://www.fly4free.pl/feed/` co 2 h, z deduplikacją po linku. Wpisy z polskim miastem wylotu i ceną dają alert „okazja z forum”. Opcjonalnie streszczenie dnia przez Dolphina (zadanie GPU).
- Tabele `fl_routes(origin, dest, month, threshold, drop_pct)` i `fl_prices(route_id, checked, min_price, min_date, days_json)`.
- Alerty: cena ≤ próg albo spadek ≥ X% względem poprzedniego pomiaru, plus przycisk „alert testowy”.
- UI: lista tras, wykres historii minimum (linia SVG), ceny dzień po dniu (słupki), lista okazji z Fly4free.

## Bot 2: Dzienny (Dolphin)
- Czat po polsku. Pamięć rozmów `daily_memory(session, role, content)` (ostatnie 12 wiadomości jako kontekst), przycisk „Zapomnij”.
- Narzędzia po stronie panelu: `fetch(url)` (requests + BeautifulSoup, cache TTL w `cache(key, value, expires)`), katalog roboczy zadania `data/tasks/<id>/` z walidacją realpath.
- Wywołanie: zadanie GPU `kind=chat`, a worker woła `POST /v1/chat/completions` (`model=dolphin3:8b`, `temperature=0.3`). Gdy worker jest zatrzymany, UI pokazuje „uruchamiam GPU… (ok. 1–3 min)”.

## Bot 3: Wideo
- Formularz: prompt, model (Wan 1.3B / LTX), liczba klipów (1–6), kroki, seed. Zadanie trafia do kolejki, potem są postęp, podgląd MP4 i przycisk „Pobierz”.
- Pliki wynikowe kopiowane do panelu (`data/videos/`), bo worker po zatrzymaniu może stracić dane tymczasowe.

## Wygląd
- Ciemny motyw kosmiczny: gradient `#070b1a → #111a3a`, migoczące gwiazdy w CSS, akcenty `#7c5cff` i `#22d3ee`, karty glass (`backdrop-filter: blur(12px)`), zaokrąglenia 14px, spójne przyciski. Zero zewnętrznych assetów.
- Pasek boczny z trzema botami i **animowanymi awatarami SVG/CSS**:
  1. Łowca lotów: **powiewająca flaga Chin** (tło `#DE2910`, gwiazdy `#FFDE00`, fala przez `feTurbulence` + `feDisplacementMap` z animowanym `baseFrequency`)
  2. Dzienny: **satelita na orbicie** wokół planety (obrót CSS, panele słoneczne)
  3. Wideo: **kometa z taśmą filmową** (szpula z obracającymi się otworami i ogon klatek filmu)
- Pod awatarem: status (zielony aktywny, pomarańczowy brak klucza, niebieski GPU startuje) i licznik alertów. Na telefonie pasek zwija się na górę.

## Testy akceptacyjne (pytest + ręczne)
1. Panel startuje na :5003 i pokazuje 3 boty z animowanymi awatarami.
2. Trasa WMI→BCN na grudzień 2026 zapisuje realne ceny (3.11.2026 najtaniej 75 PLN, 13.12), wykres się rysuje, a próg wyższy od ceny tworzy alert.
3. Fly4free RSS zapisuje co najmniej 10 wpisów bez duplikatów po dwóch pobraniach.
4. Sejf: test zapisu i odczytu. Klucz leży poza repo, a sekret nie pojawia się w logach (`grep`).
5. Kontroler Vast (mock API): kolejka z zadaniem GPU daje `start`, a 10 min bez zadań daje `stop`. Nigdy nie ma `destroy`.
6. Lock GPU (mock): zadanie wideo najpierw wywołuje `keep_alive=0`, czat i wideo nigdy nie biegną równocześnie.
7. Worker (na Vast): `/health` ok, czat z Dolphinem odpowiada po polsku, Wan 1.3B daje MP4 480p (~5 s), 2 klipy łączą się w jeden plik.
8. Bez tokenu worker zwraca 401, a port 11434 jest niedostępny z zewnątrz.
9. Ścieżka `../../x` w narzędziach zadania jest odrzucana.

Dokumentacja: README.md, ARCHITECTURE.md (diagram panel ↔ worker), docs/TEST_RESULTS.md, docs/DEPLOY_VAST.md (już istnieje, zaktualizuj).

## Kolejność prac (obowiązkowa)
**Faza 1: tylko darmowe źródła, zero wydatków.**
- Loty: Ryanair farfnd (NIEOFICJALNE) i Fly4free RSS.
- Dzienny: darmowe API bez klucza, np. Open-Meteo (pogoda), NBP (kursy walut), Wikipedia REST (streszczenia). Opcjonalnie darmowy Gemini z pliku `GEMINI_KEY_FILE`.
- Wideo: darmowy Space HF `Lightricks/ltx-video-distilled` przez `gradio_client`. Wzoruj się na `/workspace/video-studio/providers/hf_ltx.py`. Przy wyczerpanym limicie pokaż komunikat zamiast wyjątku.
- Uruchom prawdziwe testy każdego bota i zapisz `docs/TEST_RESULTS.md` (data, wejście, przykładowy wynik, PASS/FAIL).

**Faza 2: dopiero gdy Faza 1 przejdzie.**
- Dolphin `dolphin3:8b` przez Ollama i lokalne modele wideo (Wan 2.1 1.3B, LTX diffusers) na workerze Vast, za flagami `ORBIT_USE_OLLAMA=0` i `ORBIT_USE_LOCAL_VIDEO=0` (domyślnie wyłączone).
- Kontroler Vast testuj tylko na mocku.
- **Nie uruchamiaj żadnej instancji Vast, nie wydawaj pieniędzy, nie wpisuj sekretów do kodu.**
