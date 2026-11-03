"""Testy akceptacyjne 7 i 8:
Worker: /health ok, autoryzacja Bearer WORKER_TOKEN (bez tokenu zwraca 401),
port 11434 jest niedostępny z zewnątrz (tylko localhost),
sklejanie klipów FFmpeg.
"""
import os, sys, tempfile, subprocess
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
import server
from bots.video.bot import concat_clips_ffmpeg

def test_worker_auth_401_without_token():
    client = TestClient(server.app)

    # Bez nagłówka Authorization -> 401
    r_no_auth = client.get("/health")
    assert r_no_auth.status_code == 401, f"Oczekiwano 401 bez tokenu, otrzymano {r_no_auth.status_code}"

    # Ze złym tokenem -> 401
    r_bad_auth = client.get("/health", headers={"Authorization": "Bearer zly-token"})
    assert r_bad_auth.status_code == 401, f"Oczekiwano 401 przy złym tokenie, otrzymano {r_bad_auth.status_code}"

    # Z poprawnym tokenem -> 200
    valid_token = server.WORKER_TOKEN
    r_ok = client.get("/health", headers={"Authorization": f"Bearer {valid_token}"})
    assert r_ok.status_code == 200, f"Oczekiwano 200 z poprawnym tokenem, otrzymano {r_ok.status_code}"
    data = r_ok.json()
    assert data["status"] == "ok"
    assert "available_models" in data

def test_worker_ollama_port_not_exposed():
    # Sprawdź definicję w Dockerfile i onstart.sh
    dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "worker", "Dockerfile")
    with open(dockerfile_path, "r", encoding="utf-8") as f:
        dockerfile_content = f.read()

    # Port 11434 nie może być eksponowany w Dockerfile
    assert "EXPOSE 11434" not in dockerfile_content, "BŁĄD BEZPIECZEŃSTWA: Port 11434 Ollama jest wyeksponowany w Dockerfile!"
    assert "EXPOSE 8000" in dockerfile_content, "Port 8000 powinien być jedynym wyeksponowanym portem workera"
    assert "ENV OLLAMA_HOST=127.0.0.1:11434" in dockerfile_content, "Ollama musi nasłuchiwać wyłącznie na 127.0.0.1"

    # Sprawdź onstart.sh
    onstart_path = os.path.join(os.path.dirname(__file__), "..", "worker", "onstart.sh")
    with open(onstart_path, "r", encoding="utf-8") as f:
        onstart_content = f.read()
    assert "127.0.0.1:11434" in onstart_content

def test_ffmpeg_concat_two_clips():
    """Weryfikuje sklejanie 2 klipów wideo w jeden plik MP4 przez FFmpeg."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        clip1 = os.path.join(tmp_dir, "clip1.mp4")
        clip2 = os.path.join(tmp_dir, "clip2.mp4")
        final_mp4 = os.path.join(tmp_dir, "final.mp4")

        # Wygeneruj 2 krótkie testowe klipy (np. 1-sekundowy syntetyczny testowy obraz z anullsrc audio)
        cmd1 = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip1
        ]
        cmd2 = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip2
        ]
        subprocess.run(cmd1, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        assert os.path.exists(clip1) and os.path.getsize(clip1) > 0
        assert os.path.exists(clip2) and os.path.getsize(clip2) > 0

        # Połącz klipy
        concat_clips_ffmpeg([clip1, clip2], final_mp4)

        assert os.path.exists(final_mp4)
        assert os.path.getsize(final_mp4) > 0

        # Sprawdź długość (powinna wynosić ok. 2 s)
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", final_mp4
        ], capture_output=True, text=True, check=True)
        duration = float(probe.stdout.strip())
        assert 1.8 <= duration <= 2.2, f"Oczekiwano długości ~2s po sklejeniu dwóch klipów 1s, otrzymano {duration}"
