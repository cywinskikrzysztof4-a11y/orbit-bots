"""Test akceptacyjny 9:
Ścieżka '../../x' oraz próby directory traversal w narzędziach zadania są bezwzględnie odrzucane.
"""
import pytest
from bots.daily.bot import TaskSandbox

def test_task_sandbox_rejects_path_traversal():
    sb = TaskSandbox("sec-test-task-123")

    traversal_payloads = [
        "../../x",
        "../../../etc/passwd",
        "sub/../../../../test.txt",
        "..\\..\\windows_traversal",
        "/etc/shadow",
        "normal/../../../danger.txt"
    ]

    for payload in traversal_payloads:
        with pytest.raises(ValueError, match="Niedozwolona próba wyjścia|Ścieżka poza dozwolonym"):
            sb.validate_path(payload)

        with pytest.raises(ValueError):
            sb.write(payload, "złośliwy kod")

def test_task_sandbox_accepts_valid_paths():
    sb = TaskSandbox("sec-test-task-123")

    # Dozwolona ścieżka wewnątrz sandboxa
    p1 = sb.write("test.txt", "poprawna zawartość")
    assert p1.startswith(sb.dir)
    assert sb.read("test.txt") == "poprawna zawartość"

    # Podkatalog wewnątrz sandboxa
    p2 = sb.write("subfolder/data.json", '{"ok": true}')
    assert p2.startswith(sb.dir)
    assert sb.read("subfolder/data.json") == '{"ok": true}'
