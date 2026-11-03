"""Serwer GPU Workera Orbit Bots (FastAPI, port 8000).
Wymaga nagłówka Bearer WORKER_TOKEN.
Zarządza pamięcią GPU i blokadami (gpu_lock):
- Chat: Ollama dolphin3:8b (127.0.0.1:11434/v1)
- Video: Wan 2.1 1.3B lub LTX diffusers
- Łączenie klipów FFmpeg
"""
import os, subprocess, tempfile, uuid
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests

from gpu_lock import gpu_lock
try:
    from video.wan import generate_wan_clip
except ImportError:
    generate_wan_clip = None
try:
    from video.ltx import generate_ltx_clip
except ImportError:
    generate_ltx_clip = None

WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "orbit-worker-secret-token")
OLLAMA_API = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434")
OUTPUT_DIR = os.environ.get("WORKER_OUTPUT_DIR", "/tmp/orbit_worker_videos")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Orbit GPU Worker", version="1.0.0")
security = HTTPBearer(auto_error=False)

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Brak lub niepoprawny nagłówek autoryzacji Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != WORKER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy token autoryzacji",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = "dolphin3:8b"
    messages: list[ChatMessage]
    temperature: float = 0.3
    max_tokens: int = 1000

class VideoGenerationRequest(BaseModel):
    prompt: str
    negative_prompt: str = "worst quality, blurry, distorted"
    model: str = "wan2.1_1.3b"  # 'wan2.1_1.3b' or 'ltx_diffusers'
    clips: int = 1
    duration: int = 4
    steps: int = 30
    seed: int = 42

@app.get("/health")
def health(token: str = Depends(verify_token)):
    cuda_avail = False
    gpu_name = "N/A"
    try:
        import torch
        cuda_avail = torch.cuda.is_available()
        if cuda_avail:
            gpu_name = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    ollama_ok = False
    try:
        r = requests.get(f"{OLLAMA_API}/api/version", timeout=2)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "gpu": cuda_avail,
        "gpu_name": gpu_name,
        "ollama": ollama_ok,
        "available_models": ["dolphin3:8b", "wan2.1_1.3b", "ltx_diffusers"]
    }

@app.post("/chat")
def chat_completion(req: ChatRequest, token: str = Depends(verify_token)):
    gpu_lock.acquire_for_chat()
    try:
        url = f"{OLLAMA_API}/v1/chat/completions"
        payload = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Błąd Ollama: {str(e)}")
    finally:
        gpu_lock.release_from_chat()

@app.post("/video")
def generate_video(req: VideoGenerationRequest, token: str = Depends(verify_token)):
    file_id = str(uuid.uuid4())
    final_output = os.path.join(OUTPUT_DIR, f"{file_id}.mp4")

    # Blokada GPU i zwolnienie Ollamy z pamięci
    gpu_lock.acquire_for_video()
    pipe = None
    try:
        clips_count = max(1, min(req.clips, 6))
        clip_files = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(clips_count):
                clip_path = os.path.join(tmp_dir, f"clip_{i}.mp4")
                clip_seed = req.seed + i * 100

                if req.model == "wan2.1_1.3b":
                    if generate_wan_clip is None:
                        raise RuntimeError("Brak implementacji Wan 2.1")
                    pipe = generate_wan_clip(
                        prompt=req.prompt,
                        negative_prompt=req.negative_prompt,
                        out_path=clip_path,
                        steps=req.steps,
                        seed=clip_seed
                    )
                elif req.model == "ltx_diffusers":
                    if generate_ltx_clip is None:
                        raise RuntimeError("Brak implementacji LTX")
                    pipe = generate_ltx_clip(
                        prompt=req.prompt,
                        negative_prompt=req.negative_prompt,
                        out_path=clip_path,
                        steps=req.steps,
                        seed=clip_seed
                    )
                else:
                    raise HTTPException(status_code=400, detail=f"Nieznany model: {req.model}")

                clip_files.append(clip_path)

            # FFmpeg concat
            if len(clip_files) == 1:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip_files[0], "-c", "copy", final_output], check=True)
            else:
                list_txt = os.path.join(tmp_dir, "concat.txt")
                with open(list_txt, "w") as f:
                    for cf in clip_files:
                        f.write(f"file '{cf}'\n")
                subprocess.run([
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", list_txt, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    final_output
                ], check=True)

        return {
            "status": "ok",
            "file_id": file_id,
            "clips": clips_count,
            "download_url": f"/files/{file_id}.mp4"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania wideo: {str(e)}")
    finally:
        gpu_lock.release_from_video(pipe)

@app.get("/files/{file_id}.mp4")
def get_file(file_id: str, token: str = Depends(verify_token)):
    safe_id = "".join(c for c in file_id if c.isalnum() or c == "-")
    p = os.path.join(OUTPUT_DIR, f"{safe_id}.mp4")
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Plik nie istnieje")
    return FileResponse(p, media_type="video/mp4", filename=f"{safe_id}.mp4")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
