# Konfiguracja integracji Gmail (Tylko Odczyt) w Orbit Bots

Niniejszy przewodnik krok po kroku opisuje proces konfiguracji darmowej integracji z pocztą Gmail w trybie **tylko do odczytu** (`https://www.googleapis.com/auth/gmail.readonly`) w aplikacji **Orbit Bots** wdrożonej na platformie Render (`https://orbit-bots.onrender.com`).

---

## 1. Utworzenie darmowego projektu w Google Cloud

1. Zaloguj się na swoje konto Google i przejdź do konsoli: [https://console.cloud.google.com/](https://console.cloud.google.com/).
2. Na górnym pasku kliknij listę projektów i wybierz **New Project** (Nowy projekt).
3. Podaj nazwę projektu, np. `Orbit Bots Assistant`.
4. Organizację pozostaw jako *No organization* (Brak organizacji).
5. Kliknij **Create** (Utwórz) i poczekaj kilka sekund, aż projekt zostanie utworzony, po czym upewnij się, że jest wybrany jako aktywny na górnym pasku.

---

## 2. Włączenie interfejsu Gmail API

1. W menu bocznym Google Cloud przejdź do: **APIs & Services** (Interfejsy API i usługi) ➔ **Library** (Biblioteka).
2. W polu wyszukiwania wpisz `Gmail API` i naciśnij Enter.
3. Wybierz kafelek **Gmail API**.
4. Kliknij niebieski przycisk **Enable** (Włącz).

---

## 3. Konfiguracja ekranu zgody OAuth (OAuth Consent Screen)

1. W menu bocznym wybierz: **APIs & Services** ➔ **OAuth consent screen** (Ekran zgody OAuth).
2. Wybierz typ użytkownika: **External** (Zewnętrzny) i kliknij **Create** (Utwórz).
3. Uzupełnij podstawowe informacje o aplikacji:
   - **App name** (Nazwa aplikacji): `Orbit Bots`
   - **User support email**: Wybierz swój adres e-mail
   - **Developer contact information**: Wpisz swój adres e-mail
4. Kliknij **Save and Continue** (Zapisz i kontynuuj).
5. W kroku **Scopes** (Zakresy) kliknij **Add or Remove Scopes**:
   - Wyszukaj i zaznacz wyłącznie zakres: `https://www.googleapis.com/auth/gmail.readonly` (Odczyt wiadomości i metadanych w Gmailu).
   - **WAŻNE:** Nie wybieraj żadnych zakresów umożliwiających wysyłanie (`gmail.send`), modyfikację (`gmail.modify`) ani pełny dostęp (`mail.google.com`).
   - Kliknij **Update** ➔ **Save and Continue**.
6. W kroku **Test users** (Użytkownicy testowi):
   - Ponieważ aplikacja pozostaje w trybie **Testing**, dostęp mają wyłącznie użytkownicy dodani do listy.
   - Kliknij **+ Add Users** i wpisz swój adres Gmail (np. `twoj-login@gmail.com`).
   - Kliknij **Add** ➔ **Save and Continue**.
7. Przejrzyj podsumowanie i wróć do pulpitu nawigacyjnego (**Back to Dashboard**).

---

## 4. Utworzenie klienta OAuth 2.0 Web

1. W menu bocznym wybierz: **APIs & Services** ➔ **Credentials** (Dane logowania).
2. Kliknij **+ Create Credentials** (Utwórz dane logowania) ➔ **OAuth client ID** (Identyfikator klienta OAuth).
3. W polu **Application type** (Typ aplikacji) wybierz **Web application** (Aplikacja internetowa).
4. Wpisz nazwę klienta, np. `Orbit Bots Web Client`.
5. W sekcji **Authorized redirect URIs** (Autoryzowane identyfikatory URI przekierowania) kliknij **+ Add URI** i wprowadź dokładnie:
   ```text
   https://orbit-bots.onrender.com/auth/google/callback
   ```
   *(Opcjonalnie, jeśli testujesz lokalnie, możesz dodać również `http://localhost:5003/auth/google/callback`)*.
6. Kliknij **Create** (Utwórz).
7. Pojawi się okno z Twoim **Client ID** (np. `123456789-abcdef.apps.googleusercontent.com`) oraz **Client Secret** (np. `GOCSPX-xyz123...`).
   - Skopiuj obie wartości w bezpieczne miejsce (nigdy nie udostępniaj ich publicznie ani nie commituj do repozytorium GitHub!).

---

## 5. Konfiguracja zmiennych środowiskowych na platformie Render

1. Zaloguj się do swojego panelu: [https://dashboard.render.com/](https://dashboard.render.com/).
2. Otwórz swój Web Service: `orbit-bots`.
3. W menu po lewej stronie wybierz zakładkę **Environment** (Środowisko).
4. Dodaj następujące zmienne środowiskowe:

| Nazwa Zmiennej | Wartość / Opis |
| :--- | :--- |
| **`GOOGLE_CLIENT_ID`** | Skopiowany `Client ID` z Google Cloud Console |
| **`GOOGLE_CLIENT_SECRET`** | Skopiowany `Client Secret` z Google Cloud Console |
| **`LLM_API_KEY`** | Darmowy klucz Gemini z [Google AI Studio](https://aistudio.google.com/) (dla modelu `gemini-3.5-flash-lite`) |
| **`ORBIT_PANEL_PASSWORD`** | Twoje silne, prywatne hasło chroniące panel i API (HTTP Basic Auth) |

> [!CAUTION]
> **Zasada bezpieczeństwa Orbit Bots:**  
> Gdy w aplikacji podłączone jest jakiekolwiek konto lub skrzynka Gmail, a zmienna `ORBIT_PANEL_PASSWORD` nie jest ustawiona w środowisku, panel **bezwzględnie odmawia dostępu** (zwraca kod HTTP `403 Forbidden`). Ustawienie hasła `ORBIT_PANEL_PASSWORD` jest obowiązkowe w celu ochrony prywatnych danych.

5. Kliknij **Save Changes** (Zapisz zmiany). Render automatycznie zrestartuje aplikację z nowymi zmiennymi.

---

## 6. Połączenie konta Gmail w panelu Orbit Bots

1. Otwórz w przeglądarce adres: `https://orbit-bots.onrender.com`.
2. Wprowadź hasło zdefiniowane w `ORBIT_PANEL_PASSWORD`.
3. W menu bocznym wybierz zakładkę **Konta & Zgody**.
4. Kliknij przycisk **➕ Połącz Gmail (OAuth 2.0)**.
5. Zostaniesz przekierowany na oficjalną stronę logowania Google:
   - Wybierz konto Gmail, które dodałeś jako *Test User*.
   - Ponieważ aplikacja jest w trybie Testing, Google wyświetli ostrzeżenie: *„Google hasn't verified this app”* (Aplikacja nie została zweryfikowana).
   - Kliknij **Advanced** (Zaawansowane) ➔ **Go to Orbit Bots (unsafe)** (Przejdź do: Orbit Bots).
   - Potwierdź uprawnienie do odczytu poczty (`View your email messages and settings`).
6. Po zatwierdzeniu zostaniesz automatycznie przekierowany z powrotem do panelu Orbit Bots z komunikatem o sukcesie.
7. Twoje konto pojawi się na liście podłączonych kont z aktywnym przełącznikiem **Zgoda agenta**.

---

## 7. Dostępne narzędzia agenta i gwarancje bezpieczeństwa

Agent Dzienny (`daily`) uzyskuje natychmiastowy dostęp do 4 narzędzi function-calling:
- `list_recent_emails(max_results=5)` — pobiera listę ostatnich wiadomości (nadawca, temat, data, skrót).
- `search_emails(query, max_results=5)` — wyszukuje wiadomości według filtrów (np. `from:allegro`, `faktura`, `lot`).
- `read_email(message_id)` — odczytuje pełną treść wybranej wiadomości.
- `summarize_inbox(max_results=5)` — generuje zwięzłe podsumowanie ostatnich maili w skrzynce.

### Architektura bezpieczeństwa:
- **Tylko Odczyt:** W całym kodzie projektu Orbit Bots nie istnieje ani jedna funkcja umożliwiająca wysyłanie (`send`), odpowiadanie (`reply`) ani usuwanie (`delete`/`trash`) maili.
- **Szyfrowanie Fernet:** Tokeny autoryzacyjne (`access_token`, `refresh_token`) są natychmiast szyfrowane i zapisywane w sejfie Fernet poza repozytorium.
- **Automatyczne odnawianie:** Tokeny dostępu są automatycznie odświeżane w tle za pomocą `refresh_token`.
- **Wycofanie zgody:** W każdej chwili w zakładce **Konta & Zgody** możesz jednym kliknięciem wyłączyć zgodę na dostęp agenta lub trwale odłączyć konto.
