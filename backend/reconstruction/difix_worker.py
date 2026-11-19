"""Difix3D+'s side of a repair round (#215): runs in Difix's own env, never the project's.

    PYTHONPATH=~/difix/src ~/difix/.venv/bin/python difix_worker.py FOLDER

Repairs each FOLDER/<n>-render.png, guided by <n>-reference.png, into <n>-fixed.png at the render's
size: one step at timestep 199 with "remove degradation", as Difix's README runs it. Half precision
with the decoder in slices fits the desktop's 8 GB (3.4 GB peak at 640 x 480).
"""

# Difix's env has torch and its pipeline; the project's checks don't.
# pyright: basic
# pyright: reportMissingImports=false

import sys
from pathlib import Path

import torch
from PIL import Image
from pipeline_difix import DifixPipeline


def main() -> None:
    folder = Path(sys.argv[1])
    pipe = DifixPipeline.from_pretrained("nvidia/difix_ref", torch_dtype=torch.float16)
    pipe.to("cuda")
    pipe.enable_vae_slicing()
    pipe.enable_attention_slicing()
    pipe.set_progress_bar_config(disable=True)
    for render in sorted(folder.glob("*-render.png")):
        image = Image.open(render).convert("RGB")
        reference = Image.open(render.with_name(render.name.replace("-render", "-reference")))
        # Difix works in multiples of 8 pixels; the repair is put back at the render's size.
        width, height = image.width // 8 * 8, image.height // 8 * 8
        with torch.inference_mode():
            fixed = pipe(
                "remove degradation",
                image=image.resize((width, height)),
                ref_image=reference.convert("RGB").resize((width, height)),
                height=height,
                width=width,
                num_inference_steps=1,
                timesteps=[199],
                guidance_scale=0.0,
            ).images[0]
        fixed.resize(image.size, Image.Resampling.LANCZOS).save(
            render.with_name(render.name.replace("-render", "-fixed"))
        )


if __name__ == "__main__":
    main()
