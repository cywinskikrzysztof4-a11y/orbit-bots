"""Bot Wideo — generator wideo AI z promptu.
Faza 1: darmowy Space HF Lightricks/ltx-video-distilled przez gradio_client.
Faza 2: modele Wan 2.1 1.3B i LTX diffusers na workerze GPU Vast.ai.
Sklejanie klipów przez FFmpeg, kolejka zadań, pobieranie MP4.
Wspiera autonomicznego agenta Gemini (core.agent.Agent) z narzędziami:
- ltx_enqueue, ltx_status.
"""
import os, subprocess, tempfile, time, json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from core import db, config, queue, alerts, vault
from core.agent import Agent, Tool, AgentResult
from core.registry import BotBase, register
from .providers.hf_ltx import HFLtxProvider, QuotaError

VIDEOS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "videos"))
os.makedirs(VIDEOS_DIR, exist_ok=True)

db.init("""
CREATE TABLE IF NOT EXISTS vid_memory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
""")

class VideoRequest(BaseModel):
    prompt: str
    negative_prompt: str = "worst quality, inconsistent motion, blurry, jittery, distorted"
    model: str = "hf_ltx"  # 'hf_ltx', 'wan2.1_1.3b', 'ltx_diffusers'
    clips: int = 1         # 1–6
    duration: int = 4      # s per clip
    aspect: str = "16:9"   # '16:9', '9:16', '1:1'
    style: str = "cinematic"
    seed: int = 42

class VideoChatRequest(BaseModel):
    session: str = "default"
    message: str

def concat_clips_ffmpeg(clip_paths: list[str], out_mp4: str):
    """Łączy listę klipów MP4 w jeden plik za pomocą FFmpeg concat demuxera."""
    if len(clip_paths) == 1:
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
                seed = int(payload.get("seed", 42)) + idx * 10
                provider.generate_clip(
                    prompt=prompt,
                    out_path=clip_path,
                    negative_prompt=payload.get("negative_prompt", ""),
                    seed=seed
                )
                temp_clips.append(clip_path)

            concat_clips_ffmpeg(temp_clips, final_mp4)
        except QuotaError as qe:
            friendly_err = f"Limit darmowego HF Space został wyczerpany: {qe}. Spróbuj za chwilę."
            alerts.notify("video", "Błąd limitu HF", friendly_err[:200])
            raise RuntimeError(friendly_err)
        except Exception:
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

queue.register_handler("video", "generate", execute_video_job)

# ----------------- FUNKCJE NARZĘDZI AGENTA WIDEO -----------------

def tool_ltx_enqueue(
    prompt: str,
    duration: int = 4,
    aspect: str = "16:9",
    clips: int = 1,
    model: str = "hf_ltx",
    style: str = "cinematic",
    seed: int = 42
) -> dict:
    """Dodaje nowe zadanie generowania wideo do kolejki."""
    if not prompt or not prompt.strip():
        return {"error": "Prompt wideo nie może być pusty."}

    payload = {
        "prompt": prompt.strip(),
        "duration": duration,
        "aspect": aspect,
        "clips": max(1, min(int(clips), 6)),
        "model": model,
        "style": style,
        "seed": seed
    }
    is_gpu = model in ("wan2.1_1.3b", "ltx_diffusers") or config.PHASE2_LOCAL_VIDEO
    job_id = queue.enqueue("video", "generate", payload, gpu=is_gpu)
    return {
        "job_id": job_id,
        "status": "queued",
        "prompt": prompt,
        "model": model,
        "clips": clips,
        "message": f"Zadanie wideo #{job_id} zostało pomyślnie dodane do kolejki."
    }

def tool_ltx_status(job_id: int | None = None) -> dict:
    """Sprawdza status wybranego zadania wideo lub listę ostatnich zadań."""
    if job_id is not None:
        job = queue.get_job(int(job_id))
        if not job:
            return {"error": f"Zadanie wideo #{job_id} nie istnieje."}
        return {
            "job_id": job["id"],
            "status": job["status"],
            "created": job.get("created"),
            "finished": job.get("finished"),
            "download_url": f"/api/video/download/{job['id']}" if job["status"] == "done" else None
        }
    else:
        jobs = queue.list_jobs(limit=10, bot="video")
        return {
            "count": len(jobs),
            "jobs": [
                {
                    "id": j["id"],
                    "status": j["status"],
                    "created": j.get("created"),
                    "finished": j.get("finished")
                }
                for j in jobs
            ]
        }

VIDEO_TOOLS = [
    Tool(
        name="ltx_enqueue",
        description="Dodaje nowe zadanie generowania wideo do kolejki (Lightricks LTX / Wan 2.1).",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Opis sceny wideo w języku angielskim"},
                "duration": {"type": "integer", "description": "Długość klipu w sekundach (domyślnie 4)", "default": 4},
                "aspect": {"type": "string", "description": "Format obrazu: '16:9', '9:16' lub '1:1'", "default": "16:9"},
                "clips": {"type": "integer", "description": "Liczba klipów do połączenia (1-6)", "default": 1},
                "model": {"type": "string", "description": "Model wideo ('hf_ltx', 'wan2.1_1.3b')", "default": "hf_ltx"},
                "style": {"type": "string", "description": "Styl wizualny, np. 'cinematic', 'anime'", "default": "cinematic"},
                "seed": {"type": "integer", "description": "Ziarno losowości", "default": 42}
            },
            "required": ["prompt"]
        },
        handler=tool_ltx_enqueue,
        summary_fn=lambda r: f"Dodano zadanie wideo #{r.get('job_id')} do kolejki (status: {r.get('status')})"
    ),
    Tool(
        name="ltx_status",
        description="Sprawdza status wybranego zadania wideo lub pobiera listę ostatnich zadań w kolejce.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "Opcjonalny identyfikator konkretnego zadania wideo"}
            }
        },
        handler=tool_ltx_status,
        summary_fn=lambda r: f"Zadanie #{r.get('job_id')}: status {r.get('status')}" if "job_id" in r else f"Pobrano {r.get('count', 0)} ostatnich zadań wideo"
    )
]

def get_video_agent() -> Agent:
    return Agent(
        name="video",
        system_prompt=(
            "Jesteś Agentem Wideo — asystentem kreatywnym Orbit Bots do generowania wideo AI. "
            "Odpowiadasz po polsku. "
            "Posiadasz narzędzia do dodawania zadań wideo do kolejki (ltx_enqueue) "
            "oraz sprawdzania statusu i pobierania wygenerowanych filmów (ltx_status). "
            "Gdy użytkownik chce wygenerować wideo, pomóż mu doprecyzować prompt po angielsku i wywołaj ltx_enqueue. "
            "Gdy pyta o stan zadania, sprawdź ltx_status."
        ),
        tools=VIDEO_TOOLS,
        max_steps=6
    )

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
            ],
            "agent_tools": [t.name for t in VIDEO_TOOLS]
        }

    def run(self, session: str, msg: str) -> dict:
        """Pętla konwersacyjna Agenta Wideo."""
        mem = db.query("SELECT role, content FROM vid_memory WHERE session=? ORDER BY id DESC LIMIT 10", (session,))[::-1]
        db.execute("INSERT INTO vid_memory(session, role, content) VALUES(?, 'user', ?)", (session, msg))

        if os.environ.get("LLM_API_KEY"):
            try:
                agent = get_video_agent()
                agent_res = agent.run(msg, history=mem)
                db.execute("INSERT INTO vid_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, agent_res.answer))
                return {
                    "answer": agent_res.answer,
                    "steps": agent_res.steps,
                    "paused": agent_res.paused,
                    "pause_reason": agent_res.pause_reason
                }
            except Exception as e:
                alerts.notify(self.id, "Błąd Agenta Wideo", str(e)[:200])

        # Tryb awaryjny / bez klucza
        msg_l = msg.lower()
        trace = []
        if "status" in msg_l or "kolejk" in msg_l:
            st = tool_ltx_status()
            ans = f"🎬 **Kolejka wideo ({st.get('count', 0)} ostatnich)**:\n"
            for j in st.get("jobs", []):
                ans += f"• Zadanie #{j['id']} — status: **{j['status']}** ({j.get('created', '')})\n"
            trace.append({"tool": "ltx_status", "result_summary": f"{st.get('count',0)} zadań"})
        else:
            ans = (
                "🎬 Cześć! Jestem **Agentem Wideo** Orbit Bots.\n\n"
                "Mogę wygenerować dla Ciebie wideo za pomocą darmowego modelu Lightricks LTX lub sprawdzić status kolejki.\n"
                "Napisz np. *„Wygeneruj wideo: neon city in rain”* albo *„Sprawdź status kolejki wideo”*."
            )

        db.execute("INSERT INTO vid_memory(session, role, content) VALUES(?, 'assistant', ?)", (session, ans))
        return {"answer": ans, "steps": trace}

    def init(self, app):
        router = APIRouter(prefix="/api/video", tags=["video"])

        @router.post("/chat")
        def chat(req: VideoChatRequest):
            try:
                return self.run(req.session or "default", req.message)
            except Exception as e:
                raise HTTPException(status_code=502, detail=str(e)[:300])

        @router.get("/history")
        def history(session: str = "default"):
            return db.query("SELECT role, content, created FROM vid_memory WHERE session=? ORDER BY id ASC", (session,))

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
