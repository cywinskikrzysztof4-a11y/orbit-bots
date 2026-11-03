"""Test akceptacyjny 4:
Sejf: test zapisu i odczytu. Klucz leży poza repo, a sekret nie pojawia się w logach (grep).
"""
import os, stat
from core import vault, db

def test_vault_key_outside_repo():
    # Klucz poza repozytorium
    key_path = vault.get_key_path()
    repo_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    real_key_path = os.path.realpath(key_path)

    # Upewnij się, że klucz istnieje
    vault._f()
    assert os.path.exists(real_key_path)

    # Ścieżka klucza nie może znajdować się wewnątrz katalogu repozytorium
    assert not real_key_path.startswith(repo_dir), f"Klucz sejfu znajduje się wewnątrz repo: {real_key_path}"

    # Prawa dostępu do klucza (0600)
    st = os.stat(real_key_path)
    mode = stat.S_IMODE(st.st_mode)
    assert mode == 0o600, f"Uprawnienia klucza to {oct(mode)}, oczekiwano 0600"

def test_vault_put_and_get():
    secret_value = "super-tajny-klucz-fernet-12345"
    vault.put("vast_test", {"api_key": secret_value, "instance": "inst-456"})

    loaded = vault.get("vast_test")
    assert loaded is not None
    assert loaded["api_key"] == secret_value
    assert loaded["instance"] == "inst-456"

    # Tylko nazwy są widoczne
    names = vault.names()
    assert "vast_test" in names

    # Sprawdź czy sekret nie znajduje się w plain-text w bazie danych (tabela vault)
    raw_rows = db.query("SELECT blob FROM vault WHERE name='vast_test'")
    blob_content = raw_rows[0]["blob"]
    assert secret_value.encode() not in blob_content, "Wartość sekretu zapisana jawnym tekstem w bazie!"

    # Sprawdź czy sekret nie pojawia się w logach jobs_log ani alerts_log
    job_logs = db.query("SELECT * FROM jobs_log")
    for row in job_logs:
        assert secret_value not in str(row), "Sekret wyciekł do jobs_log!"

    alert_logs = db.query("SELECT * FROM alerts_log")
    for row in alert_logs:
        assert secret_value not in str(row), "Sekret wyciekł do alerts_log!"
