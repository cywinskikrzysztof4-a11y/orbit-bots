"""Testy modułu przeglądarki Playwright (Chromium headless) na mockowanej stronie sklepu.
Weryfikuje:
- otwieranie stron i wypełnianie formularzy
- rejestrację kont (dane użytkownika z sejfu, nowe hasło generowane i szyfrowane w sejfie)
- przejście do koszyka i kasy
- zatrzymanie przed ostatecznym kliknięciem płatności (podsumowanie: sklep, kwota, pozycje w panelu)
- blokadę płatności bez zatwierdzenia użytkownika
- brak logowania danych kart płatniczych
- wykrywanie CAPTCHA / 2FA / SMS i pauzę z prośbą o kod do użytkownika.
"""
import pytest
import threading
import http.server
import json
from urllib.parse import parse_qs, urlparse

from core import vault, accounts
from core.browser import BrowserController, mask_card_data, get_browser_controller

MOCK_HTML_SHOP = """<!DOCTYPE html>
<html>
<head><title>OrbitShop — Sklep Testowy</title></head>
<body>
  <h1>Witaj w OrbitShop</h1>
  <div class="product">
    <span class="product-name">Koszulka Orbit</span>
    <span class="product-price">79.00 PLN</span>
    <button id="add-to-cart-1" onclick="document.getElementById('status').innerText='Dodano do koszyka'">Dodaj do koszyka</button>
  </div>
  <div id="status">Koszyk pusty</div>
  <p><a id="go-to-cart" href="/cart">Przejdź do koszyka</a></p>
  <p><a id="go-to-register" href="/register">Załóż konto</a></p>
</body>
</html>
"""

MOCK_HTML_REGISTER = """<!DOCTYPE html>
<html>
<head><title>Rejestracja — OrbitShop</title></head>
<body>
  <h2>Utwórz konto w sklepie</h2>
  <form id="reg-form">
    <input id="email" name="email" type="email" placeholder="E-mail">
    <input id="password" name="password" type="password" placeholder="Hasło">
    <button id="btn-submit-reg" type="button" onclick="document.getElementById('res').innerText='Konto utworzone'">Zarejestruj</button>
  </form>
  <div id="res"></div>
</body>
</html>
"""

MOCK_HTML_CART = """<!DOCTYPE html>
<html>
<head><title>Twój koszyk — OrbitShop</title></head>
<body>
  <h2>Twój koszyk</h2>
  <div class="cart-item">Koszulka Orbit — 1 szt. — 79.00 PLN</div>
  <div id="cart-total">Do zapłaty: 79.00 PLN</div>
  <a id="go-to-checkout" href="/checkout">Przejdź do kasy</a>
</body>
</html>
"""

MOCK_HTML_CHECKOUT = """<!DOCTYPE html>
<html>
<head><title>Kasa — OrbitShop</title></head>
<body>
  <h2>Finalizacja zamówienia</h2>
  <div id="order-summary">
    <p>Sklep: OrbitShop</p>
    <p>Pozycja: Koszulka Orbit</p>
    <p>Kwota: 79.00 PLN</p>
  </div>
  <div class="payment-form">
    <input id="card-number" name="card_number" placeholder="Numer karty">
    <input id="card-cvv" name="cvv" placeholder="CVV">
    <!-- Przycisk ostatecznej płatności z kluczowym słowem -->
    <button id="btn-pay-now" type="button" onclick="document.getElementById('pay-status').innerText='Opłacono'">Kupuję i płacę</button>
  </div>
  <div id="pay-status">Oczekiwanie na płatność</div>
</body>
</html>
"""

MOCK_HTML_2FA = """<!DOCTYPE html>
<html>
<head><title>Weryfikacja SMS — Bezpieczeństwo</title></head>
<body>
  <h2>Weryfikacja dwuetapowa</h2>
  <p>Podaj kod z SMS przesłany na Twój telefon komórkowy:</p>
  <input id="sms-code" name="sms" autocomplete="one-time-code">
</body>
</html>
"""

MOCK_HTML_CAPTCHA = """<!DOCTYPE html>
<html>
<head><title>Weryfikacja antybotowa</title></head>
<body>
  <h2>Potwierdź, że nie jesteś robotem</h2>
  <div class="g-recaptcha" data-sitekey="test-key-1234"></div>
  <p>Rozwiąż zadanie CAPTCHA, aby kontynuować.</p>
</body>
</html>
"""

class MockShopHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        path = self.path.split("?")[0]
        if path == "/" or path == "/shop":
            self.wfile.write(MOCK_HTML_SHOP.encode("utf-8"))
        elif path == "/register":
            self.wfile.write(MOCK_HTML_REGISTER.encode("utf-8"))
        elif path == "/cart":
            self.wfile.write(MOCK_HTML_CART.encode("utf-8"))
        elif path == "/checkout":
            self.wfile.write(MOCK_HTML_CHECKOUT.encode("utf-8"))
        elif path == "/2fa":
            self.wfile.write(MOCK_HTML_2FA.encode("utf-8"))
        elif path == "/captcha":
            self.wfile.write(MOCK_HTML_CAPTCHA.encode("utf-8"))
        else:
            self.wfile.write(b"<h1>404 Not Found</h1>")

    def log_message(self, format, *args):
        pass

@pytest.fixture(scope="module")
def mock_shop_server():
    """Uruchamia lokalny serwer testowy HTTP na losowym wolnym porcie."""
    server = http.server.HTTPServer(("127.0.0.1", 0), MockShopHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()

@pytest.fixture
def browser():
    ctrl = BrowserController()
    yield ctrl
    ctrl.close()

# ----------------- TESTY PRZEGLĄDARKI -----------------

def test_browser_open_and_click(mock_shop_server, browser):
    """Test otwierania strony i klikania przycisku dodania do koszyka."""
    res_nav = browser.navigate(f"{mock_shop_server}/shop")
    assert res_nav["status"] == "ok"
    assert "OrbitShop" in res_nav["title"]

    res_click = browser.click("#add-to-cart-1")
    assert res_click["status"] == "clicked"

def test_browser_register_account_encrypted_vault(mock_shop_server, browser):
    """Test zakładania konta: generowanie silnego hasła, szyfrowanie w sejfie Fernet i zapis w accounts."""
    service = "mock_shop_orbit"
    res = browser.register_account(service, f"{mock_shop_server}/register")

    assert res["status"] == "registered_and_stored"
    assert res["service"] == service
    assert res["password_encrypted"] is True

    # Sprawdź czy poświadczenia są zapisane w sejfie Fernet
    stored = vault.get(f"account_{service}")
    assert stored is not None
    assert "password" in stored
    assert len(stored["password"]) >= 16  # Silne hasło

    # Sprawdź obecność w module kont
    acc = accounts.get_account(service)
    assert acc is not None
    assert acc["consent"] is True

    # Sprzątanie
    accounts.disconnect_account(service)

def test_browser_shopping_flow_and_pause_before_payment(mock_shop_server, browser):
    """Test ścieżki koszyka i kasy:
    Przed ostatecznym kliknięciem 'Kupuję i płacę' agent MUSI się zatrzymać,
    wyświetlić podsumowanie (sklep, kwota, pozycje) i utworzyć akcję w kolejce do zatwierdzenia.
    Bez zatwierdzenia nic nie płaci!
    """
    # 1. Przejście do koszyka
    browser.navigate(f"{mock_shop_server}/cart")
    assert "Twój koszyk" in browser.navigate(f"{mock_shop_server}/cart")["title"]

    # 2. Przejście do kasy
    browser.navigate(f"{mock_shop_server}/checkout")

    # 3. Próba kliknięcia przycisku płatności 'Kupuję i płacę'
    res_pay = browser.click(
        "#btn-pay-now",
        store="OrbitShop",
        amount=79.00,
        items=["Koszulka Orbit"]
    )

    # 4. Weryfikacja zatrzymania agenta (status pending_approval)
    assert res_pay["status"] == "pending_approval"
    assert res_pay["store"] == "OrbitShop"
    assert res_pay["amount"] == 79.00
    assert "Koszulka Orbit" in res_pay["items"]
    assert "ZATRZYMANO PRZED PŁATNOŚCIĄ" in res_pay["message"]

    action_id = res_pay["action_id"]

    # 5. Sprawdź, czy akcja czeka w kolejce
    pending_list = accounts.list_pending_actions(status="pending")
    found_action = next((a for a in pending_list if a["id"] == action_id), None)
    assert found_action is not None
    assert found_action["action_type"] == "purchase"
    assert "OrbitShop" in found_action["description"]
    assert "79.00" in found_action["description"]

    # 6. Próba realizacji bez zatwierdzenia -> musi rzucić błąd odmowy
    with pytest.raises(PermissionError) as exc_info:
        browser.execute_approved_purchase(action_id)
    assert "Płatność zablokowana" in str(exc_info.value)

    # 7. Użytkownik zatwierdza w panelu
    accounts.approve_action(action_id)

    # 8. Dopiero teraz realizacja zamówienia jest dozwolona
    exec_res = browser.execute_approved_purchase(action_id)
    assert exec_res["status"] == "purchase_completed"

def test_card_data_never_logged_or_exposed(mock_shop_server, browser):
    """Numery kart płatniczych oraz kody CVV nie mogą pojawiać się w logach ani wartościach zwracanych."""
    card_number = "4532 1234 5678 9012"
    cvv = "987"

    # Wypełnienie pola numeru karty
    browser.navigate(f"{mock_shop_server}/checkout")
    res_fill_card = browser.fill("#card-number", card_number)

    # Zwrócony podgląd nie może zawierać pełnego numeru karty
    assert card_number not in res_fill_card["value_preview"]
    assert "CHRONIONE" in res_fill_card["value_preview"]

    # Funkcja pomocnicza maskowania
    sample_text = f"Płatność kartą {card_number} z kodem CVV: {cvv}"
    masked = mask_card_data(sample_text)
    assert card_number not in masked
    assert "4532" not in masked
    assert cvv not in masked
    assert "[CHRONIONY NUMER KARTY]" in masked

def test_browser_captcha_and_2fa_pause(mock_shop_server, browser):
    """Gdy strona wymaga 2FA/SMS lub CAPTCHA, agent nie próbuje ich obchodzić — pauzuje i pyta użytkownika."""
    # 1. Strona z kodem SMS (2FA)
    res_2fa = browser.navigate(f"{mock_shop_server}/2fa")
    assert res_2fa["status"] == "needs_2fa"
    assert "Wymagany kod" in res_2fa["prompt"]
    assert "2fa_id" in res_2fa

    # Sprawdź czy trafiło do kolejki 2FA w accounts
    pending_2fa = accounts.list_pending_2fa()
    assert any(req["id"] == res_2fa["2fa_id"] for req in pending_2fa)

    # 2. Strona z CAPTCHA
    res_captcha = browser.navigate(f"{mock_shop_server}/captcha")
    assert res_captcha["status"] == "needs_2fa"
    assert "CAPTCHA" in res_captcha["prompt"]
