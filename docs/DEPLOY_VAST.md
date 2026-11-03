# Wdrożenie Workera GPU na Vast.ai (RTX 3090 24 GB)

Dokumentacja konfiguracji i integracji panelu Orbit Bots z dedykowanym workerem GPU na platformie [Vast.ai](https://cloud.vast.ai).

> [!IMPORTANT]
> **Zasada zerowych kosztów automatycznych:**
> Panel Orbit Bots **nigdy nie tworzy (`create`) ani nie usuwa (`destroy`)** instancji maszyn wirtualnych.
> Użytkownik tworzy instancję jednorazowo ręcznie. Panel potrafi jedynie włączać (`start`) i wyłączać (`stop`) już istniejącą instancję na podstawie zapotrzebowania w kolejce zadań GPU.

---

## 1. Wymagania Sprzętowe i Finansowe

- **Karta graficzna:** NVIDIA GeForce RTX 3090 (24 GB VRAM) — wystarcza do jednoczesnego lub sekwencyjnego uruchamiania Dolphin 3:8B (~6 GB) oraz Wan 2.1 1.3B (~8 GB VRAM).
- **Lokalizacja:** Kanada (CA) lub Europa (rekomendowana niska cena i wysoka niezawodność).
- **Dysk instancji:** **≥ 60 GB SSD** (niezbędny na pamięć podręczną modeli w `/workspace/hf` oraz wagi Ollama).
- **Koszt sesji:** ~0,12–0,14 $/h w trakcie pracy. Zatrzymana instancja kosztuje jedynie opłatę za przestrzeń dyskową (~0,005–0,015 $/h).
- **Zasilenie konta:** Zalecane doładowanie 5 $ (wystarcza na około 35–40 godzin generowania wideo).

---

## 2. Krok po Kroku: Przygotowanie Instancji

### Krok 1: Klucz API Vast.ai
1. Wejdź na [cloud.vast.ai](https://cloud.vast.ai) ➔ **Account** ➔ **API Keys** ➔ **Create API Key**.
2. W panelu Orbit Bots (lub przez plik `.env`) dodaj klucz do sejfu Fernet jako wpis `vast`:
   ```json
   {
     "api_key": "twoj_tajny_klucz_vast_ai"
   }
   ```
   *Wartość nigdy nie jest wyświetlana w interfejsie użytkownika.*

### Krok 2: Wyszukanie Oferty
Z poziomu CLI lub interfejsu Vast.ai:
```bash
vastai search offers 'gpu_name=RTX_3090 num_gpus=1 geolocation=CA reliability>0.98 disk_space>=60' -o dph
```

### Krok 3: Utworzenie Instancji
Użyj oficjalnego obrazu PyTorch oraz skryptu `worker/onstart.sh`:
- **Image:** `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`
- **Disk Space:** 60 GB
- **Onstart Script:** zawartość pliku `worker/onstart.sh`
- **Port:** 8000 (HTTP/HTTPS przez proxy Vast lub tunel Cloudflare)
- **Zmienne środowiskowe:**
  - `WORKER_TOKEN=<wygenerowany-losowy-token-autoryzacji>`
  - `HF_HOME=/workspace/hf`
  - `OLLAMA_HOST=127.0.0.1:11434`

Polecenie CLI:
```bash
vastai create instance <OFFER_ID> \
  --image pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime \
  --disk 60 \
  --onstart-cmd "curl -fsSL https://twoj-serwer/onstart.sh | bash" \
  --env '-p 8000:8000 -e WORKER_TOKEN=sekretny_token_123 -e HF_HOME=/workspace/hf'
```

Zapisz przydzielone `ID instancji` (np. `1429812`).

---

## 3. Konfiguracja Panelu Orbit Bots

W pliku środowiskowym panelu lub zmiennych VPS/Render ustaw:
```ini
# ID instancji na Vast.ai (utworzonej ręcznie)
VAST_INSTANCE_ID=1429812

# Czas bezczynności przed automatycznym zatrzymaniem GPU (minuty)
VAST_IDLE_MIN=10

# Włączenie modułów Fazy 2
ORBIT_USE_OLLAMA=1
ORBIT_USE_LOCAL_VIDEO=1

# Adres workera po wystawieniu portu 8000
ORBIT_WORKER_URL=https://direct.vast.ai:38192
```

W sejfie Orbit Bots zapisz wpis `worker`:
```json
{
  "url": "https://direct.vast.ai:38192",
  "token": "sekretny_token_123"
}
```

---

## 4. Weryfikacja Działania

1. **Test endpointu diagnostycznego workera:**
   ```bash
   curl -H "Authorization: Bearer sekretny_token_123" https://direct.vast.ai:38192/health
   ```
   Odpowiedź powinna zawierać:
   ```json
   {
     "status": "ok",
     "gpu": true,
     "gpu_name": "NVIDIA GeForce RTX 3090",
     "ollama": true,
     "available_models": ["dolphin3:8b", "wan2.1_1.3b", "ltx_diffusers"]
   }
   ```

2. **Weryfikacja autoryzacji (odrzucenie braku tokenu):**
   ```bash
   curl -i https://direct.vast.ai:38192/health
   # Oczekiwany kod: HTTP 401 Unauthorized
   ```

3. **Weryfikacja braku ekspozycji portu Ollama:**
   Port 11434 nasłuchuje wyłącznie na `127.0.0.1` wewnątrz kontenera i nie może być dostępny bezpośrednio z internetu.

---

## 5. Logika Cyklu Życia i Kontroli Kosztów

- **Automatyczny start:** Gdy użytkownik zleci zadanie lokalnego wideo lub zapyta model Dolphin przy wyłączonej instancji, panel wysyła żądanie `PUT /instances/<id>/` ze stanem `running` i czeka na dostępność `/health`.
- **Automatyczny stop:** Scheduler panelu co 60 sekund sprawdza liczbę oczekujących zadań GPU. Jeśli przez `VAST_IDLE_MIN` (10 minut) nie było żadnych zadań, a instancja jest uruchomiona, wysyła polecenie `PUT` ze stanem `stopped`.
- **Kafel w UI:** Kafel „Worker GPU” na żywo wyświetla aktualny stan, koszt bieżącej sesji w dolarach oraz umożliwia ręczny start/stop po potwierdzeniu.
