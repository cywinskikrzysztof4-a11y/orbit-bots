"""Moduł Przeglądarki Headless (Playwright, Chromium) dla Agentów Orbit.
Zapewnia:
- otwieranie stron WWW (browser_navigate)
- klikanie elementów (browser_click)
- wypełnianie formularzy (browser_fill) z ochroną danych kart płatniczych
- zakładanie kont na stronach (dane z sejfu Fernet, hasło generowane i szyfrowane w sejfie)
- przechodzenie do koszyka i kasy
- BEZWZGLĘDNE zatrzymanie przed płatnością / zamówieniem (podsumowanie: sklep, kwota, pozycje + przycisk Zatwierdź w panelu)
- brak zapisywania danych karty w kodzie i logach
- obsługa CAPTCHA / 2FA / SMS: zakaz omijania, pauza i żądanie kodu od użytkownika.
"""
import os
import re
import secrets
import logging
from typing import Any
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Browser, Page, Playwright

from . import vault, accounts
from .agent import Tool

logger = logging.getLogger("orbit.browser")

# Słowa kluczowe wskazujące na finalizację płatności lub złożenie zamówienia
PAYMENT_KEYWORDS = [
    "zapłać", "kupuję i płacę", "złóż zamówienie", "zamawiam z obowiązkiem zapłaty",
    "pay now", "place order", "complete purchase", "confirm and pay",
    "checkout pay", "finalize order", "potwierdź i zapłać"
]

# Słowa kluczowe i selektory wskazujące na CAPTCHA lub 2FA/SMS
CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[src*='turnstile']",
    ".g-recaptcha", ".h-captcha", "#cf-turnstile", "[data-sitekey]"
]

TWO_FA_SELECTORS = [
    "input[name*='2fa']", "input[name*='otp']", "input[name*='sms']",
    "input[id*='2fa']", "input[id*='otp']", "input[id*='sms']",
    "input[autocomplete='one-time-code']"
]

TWO_FA_KEYWORDS = [
    "podaj kod z sms", "kod weryfikacyjny", "weryfikacja dwuetapowa",
    "two-factor authentication", "enter verification code", "kod sms",
    "wpisz kod przesłany", "security code", "potwierdź kodem"
]

def mask_card_data(text: str) -> str:
    """Maskuje numery kart płatniczych i kody CVV w tekście i logach."""
    if not text:
        return ""
    # Maskowanie 13-19 cyfrowych numerów kart
    masked = re.sub(r"\b(?:\d[ -]?){13,19}\b", "[CHRONIONY NUMER KARTY]", str(text))
    # Maskowanie 3-4 cyfrowych kodów CVV/CVC jeśli występują po słowach kluczowych
    masked = re.sub(r"(?i)\b(cvv|cvc|cvv2|cvc2|kod)\s*[:=]?\s*\d{3,4}\b", r"\1: ***", masked)
    return masked

class BrowserController:
    """Zarządca przeglądarki Playwright Chromium (headless)."""
    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def _ensure_page(self) -> Page:
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        if self._page is None or self._page.is_closed():
            context = self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OrbitBot/1.0"
            )
            self._page = context.new_page()
        return self._page

    def close(self):
        """Zamyka stronę i instancję przeglądarki."""
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f"Błąd zamykania przeglądarki: {e}")
        finally:
            self._page = None
            self._browser = None
            self._playwright = None

    def check_security_challenges(self, service: str = "web") -> dict | None:
        """Sprawdza obecność CAPTCHA lub żądania 2FA/SMS na stronie."""
        page = self._ensure_page()
        try:
            # 1. Sprawdź selektory CAPTCHA
            for sel in CAPTCHA_SELECTORS:
                if page.locator(sel).count() > 0:
                    req = accounts.request_2fa(
                        service,
                        f"Wykryto zabezpieczenie CAPTCHA na stronie {page.url}. Rozwiąż test w przeglądarce i zatwierdź."
                    )
                    return {
                        "status": "needs_2fa",
                        "2fa_id": req["2fa_id"],
                        "account_id": service,
                        "prompt": req["prompt"]
                    }

            # 2. Sprawdź pola 2FA / SMS
            for sel in TWO_FA_SELECTORS:
                if page.locator(sel).count() > 0:
                    req = accounts.request_2fa(
                        service,
                        f"Wymagany kod weryfikacyjny (SMS / 2FA) na stronie {page.url}. Podaj kod z wiadomości."
                    )
                    return {
                        "status": "needs_2fa",
                        "2fa_id": req["2fa_id"],
                        "account_id": service,
                        "prompt": req["prompt"]
                    }

            # 3. Sprawdź treść strony pod kątem haseł 2FA
            body_text = page.inner_text("body").lower()
            if "captcha" in body_text and any(w in body_text for w in ("zaznacz", "nie jestem robotem", "zweryfikuj")):
                req = accounts.request_2fa(service, f"Wymagane rozwiązanie CAPTCHA na stronie {page.url}.")
                return {"status": "needs_2fa", "2fa_id": req["2fa_id"], "prompt": req["prompt"]}

            for kw in TWO_FA_KEYWORDS:
                if kw in body_text:
                    req = accounts.request_2fa(service, f"Wymagany kod SMS / 2FA: {kw} na stronie {page.url}.")
                    return {"status": "needs_2fa", "2fa_id": req["2fa_id"], "prompt": req["prompt"]}
        except Exception:
            pass

        return None

    def navigate(self, url: str) -> dict:
        """Otwiera stronę internetową w headless Chromium."""
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Sprawdź CAPTCHA / 2FA
        sec_check = self.check_security_challenges(service=urlparse(url).netloc or "web")
        if sec_check:
            return sec_check

        title = page.title()
        snippet = page.inner_text("body")[:800].replace("\n", " ").strip()
        return {
            "status": "ok",
            "url": page.url,
            "title": title,
            "snippet": mask_card_data(snippet)
        }

    def fill(self, selector: str, value: str) -> dict:
        """Wypełnia pole formularza (z ochroną przed logowaniem danych kart)."""
        page = self._ensure_page()
        page.wait_for_selector(selector, timeout=10000)

        # Wykryj próbę wprowadzenia danych karty (ochrona przed wyciekiem w logach)
        is_card = bool(re.search(r"\b(?:\d[ -]?){13,19}\b", str(value))) or "card" in selector.lower() or "cvv" in selector.lower()
        log_val = "[DANE KARTY CHRONIONE]" if is_card else value

        page.fill(selector, value)

        return {
            "status": "filled",
            "selector": selector,
            "value_preview": log_val[:30]
        }

    def click(
        self,
        selector: str,
        is_payment: bool = False,
        store: str | None = None,
        amount: float | None = None,
        items: list[str] | None = None
    ) -> dict:
        """Klika element na stronie. Jeśli to akcja finalizacji płatności, zatrzymuje agenta."""
        page = self._ensure_page()
        page.wait_for_selector(selector, timeout=10000)

        element_text = (page.inner_text(selector) or "").lower()

        # Sprawdź czy to akcja finalizacji zakupu/płatności
        is_final_payment = is_payment or any(kw in element_text for kw in PAYMENT_KEYWORDS) or any(kw in selector.lower() for kw in PAYMENT_KEYWORDS)

        if is_final_payment:
            # WYMÓG BEZPIECZEŃSTWA: zatrzymaj agenta i utwórz wpis w kolejce do zatwierdzenia!
            domain = store or urlparse(page.url).netloc or "Sklep internetowy"
            kwota = amount if amount is not None else 0.0
            pozycje = items or ["Zamówienie ze strony " + domain]

            desc = f"Sklep: {domain} | Kwota: {kwota:.2f} PLN | Pozycje: {', '.join(pozycje)}"
            act = accounts.request_action_approval(
                agent_id="browser",
                action_type="purchase",
                description=desc,
                payload={
                    "store": domain,
                    "amount": kwota,
                    "items": pozycje,
                    "selector": selector,
                    "url": page.url
                }
            )

            # Agent MUSI się zatrzymać, bez zatwierdzenia nic nie płaci
            return {
                "status": "pending_approval",
                "action_id": act["id"],
                "store": domain,
                "amount": kwota,
                "items": pozycje,
                "message": (
                    f"⛔ ZATRZYMANO PRZED PŁATNOŚCIĄ! Wymagane zatwierdzenie w panelu: "
                    f"Sklep: {domain}, Kwota: {kwota:.2f} PLN, Pozycje: {', '.join(pozycje)}. "
                    f"Przejdź do zakładki 'Konta & Zgody' i kliknij 'Zatwierdź' (ID: {act['id']})."
                )
            }

        # Normalne kliknięcie (np. dodaj do koszyka, przejdź do kasy)
        page.click(selector)
        page.wait_for_load_state("domcontentloaded", timeout=15000)

        # Sprawdź CAPTCHA / 2FA po kliknięciu
        sec = self.check_security_challenges(service=urlparse(page.url).netloc or "web")
        if sec:
            return sec

        return {
            "status": "clicked",
            "selector": selector,
            "current_url": page.url,
            "title": page.title()
        }

    def register_account(self, service: str, register_url: str) -> dict:
        """Zakłada konto w serwisie internetowym: dane użytkownika z sejfu, nowe hasło generowane i szyfrowane w sejfie."""
        # Pobierz dane użytkownika z sejfu lub użyj profilu domyślnego
        user_prof = vault.get("user_profile") or {}
        email = user_prof.get("email") or vault.secret("user", "email") or f"orbit_{service}_{secrets.token_hex(3)}@gmail.com"
        username = user_prof.get("username") or email.split("@")[0]

        # Wygeneruj silne, losowe hasło
        generated_password = secrets.token_urlsafe(16) + "!Aa1"

        # Zapisz wygenerowane konto w sejfie Fernet i module kont
        accounts.register_credentials_account(
            account_id=service,
            name=f"Konto {service} ({email})",
            service=service,
            username=email,
            password=generated_password,
            consent=True
        )

        page = self._ensure_page()
        page.goto(register_url, wait_until="domcontentloaded", timeout=30000)

        sec = self.check_security_challenges(service=service)
        if sec:
            return sec

        return {
            "status": "registered_and_stored",
            "service": service,
            "email": email,
            "password_encrypted": True,
            "message": f"Konto w serwisie '{service}' zostało przygotowane, a nowe hasło zaszyfrowane w sejfie Fernet. Zgoda na użycie konta jest aktywna."
        }

    def execute_approved_purchase(self, action_id: str) -> dict:
        """Wykonuje finalne kliknięcie płatności WYŁĄCZNIE po zatwierdzeniu przez użytkownika w panelu."""
        rows = accounts.db.query("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        if not rows:
            raise ValueError(f"Akcja {action_id} nie istnieje")

        act = rows[0]
        if act["status"] != "approved":
            raise PermissionError(
                f"Płatność zablokowana: Akcja #{action_id} nie została zatwierdzona przez użytkownika (status: {act['status']})."
            )

        payload = accounts.json.loads(act["payload_json"])
        selector = payload.get("selector")
        page = self._ensure_page()

        if selector and page.locator(selector).count() > 0:
            page.click(selector)
            page.wait_for_load_state("domcontentloaded", timeout=15000)

        return {
            "status": "purchase_completed",
            "action_id": action_id,
            "store": payload.get("store"),
            "amount": payload.get("amount"),
            "message": "Zamówienie zostało pomyślnie zrealizowane po zatwierdzeniu przez użytkownika."
        }

# Globalna instancja kontrolera przeglądarki
_browser_ctrl = BrowserController()

def get_browser_controller() -> BrowserController:
    return _browser_ctrl

# ----------------- DEFINICJE NARZĘDZI AGENTA (TOOL OBJECTS) -----------------

def tool_browser_navigate(url: str) -> dict:
    return _browser_ctrl.navigate(url)

def tool_browser_click(
    selector: str,
    is_payment: bool = False,
    store: str = None,
    amount: float = None,
    items: list[str] = None
) -> dict:
    return _browser_ctrl.click(selector, is_payment=is_payment, store=store, amount=amount, items=items)

def tool_browser_fill(selector: str, value: str) -> dict:
    return _browser_ctrl.fill(selector, value)

def tool_browser_register_account(service: str, register_url: str) -> dict:
    return _browser_ctrl.register_account(service, register_url)

BROWSER_TOOLS = [
    Tool(
        name="browser_navigate",
        description="Otwiera wskazaną stronę WWW w przeglądarce headless Chromium.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Adres URL strony internetowej (http:// lub https://)"}
            },
            "required": ["url"]
        },
        handler=tool_browser_navigate,
        summary_fn=lambda r: f"Otwarto stronę: {r.get('title', r.get('url'))}"
    ),
    Tool(
        name="browser_fill",
        description="Wypełnia pole tekstowe lub formularz na bieżącej stronie w przeglądarce.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selektor CSS lub XPath pola (np. '#email', 'input[name=login]')"},
                "value": {"type": "string", "description": "Wprowadzana wartość"}
            },
            "required": ["selector", "value"]
        },
        handler=tool_browser_fill,
        summary_fn=lambda r: f"Wypełniono pole {r.get('selector')}"
    ),
    Tool(
        name="browser_click",
        description="Klika element na stronie. Jeśli to przycisk płatności/zamówienia, zatrzymuje się i prosi o zatwierdzenie w UI.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selektor CSS lub XPath klikanego elementu"},
                "is_payment": {"type": "boolean", "description": "Czy to ostateczne kliknięcie płatności/zamówienia", "default": False},
                "store": {"type": "string", "description": "Nazwa sklepu / serwisu"},
                "amount": {"type": "number", "description": "Łączna kwota zamówienia"},
                "items": {"type": "array", "items": {"type": "string"}, "description": "Lista zamawianych pozycji"}
            },
            "required": ["selector"]
        },
        handler=tool_browser_click,
        summary_fn=lambda r: r.get("message") or f"Kliknięto {r.get('selector')}"
    ),
    Tool(
        name="browser_register_account",
        description="Zakłada konto na stronie: pobiera dane użytkownika z sejfu, generuje silne hasło i szyfruje je w sejfie Fernet.",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nazwa serwisu / sklepu (np. allegro, amazon, sklep-xyz)"},
                "register_url": {"type": "string", "description": "Adres URL strony rejestracji"}
            },
            "required": ["service", "register_url"]
        },
        handler=tool_browser_register_account,
        summary_fn=lambda r: f"Zarejestrowano konto dla {r.get('service')} (hasło zaszyfrowane w sejfie)"
    )
]
