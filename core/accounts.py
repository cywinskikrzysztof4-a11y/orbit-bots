"""Moduł Kont Orbit (core/accounts.py).
Użytkownik podłącza każde konto raz.
- Preferuje OAuth (automatyczne odświeżanie tokenów).
- Dla serwisów bez OAuth: login/hasło szyfrowane w sejfie Fernet + flaga zgody per konto.
- Agenci automatycznie używają zapisanych sesji, ale wyłącznie kont z aktywną zgodą (consent=True).
- Każda akcja wysłania/zakupu/publikacji wymaga jawnego potwierdzenia użytkownika w UI (kolejka "do zatwierdzenia").
- Zakaz obchodzenia CAPTCHA/2FA: gdy wymagane 2FA, agent pauzuje i pyta użytkownika o kod.
- Strona "Konta": lista, zgoda, odłączenie.
"""
import uuid
import json
import time
from typing import Any
from . import db, vault

db.init("""
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    auth_type TEXT NOT NULL,
    consent INTEGER DEFAULT 1,
    status TEXT DEFAULT 'connected',
    created TEXT DEFAULT CURRENT_TIMESTAMP,
    updated TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created TEXT DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS pending_2fa (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'waiting',
    code TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);
""")

def list_accounts() -> list[dict]:
    """Zwraca listę podłączonych kont bez haseł i tokenów."""
    rows = db.query("SELECT id, name, service, auth_type, consent, status, created, updated FROM accounts ORDER BY id ASC")
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "service": r["service"],
            "auth_type": r["auth_type"],
            "consent": bool(r["consent"]),
            "status": r["status"],
            "created": r["created"],
            "updated": r["updated"]
        }
        for r in rows
    ]

def get_account(account_id: str) -> dict | None:
    rows = db.query("SELECT id, name, service, auth_type, consent, status, created, updated FROM accounts WHERE id = ?", (account_id,))
    if not rows:
        return None
    r = rows[0]
    return {
        "id": r["id"],
        "name": r["name"],
        "service": r["service"],
        "auth_type": r["auth_type"],
        "consent": bool(r["consent"]),
        "status": r["status"],
        "created": r["created"],
        "updated": r["updated"]
    }

def has_consent(account_id: str) -> bool:
    """Sprawdza, czy użytkownik udzielił zgody na użycie danego konta przez agenta."""
    rows = db.query("SELECT consent FROM accounts WHERE id = ?", (account_id,))
    if not rows:
        return False
    return bool(rows[0]["consent"])

def set_consent(account_id: str, consent: bool) -> bool:
    """Włącza lub wyłącza flagę zgody dla konta."""
    db.execute(
        "UPDATE accounts SET consent = ?, updated = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if consent else 0, account_id)
    )
    return True

def get_credentials(account_id: str) -> dict | None:
    """Pobiera zaszyfrowane poświadczenia z sejfu Fernet.
    UWAGA: Wyrzuca wyjątek PermissionError, jeśli użytkownik wycofał zgodę!
    """
    if not has_consent(account_id):
        raise PermissionError(f"Brak zgody użytkownika na użycie konta '{account_id}'. Włącz zgodę w zakładce Konta.")
    return vault.get(f"account_{account_id}")

def register_oauth_account(account_id: str, name: str, service: str, token_data: dict, consent: bool = True) -> dict:
    """Zapisuje konto OAuth (tokeny w sejfie Fernet, rekord w bazie)."""
    vault.put(f"account_{account_id}", token_data)
    db.execute(
        "INSERT INTO accounts(id, name, service, auth_type, consent, status) VALUES (?, ?, ?, 'oauth', ?, 'connected') "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, service=excluded.service, consent=excluded.consent, status='connected', updated=CURRENT_TIMESTAMP",
        (account_id, name, service, 1 if consent else 0)
    )
    return get_account(account_id)

def register_credentials_account(account_id: str, name: str, service: str, username: str, password: str, consent: bool = True) -> dict:
    """Zapisuje konto z loginem/hasłem w sejfie Fernet."""
    creds = {
        "username": username,
        "password": password,
        "saved_at": time.time()
    }
    vault.put(f"account_{account_id}", creds)
    db.execute(
        "INSERT INTO accounts(id, name, service, auth_type, consent, status) VALUES (?, ?, ?, 'credentials', ?, 'connected') "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, service=excluded.service, consent=excluded.consent, status='connected', updated=CURRENT_TIMESTAMP",
        (account_id, name, service, 1 if consent else 0)
    )
    return get_account(account_id)

def disconnect_account(account_id: str) -> bool:
    """Odłącza konto: usuwa dane z sejfu Fernet oraz z bazy danych."""
    vault.delete(f"account_{account_id}")
    if account_id == "gmail":
        vault.delete("gmail_oauth")
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return True

def has_connected_accounts() -> bool:
    """Sprawdza, czy w systemie jest podłączone jakiekolwiek konto (poczta lub konto serwisowe)."""
    rows = db.query("SELECT COUNT(*) AS c FROM accounts")
    if rows and rows[0]["c"] > 0:
        return True
    if vault.get("gmail_oauth"):
        return True
    return False

# ----------------- KOLEJKA DO ZATWIERDZENIA (Pending Actions) -----------------
SENSITIVE_ACTION_TYPES = {"send", "purchase", "publish", "post", "buy", "order", "delete"}

def request_action_approval(agent_id: str, action_type: str, description: str, payload: dict) -> dict:
    """Wstrzymuje wykonanie akcji agenta i dodaje ją do kolejki do zatwierdzenia w UI."""
    action_id = f"act_{uuid.uuid4().hex[:12]}"
    payload_str = json.dumps(payload, ensure_ascii=False)
    db.execute(
        "INSERT INTO pending_actions(id, agent_id, action_type, description, payload_json, status) VALUES (?, ?, ?, ?, ?, 'pending')",
        (action_id, agent_id, action_type, description, payload_str)
    )
    return {
        "id": action_id,
        "agent_id": agent_id,
        "action_type": action_type,
        "description": description,
        "payload": payload,
        "status": "pending"
    }

def list_pending_actions(status: str = "pending") -> list[dict]:
    rows = db.query(
        "SELECT id, agent_id, action_type, description, payload_json, status, created, decided_at FROM pending_actions WHERE status = ? ORDER BY id DESC",
        (status,)
    )
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except Exception:
            p = {}
        out.append({
            "id": r["id"],
            "agent_id": r["agent_id"],
            "action_type": r["action_type"],
            "description": r["description"],
            "payload": p,
            "status": r["status"],
            "created": r["created"],
            "decided_at": r["decided_at"]
        })
    return out

def approve_action(action_id: str) -> dict:
    rows = db.query("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
    if not rows:
        raise ValueError("Akcja nie została znaleziona")
    db.execute("UPDATE pending_actions SET status = 'approved', decided_at = CURRENT_TIMESTAMP WHERE id = ?", (action_id,))
    return {"id": action_id, "status": "approved"}

def reject_action(action_id: str) -> dict:
    rows = db.query("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
    if not rows:
        raise ValueError("Akcja nie została znaleziona")
    db.execute("UPDATE pending_actions SET status = 'rejected', decided_at = CURRENT_TIMESTAMP WHERE id = ?", (action_id,))
    return {"id": action_id, "status": "rejected"}

# ----------------- OBSŁUGA 2FA / CAPTCHA (Zakaz obchodzenia) -----------------
def request_2fa(account_id: str, prompt: str) -> dict:
    """Agent pauzuje i pyta użytkownika o kod 2FA."""
    req_id = f"2fa_{uuid.uuid4().hex[:10]}"
    db.execute("UPDATE accounts SET status = 'needs_2fa' WHERE id = ?", (account_id,))
    db.execute(
        "INSERT INTO pending_2fa(id, account_id, prompt, status) VALUES (?, ?, ?, 'waiting')",
        (req_id, account_id, prompt)
    )
    return {
        "status": "needs_2fa",
        "2fa_id": req_id,
        "account_id": account_id,
        "prompt": prompt
    }

def submit_2fa_code(req_id: str, code: str) -> dict:
    rows = db.query("SELECT * FROM pending_2fa WHERE id = ?", (req_id,))
    if not rows:
        raise ValueError("Żądanie 2FA nie zostało odnalezione")
    acc_id = rows[0]["account_id"]
    db.execute("UPDATE pending_2fa SET code = ?, status = 'resolved', resolved_at = CURRENT_TIMESTAMP WHERE id = ?", (code, req_id))
    db.execute("UPDATE accounts SET status = 'connected' WHERE id = ?", (acc_id,))
    return {"id": req_id, "account_id": acc_id, "status": "resolved", "code": code}

def list_pending_2fa() -> list[dict]:
    rows = db.query("SELECT id, account_id, prompt, status, created FROM pending_2fa WHERE status = 'waiting' ORDER BY id DESC")
    return [dict(r) for r in rows]
