# Co musisz zrobić sam (Orbit Bots)

1. **Amadeus.** Darmowego konta nie da się już założyć: Self-Service zamknięto 17.07.2026. Klucze dostaniesz tylko przez Amadeus Enterprise, czyli umowę handlową: https://developers.amadeus.com. Bez tego pomiń ten punkt.
2. **Reddit.** Nowe wnioski o API są zamknięte od 31.10.2026, a publiczne API kończy się w marcu 2027. Jeśli masz starą, zatwierdzoną aplikację typu *script* (https://www.reddit.com/prefs/apps), wpisz `client_id` i `client_secret` do sejfu Orbit (wpis `reddit`). W przeciwnym razie zostaje Fly4free RSS (działa bez klucza).
3. **(Opcjonalnie) Travelpayouts:** darmowe konto partnera na https://www.travelpayouts.com, potem Profile → API token, a token wpisz do sejfu (`travelpayouts`). Dostaniesz oficjalne ceny z cache.
4. **(Opcjonalnie) Duffel:** https://app.duffel.com, test token `duffel_test_…`, wpis w sejfie `duffel`. Tryb testowy daje tylko dane fikcyjne.
5. **Serwer lub GPU:** własny Linux z GPU ≥ 8 GB VRAM albo wynajem RTX 3090 na https://vast.ai (~0,11–0,14 $/h) lub https://www.runpod.io (~0,22 $/h). Wymaga konta i doładowania, więc decyzja i płatność należą do Ciebie.
6. **Model:** na serwerze `curl -fsSL https://ollama.com/install.sh | sh`, potem `ollama pull dolphin3:8b` (albo `aia/Dolphin3.0-R1-Mistral-24B:Q4_K_M` na 24 GB). Szczegóły w `docs/DOLPHIN_INSTALL.md`.
7. **Antigravity:** otwórz `/workspace/orbit` i wklej `docs/ANTIGRAVITY_PROMPT.md` jako zadanie.
