"""Bot Wideo — generator wideo AI z promptu.
Faza 1: darmowy Space HF Lightricks/ltx-video-distilled przez gradio_client.
Faza 2: modele Wan 2.1 1.3B i LTX diffusers na workerze GPU Vast.ai.
Sklejanie klipów przez FFmpeg, kolejka zadań, pobieranie MP4.
"""
import os, subprocess, tempfile, time, json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from core import db, config, queue, alerts, vault
from core.registry import BotBase, register
from .providers.hf_ltx import HFLtxProvider, QuotaError

VIDEOS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "videos"))
os.makedirs(VIDEOS_DIR, exist_ok=True)

class VideoRequest(BaseModel):
    prompt: str
    negative_prompt: str = "worst quality, inconsistent motion, blurry, jittery, distorted"
    model: str = "hf_ltx"  # 'hf_ltx', 'wan2.1_1.3b', 'ltx_diffusers'
    clips: int = 1         # 1–6
    duration: int = 4      # s per clip
    aspect: str = "16:9"   # '16:9', '9:16', '1:1'
    style: str = "cinematic"
    seed: int = 42

def concat_clips_ffmpeg(clip_paths: list[str], out_mp4: str):
    """Łączy listę klipów MP4 w jeden plik za pomocą FFmpeg concat demuxera."""
    if len(clip_paths) == 1:
        # Skopiuj pojedynczy plik
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip_paths[0], "-c", "copy", out_mp4], check=True)
        return

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        list_file = f.name
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            out_mp4
        ]
        subprocess.run(cmd, check=True)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)

def execute_video_job(job_id: int, payload: dict) -> dict:
    """Wykonywane asynchronicznie przez worker kolejki w tle."""
    prompt = payload.get("prompt", "")
    model = payload.get("model", "hf_ltx")
    clips_count = max(1, min(int(payload.get("clips", 1)), 6))
    aspect = payload.get("aspect", "16:9")
    style = payload.get("style", "cinematic")
    duration = int(payload.get("duration", 4))
    final_mp4 = os.path.join(VIDEOS_DIR, f"{job_id}.mp4")

    # Faza 2: Worker GPU na Vast.ai
    if model in ("wan2.1_1.3b", "ltx_diffusers") or config.PHASE2_LOCAL_VIDEO:
        worker_url = vault.secret("worker", "url", "ORBIT_WORKER_URL") or config.WORKER_URL
        worker_tok = vault.secret("worker", "token", "WORKER_TOKEN")
        if not worker_url:
            raise RuntimeError("Brak skonfigurowanego adresu URL workera GPU w sejfie 'worker' lub env ORBIT_WORKER_URL")
        import requests
        headers = {"Authorization": f"Bearer {worker_tok}"} if worker_tok else {}
        resp = requests.post(f"{worker_url.rstrip('/')}/video", json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        res_data = resp.json()
        # Pobierz wynikowy plik do data/videos/
        file_url = res_data.get("download_url") or f"{worker_url.rstrip('/')}/files/{res_data.get('file_id')}.mp4"
        dl = requests.get(file_url, headers=headers, stream=True, timeout=120)
        dl.raise_for_status()
        with open(final_mp4, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                f.write(chunk)

        alerts.notify("video", f"Wideo wygenerowane ({model})", f"Zadanie #{job_id}: {prompt[:60]}")
        return {
            "status": "ok",
            "file": final_mp4,
            "clips": clips_count,
            "prompt": prompt,
            "model": model,
            "download_url": f"/api/video/download/{job_id}"
        }

    # Faza 1: HF Space przez gradio_client
    provider = HFLtxProvider()
    avail, err = provider.available()
    if not avail:
        raise RuntimeError(f"Dostawca HF LTX niedostępny: {err}")

    temp_clips = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            for idx in range(clips_count):
                clip_path = os.path.join(tmp_dir, f"clip_{idx}.mp4")
                provider.generate_clip(
                    prompt=prompt,
                    duration=duration,
                    aspect=aspect,
                    style=style,
                    out_path=clip_path,
                    idx=idx
                )
                temp_clips.append(clip_path)

            concat_clips_ffmpeg(temp_clips, final_mp4)
        except QuotaError as qe:
            friendly_err = f"Limit ZeroGPU Hugging Face został wyczerpany na publicznym Space. Szczegóły: {qe}"
            alerts.notify("video", "Limit Hugging Face Space wyczerpany", friendly_err[:200])
            raise RuntimeError(friendly_err)
        except Exception as e:
            msg = str(e)
            if "quota" in msg.lower() or "busy" in msg.lower() or "exceeded" in msg.lower():
                friendly_err = f"Space Hugging Face jest przeciążony lub wyczerpał limit. Komunikat: {msg[:200]}"
                alerts.notify("video", "Błąd limitu HF", friendly_err[:200])
                raise RuntimeError(friendly_err)
            raise

    alerts.notify("video", "Wideo gotowe do pobrania", f"Zadanie #{job_id}: {prompt[:60]} ({clips_count} klipów)")
    return {
        "status": "ok",
        "file": final_mp4,
        "clips": clips_count,
        "prompt": prompt,
        "model": model,
        "download_url": f"/api/video/download/{job_id}"
    }

# Rejestracja handlera w kolejce
queue.register_handler("video", "generate", execute_video_job)

class VideoBot(BotBase):
    id = "video"
    name = "Wideo"
    avatar = "comet"
    description = "Generowanie wideo AI: prompt, kolejka zadań, łączenie klipów FFmpeg, pobieranie MP4."

    def status(self):
        hf_avail, _ = HFLtxProvider().available()
        return {
            "hf_ltx_space": HFLtxProvider.name,
            "hf_available": hf_avail,
            "local_gpu_enabled": config.PHASE2_LOCAL_VIDEO,
            "stored_videos": len([f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")]),
            "available_models": [
                {"id": "hf_ltx", "name": "Lightricks LTX-Video Distilled (Darmowy HF Space)", "phase": 1},
                {"id": "wan2.1_1.3b", "name": "Wan 2.1 1.3B (Worker Vast.ai GPU)", "phase": 2},
                {"id": "ltx_diffusers", "name": "LTX-Video diffusers (Worker Vast.ai GPU)", "phase": 2}
            ]
        }

    def init(self, app):
        router = APIRouter(prefix="/api/video", tags=["video"])

        @router.post("/generate")
        def generate(req: VideoRequest):
            if not req.prompt or not req.prompt.strip():
                raise HTTPException(status_code=400, detail="Prompt nie może być pusty")

            is_gpu = req.model in ("wan2.1_1.3b", "ltx_diffusers") or config.PHASE2_LOCAL_VIDEO
            job_id = queue.enqueue("video", "generate", req.model_dump(), gpu=is_gpu)
            return {"job_id": job_id, "status": "queued", "gpu": is_gpu}

        @router.get("/jobs")
        def get_jobs(limit: int = 30):
            return queue.list_jobs(limit=limit, bot="video")

        @router.get("/jobs/{job_id}")
        def get_job(job_id: int):
            j = queue.get_job(job_id)
            if not j or j.get("bot") != "video":
                raise HTTPException(status_code=404, detail="Zadanie nie zostało znalezione")
            return j

        @router.get("/download/{job_id}")
        def download(job_id: int):
            mp4_path = os.path.join(VIDEOS_DIR, f"{job_id}.mp4")
            if not os.path.exists(mp4_path):
                raise HTTPException(status_code=404, detail="Plik wideo nie istnieje lub jeszcze nie został wygenerowany")
            return FileResponse(mp4_path, media_type="video/mp4", filename=f"orbit_video_{job_id}.mp4")

        @router.get("/status")
        def st():
            return self.status()

        app.include_router(router)

register(VideoBot())
