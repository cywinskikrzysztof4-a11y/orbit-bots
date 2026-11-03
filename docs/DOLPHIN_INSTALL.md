# Instalacja Dolphin (Ollama) na serwerze Linux

## 0. Wybór modelu
- **Start / tani GPU (8–12 GB VRAM):** `dolphin3:8b` (Dolphin 3.0, Llama 3.1 8B, ~4,9 GB).
- **RTX 3090 / 4090 (24 GB):** `aia/Dolphin3.0-R1-Mistral-24B:Q4_K_M` (14 GB). Lepsze rozumowanie, mieści się z kontekstem 16–32k.
- **Bez GPU:** 8B na CPU, 16 GB RAM, ok. 3–8 tokenów/s. Wystarczy do streszczeń w tle.

## 1. Instalacja Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh     # instaluje binarkę i usługę systemd „ollama”
ollama --version
nvidia-smi                                        # sprawdź, czy GPU jest widoczne (sterownik NVIDIA ≥ 535)
```

## 2. Pobranie modelu
```bash
ollama pull dolphin3:8b
# albo dla 24 GB VRAM:
ollama pull aia/Dolphin3.0-R1-Mistral-24B:Q4_K_M
ollama run dolphin3:8b "Powiedz cześć po polsku."
```
Alternatywa przez GGUF z Hugging Face: `ollama pull hf.co/bartowski/cognitivecomputations_Dolphin3.0-R1-Mistral-24B-GGUF:Q4_K_M`

## 3. Usługa systemd, nasłuch tylko na localhost
Instalator tworzy `ollama.service`. Ustaw bezpieczne opcje:
```bash
sudo systemctl edit ollama
```
```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_KEEP_ALIVE=30m"
Environment="OLLAMA_NUM_PARALLEL=2"
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now ollama && systemctl status ollama
```
**Nigdy nie wystawiaj portu 11434 na 0.0.0.0 bez autoryzacji, bo Ollama sama jej nie ma.**

## 4. Bezpieczny dostęp z zewnątrz
**A. Tunel SSH (najprostszy):** na komputerze z aplikacją Orbit:
```bash
ssh -N -L 11434:127.0.0.1:11434 user@serwer      # potem OPENAI_BASE_URL=http://127.0.0.1:11434/v1
```
**B. Reverse proxy z tokenem (Caddy + HTTPS):**
```caddy
llm.twojadomena.pl {
  @noauth not header Authorization "Bearer {env.ORBIT_LLM_TOKEN}"
  respond @noauth 401
  reverse_proxy 127.0.0.1:11434
}
```
Wtedy `OPENAI_BASE_URL=https://llm.twojadomena.pl/v1`, a `OPENAI_API_KEY=<ORBIT_LLM_TOKEN>`. Dodatkowo firewall: `sudo ufw allow 22,443/tcp && sudo ufw enable`.

## 5. Test curl (API zgodne z OpenAI)
```bash
curl -s http://127.0.0.1:11434/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"dolphin3:8b","messages":[{"role":"user","content":"Streść w 1 zdaniu: Orbit Bots to aplikacja z botami."}],"temperature":0.2}'
curl -s http://127.0.0.1:11434/v1/models
```

## 6. Podłączenie aplikacji
W `.env` aplikacji Orbit:
```
LLM_BACKEND=openai
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=dolphin3:8b
LLM_FALLBACK=gemini
```

## 7. Opcja: wynajęty RTX 3090 (Vast.ai / RunPod)
Ceny z 3.11.2026, około 17:45 (Europe/Warsaw): Vast.ai ok. 0,107–0,138 $/h z dyskiem 50 GB, RunPod Community 0,22 $/h (ok. 0,227 $ z dyskiem 50 GB).
1. Utwórz instancję RTX 3090 z obrazem `ollama/ollama` (Vast.ai: template „Ollama”) albo z Ubuntu + CUDA i krok 1. Dysk 40–50 GB.
2. **Nie otwieraj portu 11434 publicznie.** Połącz się przez SSH z tunelem: `ssh -p <PORT> root@<IP> -N -L 11434:127.0.0.1:11434`.
3. Na instancji: `ollama pull aia/Dolphin3.0-R1-Mistral-24B:Q4_K_M` (pobranie 14 GB, transfer na Vast.ai to zwykle kilka centów).
4. Ustaw `OPENAI_BASE_URL=http://127.0.0.1:11434/v1` lokalnie (przez tunel).
5. **Zatrzymuj (stop) instancję po pracy.** Zatrzymana instancja nalicza tylko opłatę za dysk. Na RunPod użyj Network Volume, żeby nie pobierać modelu ponownie.
Koszt orientacyjny: 3 h dziennie × 0,12 $ ≈ 11 $/mies. (Vast.ai) albo × 0,22 $ ≈ 20 $/mies. (RunPod).
