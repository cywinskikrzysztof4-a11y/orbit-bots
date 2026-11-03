# Specyfikacja: lokalny backend LLM (Dolphin) dla Satelity

## Kontrakt
Satelita używa `core/llm.py` z backendem `openai` (API zgodne z OpenAI Chat Completions):
- `OPENAI_BASE_URL`, np. `http://127.0.0.1:11434/v1` (Ollama), `http://127.0.0.1:8080/v1` (llama.cpp server) albo `http://127.0.0.1:8000/v1` (vLLM)
- `OPENAI_API_KEY`: dowolny ciąg dla Ollama, token dla proxy z autoryzacją
- `OPENAI_MODEL`, np. `dolphin3:8b`
- `LLM_BACKEND=openai|gemini`, `LLM_FALLBACK=gemini`

Wywołanie: `POST {BASE}/chat/completions` z `{"model", "messages", "temperature": 0.2}`. Dla modeli Mistral-24B zalecana temperatura to 0,05–0,1. JSON wymuszaj promptem i parsuj tolerancyjnie. Timeout 120 s, a przy błędzie przełącz się na Gemini.

## Modele
| Model | Ollama | GGUF (HF) | Q4_K_M | Minimalny sprzęt |
|---|---|---|---|---|
| Dolphin 3.0 Llama 3.1 8B (**rekomendowany start**) | `dolphin3:8b` | `bartowski/Dolphin3.0-Llama3.1-8B-GGUF` | ~4,9 GB | GPU 8 GB VRAM (albo CPU z 16 GB RAM, wolno) |
| Dolphin 3.0 R1 Mistral 24B (rozumowanie) | `aia/Dolphin3.0-R1-Mistral-24B:Q4_K_M` | `bartowski/cognitivecomputations_Dolphin3.0-R1-Mistral-24B-GGUF` | 14,3 GB (Q6_K 19,4, Q8_0 25,1) | GPU 24 GB (RTX 3090/4090) |
| Dolphin Mixtral 8x7B | `dolphin-mixtral:8x7b` | — | 26 GB | 2× 24 GB albo 48 GB, CPU z 48–64 GB RAM |
| Dolphin Mixtral 8x22B | `dolphin-mixtral:8x22b` | — | 80 GB | A100/H100 80 GB i więcej |
Rozmiary dla 24B i Mixtrala według Ollama/HF (stan 3.11.2026). Rozmiar dla 8B to wartość przybliżona. Dolicz 1–3 GB VRAM na kontekst.
