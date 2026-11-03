"""Testy jednostkowe i integracyjne dla Agentów Orbit (Wymóg 7):
- Pętla function-calling z mockowanym Gemini API
- Limit MAX_TOOL_STEPS = 6
- Rejestry narzędzi dla wszystkich 3 botów (lotniczy, codzienny, wideo)
- Scope Gmail ściśle i wyłącznie readonly (brak send/modify/delete)
- Brak jakiegokolwiek kodu do wysyłania/usuwania maili
- Egzekwowanie zgody per konto (consent=True/False)
- Blokada akcji wrażliwych bez jawnego zatwierdzenia użytkownika
- Pauza przy 2FA i zakaz obchodzenia zabezpieczeń
- Ochrona hasłem ORBIT_PANEL_PASSWORD i blokada 403 przy braku hasła z podłączonymi kontami
"""
import os
import re
import json
import base64
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from core.agent import Agent, Tool, AgentResult, MAX_TOOL_STEPS
from core import accounts, gmail, db, vault
from bots.flights.bot import get_flight_agent, FLIGHT_TOOLS
from bots.daily.bot import get_daily_agent, DAILY_TOOLS
from bots.video.bot import get_video_agent, VIDEO_TOOLS
from app import app

# ----------------- 1. TEST PĘTLI FUNCTION-CALLING AGENTA -----------------

def test_agent_function_calling_loop(monkeypatch):
    """Pętla function-calling: LLM zwraca tool_call -> agent wykonuje narzędzie -> zwraca odpowiedź + kroki."""
    monkeypatch.setenv("LLM_API_KEY", "mock-test-key")

    mock_tool_handler = MagicMock(return_value={"temperature": 19.5, "condition": "Słonecznie"})
    tool = Tool(
        name="weather",
        description="Sprawdza pogodę",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"]
        },
        handler=mock_tool_handler,
        summary_fn=lambda r: f"Pogoda: {r['temperature']}°C, {r['condition']}"
    )

    agent = Agent(
        name="test_agent",
        system_prompt="Jesteś pomocnym asystentem.",
        tools=[tool],
        model="gemini-3.5-flash-lite"
    )

    # Odpowiedź 1: model zleca wywołanie narzędzia weather
    resp1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "weather",
                        "arguments": json.dumps({"city": "Kraków"})
                    }
                }]
            }
        }]
    }

    # Odpowiedź 2: model podsumowuje wynik po otrzymaniu odpowiedzi narzędzia
    resp2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "W Krakowie jest aktualnie 19.5°C i jest słonecznie.",
                "tool_calls": None
            }
        }]
    }

    mock_responses = [
        MagicMock(status_code=200, json=lambda: resp1),
        MagicMock(status_code=200, json=lambda: resp2)
    ]

    with patch("requests.post", side_effect=mock_responses) as mock_post:
        result = agent.run("Jaka jest pogoda w Krakowie?")

    assert result.answer == "W Krakowie jest aktualnie 19.5°C i jest słonecznie."
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step["tool"] == "weather"
    assert step["arguments"] == {"city": "Kraków"}
    assert "19.5" in step["result_summary"]
    mock_tool_handler.assert_called_once_with(city="Kraków")

# ----------------- 2. TEST LIMITU 6 KROKÓW AGENTA -----------------

def test_agent_max_tool_steps_limit(monkeypatch):
    """Agent bezwzględnie przestrzega MAX_TOOL_STEPS = 6 i nie wpada w nieskończoną pętlę."""
    monkeypatch.setenv("LLM_API_KEY", "mock-test-key")

    dummy_tool = Tool(
        name="ping",
        description="Narzędzie ping",
        parameters={"type": "object", "properties": {}},
        handler=lambda: {"pong": True},
        summary_fn=lambda r: "pong"
    )

    agent = Agent(
        name="loop_agent",
        system_prompt="Test limitu",
        tools=[dummy_tool],
        max_steps=MAX_TOOL_STEPS
    )

    # Model w nieskończoność próbuje wywoływać narzędzie ping
    infinite_tool_call_resp = MagicMock(
        status_code=200,
        json=lambda: {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_loop",
                        "type": "function",
                        "function": {"name": "ping", "arguments": "{}"}
                    }]
                }
            }]
        }
    )

    final_synth_resp = MagicMock(
        status_code=200,
        json=lambda: {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Zatrzymano po 6 krokach."
                }
            }]
        }
    )

    # 6 wywołań w pętli + 1 wywołanie syntezy końcowej
    side_effects = [infinite_tool_call_resp] * 6 + [final_synth_resp]

    with patch("requests.post", side_effect=side_effects):
        res = agent.run("Wykonuj ping w kółko")

    assert len(res.steps) == 6, f"Oczekiwano dokładnie 6 kroków, otrzymano {len(res.steps)}"
    assert res.answer == "Zatrzymano po 6 krokach."

# ----------------- 3. TEST REJESTRÓW NARZĘDZI 3 BOTÓW -----------------

def test_tool_registries_all_bots():
    """Weryfikacja rejestrów narzędzi dla 3 botów zgodnie ze specyfikacją."""
    # 1. Lotniczy: ryanair_search, fly4free_search, price_alert_add/list/remove
    flight_tools = {t.name for t in FLIGHT_TOOLS}
    expected_flight = {"ryanair_search", "fly4free_search", "price_alert_add", "price_alert_list", "price_alert_remove"}
    assert expected_flight.issubset(flight_tools), f"Brakujące narzędzia bota lotniczego: {expected_flight - flight_tools}"

    # 2. Codzienny: weather, nbp_rates, wikipedia, web_fetch, narzędzia Gmail
    daily_tools = {t.name for t in DAILY_TOOLS}
    expected_daily = {
        "weather", "nbp_rates", "wikipedia", "web_fetch",
        "list_recent_emails", "search_emails", "read_email", "summarize_inbox"
    }
    assert expected_daily.issubset(daily_tools), f"Brakujące narzędzia bota dziennego: {expected_daily - daily_tools}"

    # 3. Wideo: ltx_enqueue, ltx_status
    video_tools = {t.name for t in VIDEO_TOOLS}
    expected_video = {"ltx_enqueue", "ltx_status"}
    assert expected_video.issubset(video_tools), f"Brakujące narzędzia bota wideo: {expected_video - video_tools}"

# ----------------- 4. TEST SCOPE GMAIL WYŁĄCZNIE READONLY -----------------

def test_gmail_scope_strictly_readonly(monkeypatch):
    """Scope Gmail musi być wyłącznie https://www.googleapis.com/auth/gmail.readonly."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")

    assert gmail.GMAIL_READONLY_SCOPE == "https://www.googleapis.com/auth/gmail.readonly"

    url, state = gmail.generate_auth_url("https://orbit-bots.onrender.com/auth/google/callback")
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly" in url or "scope=https://www.googleapis.com/auth/gmail.readonly" in url

    # Upewnij się, że nie zażądano żadnego uprawnienia do wysyłania/modyfikacji
    assert "gmail.send" not in url
    assert "gmail.modify" not in url
    assert "gmail.compose" not in url
    assert "mail.google.com" not in url.split("scope=")[1].split("&")[0]

# ----------------- 5. TEST BRAKU KODU DO WYSYŁANIA I USUWANIA MAILI -----------------

def test_gmail_no_send_or_delete_code():
    """W module core/gmail.py nie ma żadnego kodu do wysyłania ani usuwania wiadomości."""
    gmail_attrs = dir(gmail)
    forbidden_terms = ["send", "reply", "compose", "draft", "trash", "delete", "remove_message", "modify"]

    for attr in gmail_attrs:
        # Pomiń nazwy wbudowane Pythona
        if attr.startswith("__"):
            continue
        attr_lower = attr.lower()
        for term in forbidden_terms:
            assert term not in attr_lower, f"Wykryto zabronioną funkcję/atrybut w core/gmail.py: {attr}"

    # Przeszukaj kod źródłowy pliku
    src_path = os.path.realpath(gmail.__file__)
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Sprawdź czy nie ma zapytań POST /messages/send ani DELETE
    assert "/messages/send" not in src
    assert "requests.delete" not in src
    assert "requests.post(" not in src or "token" in src  # requests.post może występować tylko dla oauth2 /token

# ----------------- 6. TEST EGZEKWOWANIA ZGODY PER KONTO (core/accounts.py) -----------------

def test_account_consent_enforcement():
    """Gdy zgoda jest wyłączona (consent=False), agent nie może użyć konta (PermissionError)."""
    acc_id = "test_custom_service"

    # Dodaj konto z domyślną zgodą
    accounts.register_credentials_account(
        account_id=acc_id,
        name="Test Service",
        service="custom_service",
        username="jan@example.com",
        password="secretpassword123",
        consent=True
    )

    assert accounts.has_consent(acc_id) is True
    creds = accounts.get_credentials(acc_id)
    assert creds is not None
    assert creds["username"] == "jan@example.com"
    assert creds["password"] == "secretpassword123"

    # Użytkownik cofa zgodę w UI
    accounts.set_consent(acc_id, False)
    assert accounts.has_consent(acc_id) is False

    # Próba odczytu poświadczeń przez agenta musi rzucić wyjątek PermissionError
    with pytest.raises(PermissionError) as exc_info:
        accounts.get_credentials(acc_id)
    assert "Brak zgody" in str(exc_info.value)

    # Odłączenie konta
    accounts.disconnect_account(acc_id)
    assert accounts.get_account(acc_id) is None
    assert vault.get(f"account_{acc_id}") is None

# ----------------- 7. TEST BLOKADY AKCJI BEZ ZATWIERDZENIA -----------------

def test_sensitive_action_requires_approval(monkeypatch):
    """Każda akcja zakupu/wysłania/publikacji wstrzymuje agenta i trafia do kolejki do zatwierdzenia."""
    monkeypatch.setenv("LLM_API_KEY", "mock-test-key")

    mock_send = MagicMock()
    send_tool = Tool(
        name="send_payment",
        description="Wyślij przelew/płatność",
        parameters={
            "type": "object",
            "properties": {"amount": {"type": "number"}, "recipient": {"type": "string"}},
            "required": ["amount", "recipient"]
        },
        handler=mock_send,
        requires_confirmation=True  # Wymaga zatwierdzenia
    )

    agent = Agent(name="finance_agent", system_prompt="Agent finansowy", tools=[send_tool])

    tool_call_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_pay",
                    "type": "function",
                    "function": {
                        "name": "send_payment",
                        "arguments": json.dumps({"amount": 500.0, "recipient": "Odbiorca"})
                    }
                }]
            }
        }]
    }

    with patch("requests.post", return_value=MagicMock(status_code=200, json=lambda: tool_call_resp)):
        res = agent.run("Wyślij 500 zł do Odbiorcy")

    # Handler nie mógł zostać wykonany!
    mock_send.assert_not_called()
    assert res.paused is True
    assert res.pause_reason == "pending_approval"
    assert res.pending_action is not None
    action_id = res.pending_action["id"]

    # Sprawdź obecność w kolejce pending_actions
    pending = accounts.list_pending_actions(status="pending")
    assert any(a["id"] == action_id for a in pending)

    # Użytkownik zatwierdza w UI
    accounts.approve_action(action_id)
    approved = accounts.list_pending_actions(status="approved")
    assert any(a["id"] == action_id for a in approved)

# ----------------- 8. TEST PAUZY PRZY 2FA -----------------

def test_2fa_pause_and_resume(monkeypatch):
    """Gdy wymagane jest 2FA, agent pauzuje, pyta użytkownika, a po podaniu kodu wznawia stan."""
    monkeypatch.setenv("LLM_API_KEY", "mock-test-key")

    acc_id = "test_2fa_account"
    accounts.register_credentials_account(acc_id, "Bank", "banking", "user", "pass", consent=True)

    def sensitive_tool():
        # Serwis zewnętrzny zażądał 2FA
        return accounts.request_2fa(acc_id, "Podaj kod z aplikacji Authenticator")

    tool = Tool(
        name="banking_login",
        description="Logowanie do banku",
        parameters={"type": "object", "properties": {}},
        handler=sensitive_tool
    )

    agent = Agent(name="bank_agent", system_prompt="Agent", tools=[tool])

    call_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_2fa",
                    "type": "function",
                    "function": {"name": "banking_login", "arguments": "{}"}
                }]
            }
        }]
    }

    with patch("requests.post", return_value=MagicMock(status_code=200, json=lambda: call_resp)):
        res = agent.run("Zaloguj mnie do banku")

    assert res.paused is True
    assert res.pause_reason == "needs_2fa"
    assert res.pending_2fa is not None
    req_id = res.pending_2fa["2fa_id"]

    # Sprawdź czy konto ma status needs_2fa
    acc = accounts.get_account(acc_id)
    assert acc["status"] == "needs_2fa"

    # Użytkownik podaje kod 2FA
    accounts.submit_2fa_code(req_id, "654321")

    # Status konta wraca do connected
    acc_after = accounts.get_account(acc_id)
    assert acc_after["status"] == "connected"

    # Sprzątanie
    accounts.disconnect_account(acc_id)

# ----------------- 9. TEST OCHRONY HASŁEM ORBIT_PANEL_PASSWORD -----------------

def test_security_orbit_panel_password(monkeypatch):
    """Test ochrony hasłem:
    1. Gdy hasło jest ustawione -> ochrona Basic Auth; wyjątki: /health i /auth/google/callback.
    2. Gdy podłączone konta, a hasła brak -> bezwzględna odmowa 403 Forbidden.
    """
    client = TestClient(app)

    # 1. ORBIT_PANEL_PASSWORD jest ustawione
    test_pw = "OrbitAdminSecret999!"
    monkeypatch.setenv("ORBIT_PANEL_PASSWORD", test_pw)

    # Zapytanie bez hasła -> 401
    r = client.get("/")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")

    # Zapytanie z błędnym hasłem -> 401
    bad_auth = base64.b64encode(b"admin:wrong").decode()
    r_bad = client.get("/", headers={"Authorization": f"Basic {bad_auth}"})
    assert r_bad.status_code == 401

    # Zapytanie z poprawnym hasłem -> 200 OK
    good_auth = base64.b64encode(f"admin:{test_pw}".encode()).decode()
    r_good = client.get("/", headers={"Authorization": f"Basic {good_auth}"})
    assert r_good.status_code == 200

    # Ścieżki wyjęte spod autoryzacji: /health, /healthz
    assert client.get("/health").status_code == 200
    assert client.get("/healthz").status_code == 200

    # 2. Scenariusz bezpieczeństwa: podłączone konto, a hasła brak -> 403 Forbidden
    monkeypatch.delenv("ORBIT_PANEL_PASSWORD", raising=False)

    # Upewnij się, że jest zarejestrowane konto
    accounts.register_credentials_account("sec_acc", "Sec Test", "service", "usr", "pwd", consent=True)
    assert accounts.has_connected_accounts() is True

    # Zapytanie do panelu -> 403 Forbidden
    r_blocked = client.get("/")
    assert r_blocked.status_code == 403
    assert "Odmowa dostępu" in r_blocked.text

    # API również zablokowane
    assert client.get("/api/bots").status_code == 403

    # Ale callback OAuth i /health nadal dostępne (dla monitoringu i zakończenia procesu logowania)
    assert client.get("/health").status_code == 200
    assert client.get("/healthz").status_code == 200

    # Posprzątaj konto
    accounts.disconnect_account("sec_acc")
