"""Generator wideo Wan 2.1 1.3B (WanPipeline).
Rozdzielczość 832x480 (480p), 81 klatek, ~8 GB VRAM z enable_model_cpu_offload().
"""
import os, torch

MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"

def generate_wan_clip(prompt: str, negative_prompt: str, out_path: str, steps: int = 30, seed: int = 42, height: int = 480, width: int = 832):
    try:
        from diffusers import WanPipeline
        from diffusers.utils import export_to_video
    except ImportError:
        raise RuntimeError("diffusers nie jest zainstalowane na tym workerze")

    pipe = WanPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.float16)
    pipe.enable_model_cpu_offload()

    generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)
    output = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_frames=81,
        num_inference_steps=steps,
        generator=generator
    ).frames[0]

    export_to_video(output, out_path, fps=16)
    return pipe
