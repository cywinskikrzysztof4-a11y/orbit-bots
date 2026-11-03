"""Integracja z pocztą Gmail w trybie TYLKO DO ODCZYTU (Read-Only).
Zgodnie z wymaganiami bezpieczeństwa:
- OAuth 2.0 web flow
- Scope wyłącznie: https://www.googleapis.com/auth/gmail.readonly (brak uprawnień send/modify/delete)
- GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET z env
- Tokeny szyfrowane w sejfie Fernet
- Narzędzia agenta: list_recent_emails, search_emails, read_email, summarize_inbox
- Kategoryczny ZAKAZ i brak jakiegokolwiek kodu do wysyłania, odpowiadania lub usuwania wiadomości.
"""
import os
import time
import base64
import secrets
import logging
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup

from . import db, vault, accounts

logger = logging.getLogger("orbit.gmail")

# WYŁĄCZNIE scope tylko do odczytu
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

db.init("""
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created REAL
);
""")

def get_google_client_config() -> tuple[str, str]:
    """Pobiera GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET ze zmiennych środowiskowych."""
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return cid, csec

def generate_auth_url(redirect_uri: str) -> tuple[str, str]:
    """Generuje unikalny token state i URL autoryzacyjny Google OAuth 2.0."""
    cid, csec = get_google_client_config()
    if not cid or not csec:
        raise ValueError("Brak GOOGLE_CLIENT_ID lub GOOGLE_CLIENT_SECRET w zmiennych środowiskowych.")

    state = secrets.token_urlsafe(32)
    db.execute("INSERT OR REPLACE INTO oauth_states(state, created) VALUES (?, ?)", (state, time.time()))

    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,  # Tylko i wyłącznie gmail.readonly
        "access_type": "offline",        # Wymagane do otrzymania refresh_token
        "prompt": "consent",            # Zapewnia zwrócenie refresh_token
        "state": state
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return url, state

def verify_state(state: str) -> bool:
    """Weryfikuje i unieważnia stan CSRF OAuth."""
    if not state:
        return False
    rows = db.query("SELECT created FROM oauth_states WHERE state = ?", (state,))
    if not rows:
        return False
    # Ważność stanu: 15 minut
    is_valid = (time.time() - rows[0]["created"]) < 900
    db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    return is_valid

def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Wymienia kod autoryzacji na tokeny dostępu i odświeżania."""
    cid, csec = get_google_client_config()
    if not cid or not csec:
        raise ValueError("Brak GOOGLE_CLIENT_ID lub GOOGLE_CLIENT_SECRET")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    resp = requests.post(token_url, data=data, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Błąd wymiany kodu OAuth ({resp.status_code}): {resp.text[:200]}")
    tokens = resp.json()

    # Weryfikacja przyznanego scope (upewnij się, że nie ma uprawnień do zapisu/usuwania)
    granted_scope = tokens.get("scope", "")
    if "mail.google.com" in granted_scope and "readonly" not in granted_scope:
        logger.warning(f"Uwaga: wykryto szerszy scope niż żądany: {granted_scope}")

    # Pobierz profil użytkownika (adres e-mail)
    email = "użytkownik"
    try:
        prof_res = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=15
        )
        if prof_res.status_code == 200:
            email = prof_res.json().get("emailAddress", "użytkownik")
    except Exception:
        pass

    stored_data = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + tokens.get("expires_in", 3600),
        "scope": tokens.get("scope", GMAIL_READONLY_SCOPE),
        "email": email
    }

    # Zapisz w sejfie Fernet
    vault.put("gmail_oauth", stored_data)

    # Zarejestruj w module kont
    accounts.register_oauth_account(
        account_id="gmail",
        name=f"Gmail ({email})",
        service="gmail",
        token_data=stored_data,
        consent=True
    )
    return stored_data

def get_valid_access_token() -> str:
    """Zwraca aktywny token dostępu, automatycznie go odnawiając (refresh_token)."""
    # Sprawdź zgodę użytkownika w module kont
    if not accounts.has_consent("gmail"):
        raise PermissionError("Brak zgody na użycie konta Gmail. Włącz zgodę w zakładce Konta w panelu Orbit.")

    data = vault.get("gmail_oauth")
    if not data or not data.get("access_token"):
        raise RuntimeError("Konto Gmail nie jest podłączone. Przejdź do zakładki Konta i kliknij 'Połącz Gmail'.")

    # Jeśli token wygasa za mniej niż 90 sekund i mamy refresh_token, odśwież go
    expires_at = data.get("expires_at", 0)
    refresh_token = data.get("refresh_token")
    if time.time() > (expires_at - 90) and refresh_token:
        cid, csec = get_google_client_config()
        if cid and csec:
            try:
                r = requests.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": cid,
                        "client_secret": csec,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token"
                    },
                    timeout=20
                )
                if r.status_code == 200:
                    fresh = r.json()
                    data["access_token"] = fresh.get("access_token")
                    data["expires_at"] = time.time() + fresh.get("expires_in", 3600)
                    if fresh.get("refresh_token"):
                        data["refresh_token"] = fresh.get("refresh_token")
                    vault.put("gmail_oauth", data)
                    accounts.register_oauth_account("gmail", f"Gmail ({data.get('email', 'Google')})", "gmail", data, consent=True)
            except Exception as e:
                logger.error(f"Błąd odświeżania tokena Gmail: {e}")

    return data["access_token"]

# ----------------- NARZĘDZIA AGENTA (WYŁĄCZNIE METODY GET) -----------------

def list_recent_emails(max_results: int = 5) -> list[dict]:
    """Pobiera listę ostatnich wiadomości ze skrzynki pocztowej."""
    max_results = max(1, min(int(max_results), 15))
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"maxResults": max_results},
        timeout=20
    )
    r.raise_for_status()
    items = r.json().get("messages", [])

    results = []
    for item in items:
        mid = item["id"]
        msg_r = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
            headers=headers,
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"]
            },
            timeout=15
        )
        if msg_r.status_code == 200:
            msg_data = msg_r.json()
            hdrs = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            results.append({
                "id": mid,
                "from": hdrs.get("from", "Nieznany nadawca"),
                "subject": hdrs.get("subject", "(brak tematu)"),
                "date": hdrs.get("date", ""),
                "snippet": msg_data.get("snippet", "")
            })
    return results

def search_emails(query: str, max_results: int = 5) -> list[dict]:
    """Wyszukuje wiadomości w Gmailu według podanego zapytania (np. 'from:boss', 'faktura', 'lot')."""
    max_results = max(1, min(int(max_results), 15))
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": query, "maxResults": max_results},
        timeout=20
    )
    r.raise_for_status()
    items = r.json().get("messages", [])

    results = []
    for item in items:
        mid = item["id"]
        msg_r = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
            headers=headers,
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"]
            },
            timeout=15
        )
        if msg_r.status_code == 200:
            msg_data = msg_r.json()
            hdrs = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            results.append({
                "id": mid,
                "from": hdrs.get("from", "Nieznany nadawca"),
                "subject": hdrs.get("subject", "(brak tematu)"),
                "date": hdrs.get("date", ""),
                "snippet": msg_data.get("snippet", "")
            })
    return results

def _extract_body_text(payload: dict) -> str:
    """Rekurencyjnie wyciąga treść tekstową z części wiadomości MIME."""
    body_data = payload.get("body", {}).get("data")
    if body_data:
        try:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
        except Exception:
            pass

    parts = payload.get("parts", [])
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                try:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                except Exception:
                    pass
        elif mime == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                try:
                    html_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    soup = BeautifulSoup(html_text, "html.parser")
                    return soup.get_text("\n", strip=True)
                except Exception:
                    pass
        elif part.get("parts"):
            nested = _extract_body_text(part)
            if nested:
                return nested
    return ""

def read_email(message_id: str) -> dict:
    """Odczytuje pełną treść wybranej wiadomości e-mail."""
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        headers=headers,
        params={"format": "full"},
        timeout=20
    )
    r.raise_for_status()
    msg = r.json()
    payload = msg.get("payload", {})
    hdrs = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    body = _extract_body_text(payload)
    if len(body) > 6000:
        body = body[:5950] + "\n...[przycięto długą treść]..."

    return {
        "id": message_id,
        "from": hdrs.get("from", "Nieznany nadawca"),
        "to": hdrs.get("to", ""),
        "subject": hdrs.get("subject", "(brak tematu)"),
        "date": hdrs.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body or msg.get("snippet", "")
    }

def summarize_inbox(max_results: int = 5) -> str:
    """Tworzy zwięzłe podsumowanie ostatnich wiadomości w skrzynce pocztowej."""
    emails = list_recent_emails(max_results=max_results)
    if not emails:
        return "Brak nowych wiadomości w skrzynce lub skrzynka jest pusta."

    lines = [f"Podsumowanie ostatnich {len(emails)} wiadomości w skrzynce:"]
    for i, e in enumerate(emails, 1):
        lines.append(f"{i}. Od: {e['from']} | Temat: {e['subject']} ({e['date']})")
        if e['snippet']:
            lines.append(f"   Fragment: {e['snippet'][:120]}...")
    return "\n".join(lines)
