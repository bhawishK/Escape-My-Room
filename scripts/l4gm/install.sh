#!/usr/bin/env bash
# L4GM for hazards' 4D step (#226), in its own Python 3.11 env on the GPU desktop.
#
#   bash scripts/l4gm/install.sh            # installs into ~/l4gm (ESCAPE_ROOM_L4GM_DIR to change)
#
# L4GM (NVIDIA, NeurIPS 2024) and its weights are Apache 2.0; ImageDream, which it uses for the
# first frame's views, is OpenRAIL. The fixes found by hand in spike #220 are built in:
# - torch 2.4.1 with CUDA 12.4, hard-linked from the SpatialLM env when there is one (no download);
# - kiui 0.2.14, as newer versions fail to import;
# - weights fetched without any saved Hugging Face login, as an expired one breaks the download;
# - infer_4d_ply.py, L4GM's infer_4d.py that also saves each frame's splat.
set -euo pipefail

L4GM_COMMIT=b857d670bda83a569e2bad774afe56483d7a8674
DIR=${ESCAPE_ROOM_L4GM_DIR:-$HOME/l4gm}
HERE=$(cd "$(dirname "$0")" && pwd)
CUDA=${CUDA_HOME:-/usr/local/cuda-12.8}
export PATH=$HOME/.local/bin:$CUDA/bin:$PATH CUDA_HOME=$CUDA PIP_DEFAULT_TIMEOUT=300

if [ ! -d "$DIR/.git" ]; then
  git clone -q https://github.com/nv-tlabs/L4GM-official.git "$DIR"
fi
git -C "$DIR" fetch -q origin
git -C "$DIR" checkout -q "$L4GM_COMMIT"

PY=$(mise where python@3.11 2>/dev/null)/bin/python3.11 || true
[ -x "$PY" ] || { mise install -y python@3.11 >/dev/null; PY=$(mise where python@3.11)/bin/python3.11; }
[ -d "$DIR/.venv" ] || "$PY" -m venv "$DIR/.venv"
SITE="$DIR/.venv/lib/python3.11/site-packages"

SPATIALLM="$HOME/spatiallm/.venv/lib/python3.11/site-packages"
if [ -d "$SPATIALLM/torch-2.4.1+cu124.dist-info" ]; then
  (cd "$SPATIALLM" && for d in torch torch-2.4.1* torchvision torchvision-0.19.1* torchvision.libs \
      functorch torchgen triton triton-* nvidia nvidia_*; do
    [ -e "$SITE/$d" ] || cp -al "$d" "$SITE/"
  done)
else
  "$DIR/.venv/bin/pip" install -q torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu124
fi

PIP="$DIR/.venv/bin/pip"
"$PIP" install -q --upgrade pip wheel setuptools ninja
"$PIP" install -q --no-deps xformers==0.0.28.post1 --index-url https://download.pytorch.org/whl/cu124
"$PIP" install -q "numpy<2" scipy rich einops opencv-python-headless tyro roma plyfile "kiui==0.2.14" \
  lpips imageio imageio-ffmpeg "accelerate==0.28.0" safetensors scikit-image scikit-learn tqdm \
  "diffusers==0.27.2" "huggingface_hub==0.23.5" "transformers<4.45" sentencepiece
"$PIP" install -q --no-build-isolation "git+https://github.com/nerfstudio-project/gsplat.git@v1.4.0"

mkdir -p "$DIR/pretrained"
for name in recon.safetensors interp.safetensors; do
  [ -s "$DIR/pretrained/$name" ] || curl -sSL --fail -o "$DIR/pretrained/$name" \
    "https://huggingface.co/jiawei011/L4GM/resolve/main/$name"
done

"$DIR/.venv/bin/python" "$HERE/ply_writer.py" "$DIR"
"$DIR/.venv/bin/python" -c "import torch, xformers, gsplat, kiui.op; print('L4GM ready:', torch.__version__, gsplat.__version__, torch.cuda.is_available())"
# ImageDream's weights (about 5 GB) download on the first hazard, without a login.
