# Orbit Bots 🚀

Modułowa aplikacja wielobotowa w Pythonie (FastAPI + SQLite, interfejs w języku polskim) zaprojektowana w **architekturze dzielonej**:
- **Panel (zawsze włączony):** UI, bot lotów, bot asystenta dziennego z darmowymi API, kolejka zadań, sejf Fernet, kontroler Vast.ai. Działa na porcie **5003**.
- **Worker GPU na Vast.ai RTX 3090 24 GB:** uruchamiany na żądanie dla zadań wymagających dużych modeli (Dolphin 3:8B przez Ollama oraz generowanie wideo Wan 2.1 / LTX). Automatycznie wyłączany po 10 minutach bezczynności.

---

## 🤖 Trzy Wbudowane Boty

### 1. ✈ Łowca lotów (`flights`)
- **Trasy:** wyloty z 14 polskich portów lotniczych (m.in. WAW, WMI, KRK, GDN, KTW, WRO, POZ) do dowolnego portu IATA na wybrany miesiąc.
- **Źródło cen:** Ryanair farfnd (<span style="color:#f87171;font-weight:bold;">NIEOFICJALNE</span>, odpytywane co 6 godzin).
- **Okazje:** RSS portalu [Fly4free.pl](https://www.fly4free.pl/feed/) odpytywany co 2 godziny, z pełną deduplikacją po linku i automatycznym wykrywaniem polskich miast oraz cen.
- **Wykresy i alerty:** historia najniższych cen z wykresem liniowym SVG, widok słupkowy dzień po dniu w miesiącu, alerty przy przekroczeniu progu cenowego lub spadku o X%, przycisk testowego alertu.
- **Awatar:** Powiewająca flaga Chin SVG/CSS z filtrem `feTurbulence` i animacją `baseFrequency`.

### 2. 🛰 Dzienny (`daily`)
- **Czat po polsku:** pamięć ostatnich 12 wiadomości w SQLite (`daily_memory`), przycisk „Zapomnij”.
- **Darmowe narzędzia (Faza 1 — bez klucza):**
  - **Open-Meteo:** aktualna pogoda i prognoza dla dowolnego miasta.
  - **NBP API:** oficjalne średnie kursy walut (EUR, USD, GBP, CHF itp.).
  - **Wikipedia:** streszczenia i wyszukiwarka haseł w języku polskim.
  - **Fetch + BeautifulSoup:** czyszczenie i pobieranie stron WWW z cache TTL.
- **Bezpieczeństwo sandboxa:** każde zadanie otrzymuje izolowany katalog roboczy `data/tasks/<id>/`. Próby wyjścia poza katalog (`../../x`) są bezwzględnie blokowane.
- **Faza 2:** model Dolphin 3:8B przez Ollama na workerze GPU.
- **Awatar:** Satelita krążący na eliptycznej orbicie wokół planety (czysty CSS/SVG).

### 3. 🎬 Wideo (`video`)
- **Generowanie wideo AI:** formularz wprowadzania promptu, wyboru modelu, proporcji obrazu (16:9, 9:16, 1:1) i liczby klipów (1–6).
- **Faza 1 (darmowa):** Space Hugging Face `Lightricks/ltx-video-distilled` przez `gradio_client`. Wyczerpanie limitu ZeroGPU wyświetla przyjazny komunikat zamiast błędu.
- **Faza 2 (lokalna na GPU):** modele `Wan-AI/Wan2.1-T2V-1.3B-Diffusers` (480p, 81 klatek, ~8 GB VRAM) oraz `Lightricks/LTX-Video`.
- **Łączenie klipów:** automatyczne scalanie klipów za pomocą narzędzia FFmpeg (`concat`) w jeden plik MP4 z dźwiękiem AAC.
- **Podgląd i pobieranie:** odtwarzacz wideo bezpośrednio w przeglądarce oraz pobieranie gotowego pliku MP4.
- **Awatar:** Kometa ze szpulą filmową i świecącym ogonem z klatek taśmy filmowej (animacja CSS/SVG).

---

## 🌌 Wygląd i Interfejs (UI)

- Ciemny motyw kosmiczny (gradient `#070b1a → #111a3a`), migoczące gwiazdy w czystym CSS.
- Karty glassmorphism (`backdrop-filter: blur(14px)`), zaokrąglenia 14px, akcenty `#7c5cff` i `#22d3ee`.
- **Zero zewnętrznych plików graficznych lub czcionek** — wszystkie awatary, logotypy i wykresy to inline SVG i style CSS.
- Responsywny pasek boczny ze wskaźnikami statusu (zielony = aktywny, pomarańczowy = brak klucza, niebieski = startuje GPU) i licznikiem alertów.
- Kafel kontrolera Vast.ai ze stanem instancji, stawką godzinową, kosztem bieżącej sesji oraz przyciskami Start/Stop.

---

## 🛠 Instalacja i Uruchomienie

### Wymagania
- Python 3.11+
- FFmpeg (do łączenia klipów wideo)

### 1. Przygotowanie środowiska
```bash
cd /workspace/orbit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Uruchomienie aplikacji (port 5003)
```bash
python app.py
```
Aplikacja jest dostępna w przeglądarce pod adresem: **http://localhost:5003**.

---

## 🔐 Sejf Kluczy (Fernet) i Bezpieczeństwo

- Wszystkie sekrety (np. klucz API Vast.ai, tokeny dostępu workera) są szyfrowane algorytmem Fernet.
- Klucz szyfrujący przechowywany jest **poza repozytorium**: `~/.orbit/vault.key` (uprawnienia `chmod 600`) lub w zmiennej środowiskowej `ORBIT_VAULT_KEY_B64`.
- Interfejs API i widok WWW udostępniają **wyłącznie nazwy pozycji**, nigdy wartości kluczy.
- Wartości poufne nie trafiają do logów ani bazy w postaci jawnej.

---

## 🧪 Testy Akceptacyjne

Pełny zestaw 21 testów jednostkowych i integracyjnych uruchamia się poleceniem:
```bash
.venv/bin/pytest tests/ -v
```

Szczegółowe wyniki testów z rzeczywistymi danymi z API znajdują się w dokumencie [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md).

---

## 📚 Dokumentacja Szczegółowa

- [ARCHITECTURE.md](ARCHITECTURE.md) — pełny opis architektury dzielonej z diagramem Mermaid.
- [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) — zestawienie wyników wszystkich testów akceptacyjnych.
- [docs/DEPLOY_VAST.md](docs/DEPLOY_VAST.md) — przewodnik wdrożenia workera GPU na platformie Vast.ai (RTX 3090).
