"""Sejf danych dostępowych (Fernet). Klucz trzymany POZA repo: ~/.orbit/vault.key (chmod 600)
lub w zmiennej środowiskowej ORBIT_VAULT_KEY_B64 (np. na Renderze) / ORBIT_VAULT_KEY.
Wartości nigdy nie są zwracane do UI ani logów — tylko informacja, czy istnieją."""
import os, json
from cryptography.fernet import Fernet
from . import db

def get_key_path():
    if os.environ.get("ORBIT_VAULT_KEY"):
        return os.environ["ORBIT_VAULT_KEY"]
    home_p = os.path.expanduser("~/.orbit/vault.key")
    try:
        os.makedirs(os.path.dirname(home_p), exist_ok=True)
        return home_p
    except OSError:
        return "/tmp/.orbit/vault.key"

KEY_PATH = get_key_path()

db.init("CREATE TABLE IF NOT EXISTS vault(name TEXT PRIMARY KEY, blob BLOB, updated TEXT DEFAULT CURRENT_TIMESTAMP);")

def _f():
    env_b64 = os.environ.get("ORBIT_VAULT_KEY_B64")
    if env_b64:
        return Fernet(env_b64.encode().strip())
    kp = get_key_path()
    if not os.path.exists(kp):
        os.makedirs(os.path.dirname(kp), mode=0o700, exist_ok=True)
        with open(kp, "wb") as fh:
            fh.write(Fernet.generate_key())
        try:
            os.chmod(kp, 0o600)
        except OSError:
            pass
    return Fernet(open(kp, "rb").read().strip())

def put(name, data: dict):
    db.execute("INSERT OR REPLACE INTO vault(name,blob) VALUES(?,?)", (name, _f().encrypt(json.dumps(data).encode())))

def get(name):
    r = db.query("SELECT blob FROM vault WHERE name=?", (name,))
    return json.loads(_f().decrypt(r[0]["blob"])) if r else None

def names():
    return [r["name"] for r in db.query("SELECT name,updated FROM vault")]

def delete(name):
    db.execute("DELETE FROM vault WHERE name=?", (name,))

def secret(vault_name, field, env=None):
    """Najpierw zmienna środowiskowa, potem sejf. Zwraca None gdy brak klucza."""
    if env and os.environ.get(env):
        return os.environ[env]
    d = get(vault_name)
    return (d or {}).get(field)
