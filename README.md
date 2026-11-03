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
