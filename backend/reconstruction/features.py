"""Features for the positioning map, from Hugging Face models (needs torch and transformers).

- **Local:** SuperPoint (`magic-leap-community/superpoint`), the strongest 2048 keypoints per frame.
  Its weights are licensed for non-commercial use only, which suits the contest.
- **Global:** DINOv2 (`facebook/dinov2-small`): its class token and mean patch token, joined and
  normalised, to pick the map frames worth matching.

The phone's frames (#133) must use the same models; `map.json` names them.
"""

# cv2, pycolmap, torch and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

from pathlib import Path

import numpy as np

LOCAL_MODEL = "magic-leap-community/superpoint"
GLOBAL_MODEL = "facebook/dinov2-small"
MAX_KEYPOINTS = 2048


class HuggingFaceExtractor:
    local_model = LOCAL_MODEL
    global_model = f"{GLOBAL_MODEL} (class + mean patch token)"

    def __init__(self, device: str = "cuda") -> None:
        from transformers import AutoImageProcessor, AutoModel, SuperPointForKeypointDetection

        self.device = device
        self.local_processor = AutoImageProcessor.from_pretrained(LOCAL_MODEL)
        self.local_net = SuperPointForKeypointDetection.from_pretrained(LOCAL_MODEL).to(device)
        self.global_processor = AutoImageProcessor.from_pretrained(GLOBAL_MODEL)
        self.global_net = AutoModel.from_pretrained(GLOBAL_MODEL).to(device)
        self.local_net.eval()
        self.global_net.eval()

    def local(self, image: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        import torch
        from PIL import Image

        picture = Image.open(image).convert("RGB")
        inputs = self.local_processor(picture, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.local_net(**inputs)
        [found] = self.local_processor.post_process_keypoint_detection(
            outputs, [(picture.height, picture.width)]
        )
        scores = found["scores"].cpu().numpy()
        strongest = np.argsort(-scores)[:MAX_KEYPOINTS]
        return (
            found["keypoints"].cpu().numpy()[strongest].astype(np.float32),
            found["descriptors"].cpu().numpy()[strongest].astype(np.float32),
            scores[strongest].astype(np.float32),
        )

    def global_descriptor(self, image: Path) -> np.ndarray:
        import torch
        from PIL import Image

        inputs = self.global_processor(Image.open(image).convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            tokens = self.global_net(**inputs.to(self.device)).last_hidden_state[0]
        joined = torch.cat([tokens[0], tokens[1:].mean(dim=0)])
        return torch.nn.functional.normalize(joined, dim=0).cpu().numpy().astype(np.float32)
