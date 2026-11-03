# Plan: integracja z Telegramem (NIE zaimplementowane)
- Env: `TELEGRAM_BOT_TOKEN` (od @BotFather), opcjonalnie `TELEGRAM_CHAT_ID`.
- Krok 1: wysyłka alertów (core/alerts.py) przez Bot API `sendMessage`.
- Krok 2: webhook `/telegram/webhook` na Renderze -> komendy `/loty`, `/pogoda`, `/wideo`.
- Krok 3: każdy bot jako osobna komenda; token tylko w env/sejfie, nigdy w kodzie.
