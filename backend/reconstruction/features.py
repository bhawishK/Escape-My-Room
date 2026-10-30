"""Features for the positioning map, from Hugging Face models (needs torch and transformers).

- **Local:** SuperPoint (`magic-leap-community/superpoint`), the strongest 2048 keypoints per frame.
  Its weights are licensed for non-commercial use only, which suits the contest. Frames are shrunk
  to 640 px on the long side, keeping their shape, and keypoints come back in the frame's own
  pixels, measured from the image's corner like COLMAP's and gsplat's `K` (a pixel's centre is at
  +0.5).
- **Global:** DINOv2 (`facebook/dinov2-small`): its class token and mean patch token, joined and
  normalised, to pick the map frames worth matching.

The phone's frames (#133) must use the same models; `map.json` names them. Each frame is a file
or, for the phone's frames, its JPEG bytes.
"""

# torch and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

from pathlib import Path
from typing import BinaryIO

import numpy as np

LOCAL_MODEL = "magic-leap-community/superpoint"
GLOBAL_MODEL = "facebook/dinov2-small"
MAX_KEYPOINTS = 2048
# SuperPoint's input: the long side in pixels, both sides a multiple of 8.
DETECTION_SIDE = 640


class HuggingFaceExtractor:
    local_model = LOCAL_MODEL
    global_model = f"{GLOBAL_MODEL} (class + mean patch token)"

    def __init__(self, device: str = "cuda") -> None:
        from transformers import AutoImageProcessor, AutoModel, SuperPointForKeypointDetection

        self.device = device
        # Both models are public. A Hugging Face login stored on the machine is never sent: an
        # expired one makes the Hub refuse even public models (it did on the GPU desktop, #139).
        public = {"token": False}
        self.local_processor = AutoImageProcessor.from_pretrained(LOCAL_MODEL, **public)
        self.local_net = SuperPointForKeypointDetection.from_pretrained(LOCAL_MODEL, **public)
        self.local_net.to(device)
        self.global_processor = AutoImageProcessor.from_pretrained(GLOBAL_MODEL, **public)
        self.global_net = AutoModel.from_pretrained(GLOBAL_MODEL, **public).to(device)
        self.local_net.eval()
        self.global_net.eval()

    def local(self, image: Path | BinaryIO) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        import torch
        from PIL import Image

        picture = Image.open(image).convert("RGB")
        shrink = DETECTION_SIDE / max(picture.size)
        size = {
            "height": max(8, round(picture.height * shrink / 8) * 8),
            "width": max(8, round(picture.width * shrink / 8) * 8),
        }
        inputs = self.local_processor(picture, size=size, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.local_net(**inputs)
        [found] = self.local_processor.post_process_keypoint_detection(
            outputs, [(picture.height, picture.width)]
        )
        scores = found["scores"].cpu().numpy()
        strongest = np.argsort(-scores)[:MAX_KEYPOINTS]
        # transformers gives keypoints as pixel indices; +0.5 puts them on the pixel's centre.
        keypoints = found["keypoints"].cpu().numpy()[strongest] + 0.5
        return (
            keypoints.astype(np.float32),
            found["descriptors"].cpu().numpy()[strongest].astype(np.float32),
            scores[strongest].astype(np.float32),
        )

    def global_descriptor(self, image: Path | BinaryIO) -> np.ndarray:
        import torch
        from PIL import Image

        inputs = self.global_processor(Image.open(image).convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            tokens = self.global_net(**inputs.to(self.device)).last_hidden_state[0]
        joined = torch.cat([tokens[0], tokens[1:].mean(dim=0)])
        return torch.nn.functional.normalize(joined, dim=0).cpu().numpy().astype(np.float32)
