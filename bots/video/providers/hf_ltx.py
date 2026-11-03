import os, shutil, subprocess
class Provider: pass
SPACE = os.environ.get("HF_LTX_SPACE", "Lightricks/ltx-video-distilled")
# Małe rozdzielczości mieszczą się w anonimowym limicie ZeroGPU
DIMS = {"16:9": (256, 448), "9:16": (448, 256), "1:1": (320, 320)}
class QuotaError(RuntimeError): pass
class HFLtxProvider(Provider):
    """LTX-Video (Lightricks) na publicznym Space Hugging Face (ZeroGPU) przez gradio_client.
    Działa anonimowo; HF_TOKEN (darmowy) zwiększa dzienny limit GPU."""
    name = "hf_ltx"
    def available(self):
        try: import gradio_client  # noqa
        except ImportError: return False, "brak gradio_client"
        return True, ""
    def generate_clip(self, prompt, duration, aspect, style, out_path, idx):
        from gradio_client import Client
        h, w = DIMS.get(aspect, DIMS["16:9"])
        try:
            c = Client(SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
            r = c.predict(prompt=f"{prompt}, {style} style, shot {idx+1}",
                negative_prompt="worst quality, inconsistent motion, blurry, jittery, distorted",
                input_image_filepath=None, input_video_filepath=None,
                height_ui=h, width_ui=w, mode="text-to-video",
                duration_ui=max(1, min(int(duration), 5)), ui_frames_to_use=9,
                seed_ui=42, randomize_seed=True, ui_guidance_scale=1,
                improve_texture_flag=False, api_name="/text_to_video")
        except Exception as e:
            msg = str(e)
            if "quota" in msg.lower(): raise QuotaError(msg[:300])
            raise
        src = r[0]["video"] if isinstance(r[0], dict) else r[0]
        # normalizacja (sklejanie z innymi klipami, dźwięk AAC)
        subprocess.run(["ffmpeg","-y","-loglevel","error","-i",src,"-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
            "-c:v","libx264","-pix_fmt","yuv420p","-vf","scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a","aac","-shortest",out_path], check=True)
