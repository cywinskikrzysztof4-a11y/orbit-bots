# Orbit Bots 🚀 — Centrum Dowodzenia Agentami AI

Modułowa aplikacja wieloagentowa w Pythonie (FastAPI + SQLite, interfejs w języku polskim, wdrożenie na Render: `https://orbit-bots.onrender.com` na planie darmowym).

W wersji 2.5 trzy wbudowane boty zostały przekształcone w **autonomicznych agentów z narzędziami (function-calling)** zasilanych darmowym endpointem Gemini API zgodnym z OpenAI, z modułem zarządzania kontami, bezpieczną integracją Gmail (tylko odczyt) oraz kolejką zatwierdzeń akcji wrażliwych.

---

## 🤖 Trzej Autonomiczni Agenci z Narzędziami

Każdy z agentów korzysta ze wspólnego, niezależnego od UI rdzenia `core/agent.py` (gotowego do późniejszego bezpośredniego użycia przez adapter Telegrama) oraz pętli function-calling z modelem `gemini-3.5-flash-lite` (klucz pobierany wyłącznie ze zmiennej `LLM_API_KEY`). Maksymalny limit kroków na zapytanie: `MAX_TOOL_STEPS = 6`.

### 1. ✈ Łowca lotów (`flights`) — Agent Podróżniczy
- **Narzędzia agenta:**
  - `ryanair_search(origin, dest, month)` — wyszukiwanie najtańszych taryf per dzień z oficjalnego serwera farfnd z 14 polskich lotnisk (m.in. WMI, WAW, KRK, GDN).
  - `fly4free_search(query, limit)` — przeszukiwanie okazji z serwisu Fly4free.pl (z automatyczną deduplikacją po linku).
  - `price_alert_add(origin, dest, month, threshold, drop_pct)` — natychmiastowe utworzenie alertu cenowego i weryfikacja.
  - `price_alert_list()` — lista wszystkich aktywnych tras i ich ostatnich cen.
  - `price_alert_remove(route_id)` — usunięcie alertu trasy.
- **Interfejs:** Dedykowany czat z agentem prezentujący wywołane narzędzia i wyniki, formularz tras oraz interaktywny wykres liniowy SVG.
- **Awatar:** Powiewająca flaga Chin SVG/CSS z filtrem `feTurbulence` i animacją `baseFrequency`.

### 2. 🛰 Dzienny (`daily`) — Osobisty Agent Zadań i Poczty
- **Narzędzia agenta:**
  - `weather(city)` — prognoza pogody z darmowego API Open-Meteo bez klucza.
  - `nbp_rates(currency)` — oficjalne średnie kursy walut z Narodowego Banku Polskiego (NBP API).
  - `wikipedia(query, lang)` — streszczenia i wyszukiwarka haseł w polskiej Wikipedii.
  - `web_fetch(url)` — bezpieczne pobieranie treści stron WWW (tylko protokoły HTTP/HTTPS, metoda GET, limit rozmiaru, bez skryptów/styli).
  - `list_recent_emails(max_results)` — odczyt listy ostatnich wiadomości z Gmaila.
  - `search_emails(query, max_results)` — wyszukiwanie maili według słów kluczowych i nadawcy.
  - `read_email(message_id)` — odczyt pełnej treści wiadomości e-mail.
  - `summarize_inbox(max_results)` — generowanie zwięzłego podsumowania skrzynki odbiorczej.
  - `browser_navigate(url)`, `browser_fill(selector, value)`, `browser_click(selector, is_payment)`, `browser_register_account(service, register_url)` — pełna automatyzacja przeglądarki Playwright (headless Chromium).
- **Interfejs:** Czat z pamięcią kontekstu w SQLite (`daily_memory`), szybkie przyciski narzędziowe oraz wizualne bloczki kroków agenta (rozwijana lista wykonanych narzędzi z parametrami i podsumowaniem).
- **Awatar:** Satelita krążący na orbicie eliptycznej (czysty CSS/SVG).

### 3. 🎬 Wideo (`video`) — Agent Kreatywny
- **Narzędzia agenta:**
  - `ltx_enqueue(prompt, duration, aspect, clips, model, style, seed)` — kolejkowanie generowania klipów wideo (darmowy Hugging Face Space Lightricks LTX lub opcjonalny worker GPU Vast.ai).
  - `ltx_status(job_id)` — sprawdzanie postępu i statusu wyrenderowanych filmów.
- **FFmpeg:** Automatyczne scalanie wygenerowanych klipów w gotowy plik MP4 z dźwiękiem AAC.
- **Awatar:** Kometa ze szpulą filmową i świecącym ogonem z taśmy filmowej (animacja CSS/SVG).

---

## 📬 Integracja Gmail (Tylko Odczyt)

- **OAuth 2.0 Web Flow:** Oficjalny przepływ Google OAuth 2.0 z endpointami `/auth/google/start` i `/auth/google/callback` (z weryfikacją losowego tokenu `state`).
- **Ścisły zakres uprawnień (Scope):** Wyłącznie `https://www.googleapis.com/auth/gmail.readonly`.
- **Gwarancja bezpieczeństwa:** W całym projekcie **nie istnieje żaden kod** do wysyłania wiadomości, odpowiadania, tworzenia wersji roboczych ani usuwania maili.
- **Szyfrowanie tokenów:** Klucze autoryzacyjne (`access_token`, `refresh_token`) są natychmiast szyfrowane i zapisywane w sejfie Fernet.
- **Krok po kroku:** Zobacz dedykowany przewodnik [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) opisujący konfigurację projektu w Google Cloud Console i zmiennych w Renderze.

---

## 🌐 Narzędzia Przeglądarki Headless (Playwright, Chromium)

- **Automatyzacja Webowa:** otwieranie stron (`browser_navigate`), wypełnianie pól formularzy (`browser_fill`), klikanie przycisków (`browser_click`), zakładanie kont na stronach (`browser_register_account`), przechodzenie do koszyka i kasy.
- **Bezpieczeństwo danych użytkownika:** dane logowania pobierane z sejfu Fernet; nowe hasła są generowane losowo (kryptograficznie silne) i natychmiast szyfrowane w sejfie.
- **Ochrona danych kart:** numery kart płatniczych i kody CVV/CVC są automatycznie maskowane — nigdy nie są zapisywane w kodzie ani logowane.
- **Blokada przed płatnością:** przed ostatecznym kliknięciem *Zapłać* / *Złóż zamówienie* agent **bezwzględnie zatrzymuje się** i generuje w panelu podsumowanie (sklep, kwota, lista pozycji) z przyciskiem *Zatwierdź*. Bez wyraźnej akceptacji użytkownika w panelu żadna płatność nie zostanie zrealizowana.
- **Zakaz obchodzenia CAPTCHA / 2FA / SMS:** po napotkaniu wyzwania antybotowego lub kodu SMS agent natychmiast pauzuje i prosi użytkownika o podanie kodu w sekcji 2FA panelu.

---

## 🔑 Moduł Zarządzania Kontami (`core/accounts.py`)

- **Jednorazowe podłączenie:** Użytkownik łączy każde konto raz (preferowane OAuth z automatycznym odnawianiem tokenów).
- **Konta bez OAuth:** Dane logowania są szyfrowane kluczem Fernet i przechowywane w sejfie.
- **Flaga zgody (Consent per account):** Każde konto posiada niezależną flagę zgody. Agent ma prawo korzystać **wyłącznie z kont z aktywną zgodą**. Wycofanie zgody natychmiast blokuje dostęp agenta (wyjątek `PermissionError`).
- **Kolejka do zatwierdzenia:** Każda próba wykonania akcji wrażliwej (wysłanie, zakup, publikacja) jest wstrzymywana (`status: pending_approval`) i wymaga manualnego potwierdzenia użytkownika w UI.
- **Zakaz obchodzenia 2FA/CAPTCHA:** W przypadku wykrycia wymogu uwierzytelnienia dwuskładnikowego, agent natychmiast pauzuje i prosi użytkownika o kod w sekcji 2FA.
- **Strona „Konta & Zgody”:** Pełna lista powiązanych usług, przełączniki zgody, przyciski odłączania, kolejka akcji do zatwierdzenia oraz formularz kodów 2FA.

---

## 🛡️ Bezpieczeństwo i Ochrona Hasłem

- Zmienna `ORBIT_PANEL_PASSWORD` chroni cały panel oraz API za pomocą HTTP Basic Auth.
- Wyjątki wyjęte spod autoryzacji: `/health`, `/healthz` oraz callback OAuth `/auth/google/callback`.
- **Kluczowa reguła bezpieczeństwa:** Jeżeli w aplikacji podłączono skrzynkę pocztową lub jakiekolwiek konto serwisowe, a hasło `ORBIT_PANEL_PASSWORD` nie zostało skonfigurowane w zmiennych środowiskowych — aplikacja **bezwzględnie odmawia dostępu** (zwracając kod `403 Forbidden`).

---

## ⚙️ Zmienne Środowiskowe

Skopiuj szablon `.env.example` lub uzupełnij zmienne w panelu Render ➔ Environment:

```bash
# Klucz darmowego Gemini API (Google AI Studio)
LLM_API_KEY=twoj-klucz-gemini

# Google OAuth 2.0 (Gmail Read-Only)
GOOGLE_CLIENT_ID=twoj-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=twoj-sekret
GOOGLE_REDIRECT_URI=https://orbit-bots.onrender.com/auth/google/callback

# Hasło panelu (wymagane przy podłączonych kontach)
ORBIT_PANEL_PASSWORD=twoje-silne-haslo-panelu
```

---

## 🧪 Testy Pytest

Projekt posiada kompletny zestaw 35 testów jednostkowych i integracyjnych (w tym testy z mockowanym LLM, Gmail oraz mockowanym sklepem w Playwright):

```bash
.venv/bin/pytest tests/ -v
```

Wszystkie testy weryfikują m.in.:
1. Pętlę function-calling agenta z mockowanym Gemini API.
2. Bezwzględny limit `MAX_TOOL_STEPS = 6`.
3. Kompletność rejestrów narzędzi dla 3 botów.
4. Ścisły zakres uprawnień Gmail wyłącznie `readonly`.
5. Całkowity brak kodu do wysyłania lub usuwania wiadomości.
6. Egzekwowanie zgody per konto (`consent=True/False`).
7. Blokadę akcji wrażliwych bez zatwierdzenia w UI.
8. Pauzę przy żądaniu 2FA.
9. Ochronę hasłem `ORBIT_PANEL_PASSWORD` oraz blokadę 403.
10. Otwieranie stron, wypełnianie formularzy i szyfrowanie haseł w Playwright.
11. Zatrzymanie przed finalizacją płatności w sklepie i blokadę zakupu bez zatwierdzenia.
12. Ochronę danych kart płatniczych i brak ich logowania.
13. Pauzę przy wykryciu CAPTCHA / 2FA / SMS w przeglądarce.

---

## ☁️ Uruchomienie w GitHub Codespaces

Darmowy test z lokalnymi modelami (bez Gemini, bez kluczy):

1. Na GitHubie: **Code → Codespaces → ⋯ → New with options**, wybierz maszynę **4-core / 16 GB**.
2. Przy pierwszym starcie skrypt `.devcontainer/post-create.sh` instaluje Ollamę, zależności Pythona i Chromium (kilka minut).
3. Przy każdym starcie `.devcontainer/post-start.sh` uruchamia `ollama serve`, pobiera modele `qwen3:4b` (mały, szybki) i `dolphin3:8b` (domyślny, bez cenzury) oraz startuje Orbit na porcie **8000** (zakładka *Ports*).
4. Agenci korzystają z endpointu Ollamy zgodnego z OpenAI: `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=dolphin3:8b`, `LLM_API_KEY=ollama` (wartość zastępcza, nie sekret). Zmiana modelu: `export LLM_MODEL=qwen3:4b` i restart uvicorn.
5. Logi: `/tmp/orbit.log`, `/tmp/ollama.log`, `/tmp/ollama-pull.log`. Postęp pobierania modeli: `tail -f /tmp/ollama-pull.log`.

Ograniczenia: darmowy limit to 120 rdzeniogodzin/mies. (~30 h na 4 rdzeniach), Codespace zatrzymuje się po ok. 30 min bezczynności, a model 8B na CPU odpowiada wolno (kilka tokenów/s). Konfiguracja Render/Gemini pozostaje bez zmian.

---

## ⏰ Automatyczne Wybudzanie Codespace i Harmonogram Zadań

System umożliwia cykliczne uruchamianie zadań w tle (np. sprawdzanie cen lotów, agregacja ofert, zadania agentów, generowanie wideo) w bezpłatnym środowisku GitHub Codespaces, z zachowaniem automatycznego uśpienia po zakończeniu pracy.

Wdrożono:
1. **Thread-safe licznik zadań (`core/activity.py`):** monitoruje liczbę aktywnych wątków zadań (`active`), oczekujących zadań w kolejce SQLite (`queued`) oraz znacznik ostatniej aktywności (`last_activity`). Dostępny przez endpoint `GET /api/health/busy`.
2. **Pętlę keep-alive (`core/keepalive.py`):** aktywna **wyłącznie** przy `CODESPACES=true`. Dopóki `active > 0`, co ~4 min generuje aktywność (wypisanie na terminal stdout z flushem + modyfikacja pliku w przestrzeni roboczej `data/.codespace_keepalive`), co resetuje licznik idle timeout w GitHub Codespaces. Gdy `active == 0`, pętla nie generuje żadnego sygnału, pozwalając Codespace zasnąć po 30 min bezczynności. Na Renderze mechanizm pozostaje wyłączony.
3. **Workflow GitHub Actions (`.github/workflows/wake-codespace.yml`):** wybudza Codespace przez GitHub API, czeka na stan `Available`, po czym wywołuje endpoint `POST /api/jobs/run-scheduled` zabezpieczony tokenem.

### 1. Jak wygenerować Personal Access Token (PAT)
1. W profilu GitHub przejdź do: **Settings ➔ Developer Settings ➔ Personal Access Tokens ➔ Tokens (classic)** (lub Fine-grained tokens).
2. Kliknij **Generate new token (classic)**.
3. Nazwij token (np. `Orbit-Codespaces-Controller`).
4. Zaznacz uprawnienie **`codespace`** (pełna kontrola nad tworzeniem, uruchamianiem i zatrzymywaniem codespaces).
5. Wygeneruj i skopiuj token (zaczyna się od `ghp_`).

### 2. Jak ustawić Secret w repozytorium (`CODESPACE_PAT`)
1. W repozytorium GitHub wejdź w: **Settings ➔ Secrets and variables ➔ Actions**.
2. W sekcji **Repository secrets** kliknij przycisk **New repository secret**.
3. Jako **Name** wpisz: `CODESPACE_PAT`.
4. Jako **Secret** wklej skopiowany wcześniej token PAT.
5. Kliknij **Add secret**.
6. *(Zalecane)* W **Settings ➔ Secrets and variables ➔ Codespaces** również dodaj secret `CODESPACE_PAT` (lub `ORBIT_JOB_TOKEN`), aby środowisko Codespace miało dostęp do tej zmiennej i automatycznie autoryzowało zapytania do endpointu `/api/jobs/run-scheduled`.

### 3. Jak ustawić Zmienną repozytorium (`CODESPACE_NAME`)
1. W repozytorium wejdź w: **Settings ➔ Secrets and variables ➔ Actions ➔ Zakładka Variables**.
2. Kliknij **New repository variable**.
3. Jako **Name** wpisz: `CODESPACE_NAME`.
4. Jako **Value** wpisz nazwę swojego Codespace (np. `fictional-guacamole-4qvxgrw5pj64h77v9`).
5. Gdzie znaleźć nazwę Codespace?
   - W terminalu: wykonaj polecenie `gh codespace list`.
   - W przeglądarce: wejdź na [github.com/codespaces](https://github.com/codespaces) — unikalna nazwa jest widoczna pod nazwą repozytorium.

### 4. Harmonogram (cron) i uruchamianie ręczne
Workflow zdefiniowany jest w pliku `.github/workflows/wake-codespace.yml`.
- **Harmonogram automatyczny:** domyślnie skonfigurowano uruchamianie codziennie o godzinie 05:00 UTC (`cron: '0 5 * * *'`). Możesz zmienić to pole na dowolną składnię cron, np.:
  - `'0 */6 * * *'` — co 6 godzin
  - `'0 6,18 * * *'` — dwa razy dziennie (o 06:00 i 18:00 UTC)
- **Uruchomienie ręczne (`workflow_dispatch`):**
  1. Wejdź w zakładkę **Actions** w repozytorium.
  2. Wybierz workflow **Wake Codespace & Run Scheduled Jobs** z lewej listy.
  3. Kliknij rozwijane menu **Run workflow** i zatwierdź zielonym przyciskiem.
  4. Opcjonalny parametr `wait_for_completion` pozwala wybrać, czy wywołanie ma czekać synchronicznie na zakończenie wszystkich zadań (`true`), czy uruchomić je w tle i natychmiast zakończyć krok workflow (`false`).

### 5. Ograniczenia i ważne zasady działania
- **Idle timeout (30 minut):** GitHub Codespaces domyślnie usypia maszynę po 30 minutach bezczynności. Gdy zadania botów dobiegną końca (`active=0`), pętla keep-alive milknie, a maszyna samoistnie się wyłącza.
- **Twardy limit 12 godzin (Absolute Lifetime Limit):** Niezależnie od keep-alive, ruchów myszą czy procesów terminala, GitHub zamyka każdy działający kontener Codespace po maksymalnie 12 godzinach ciągłej pracy.
- **Miesięczny limit darmowych godzin:** Darmowe konta GitHub posiadają 120 rdzeniogodzin/miesiąc (dla domyślnej maszyny 4-core oznacza to ~30 godzin pracy na pełnych obrotach). Dzięki wybudzaniu tylko na czas pracy zadań i automatycznemu usypianiu po skończeniu, pula darmowych godzin wystarcza na codzienne operacje.
- **Środowisko produkcyjne Render:** Działa w 100% bez zmian (`CODESPACES` nie jest ustawione, więc pętla keep-alive nie startuje, a aplikacja działa w standardowym trybie ciągłym/darmowym).
- **Bezpieczeństwo tokenów:** W kodzie repozytorium ani w logach **nie ma żadnych tokenów**. Token autoryzacyjny jest wstrzykiwany w czasie wykonywania workflow wyłącznie z bezpiecznego magazynu sekretów GitHuba.

