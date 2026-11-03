"""Generator wideo LTX-Video (LTXPipeline).
Rozdzielczość 704x480, 121 klatek.
"""
import os, torch

MODEL_ID = "Lightricks/LTX-Video"

def generate_ltx_clip(prompt: str, negative_prompt: str, out_path: str, steps: int = 30, seed: int = 42, height: int = 480, width: int = 704):
    try:
        from diffusers import LTXPipeline
        from diffusers.utils import export_to_video
    except ImportError:
        raise RuntimeError("diffusers nie jest zainstalowane na tym workerze")

    pipe = LTXPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
    if hasattr(pipe, "enable_model_cpu_offload"):
        pipe.enable_model_cpu_offload()

    generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)
    output = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=height,
        width=width,
        num_frames=121,
        num_inference_steps=steps,
        generator=generator
    ).frames[0]

    export_to_video(output, out_path, fps=24)
    return pipe
