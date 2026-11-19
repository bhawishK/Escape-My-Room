#!/usr/bin/env bash
# Retrain the live room's reconstruction four ways and build each into a room (#209), on the GPU
# desktop. Frames, COLMAP and levelling are reused from the job, so each variant is in the same
# frame as room 9 and takes its placement unchanged.
#
#   A: as now              B: needle penalty
#   C: depth guidance      D: both
#   E: D, plus four Difix3D+ repair rounds (#215; Difix installed in ~/difix)
#
# Run from a worktree of the branch, so the server's own checkout is never touched:
#   git -C ~/escape-my-room worktree add ~/escape-my-room-209 issue-209-depth-training
#   bash ~/escape-my-room-209/experiments/room-refine/retrain_variants.sh [A B C D]
set -euo pipefail

REPO=${REPO:-$HOME/escape-my-room}
CODE=$(cd "$(dirname "$0")/../.." && pwd)
JOB=${JOB:-$REPO/data/jobs/job_9396ad95bd16b2d4471ae3d86da37d38/reconstruction}
VIDEO=${VIDEO:-$REPO/data/captures/cap_6696f94608023d88a08a3b6f68da7bbe/video.mov}
PLACED=${PLACED:-$REPO/data/rooms/refined-206-v9}
OUT=${OUT:-$REPO/data/refine-209}
PYTHON=${PYTHON:-$REPO/.venv/bin/python}
# gsplat compiles its CUDA code on first use with the venv's ninja, as the server's runs do.
export PATH="$(dirname "$PYTHON"):$PATH"

declare -A FLAGS=(
  [A]=""
  [B]="--anisotropy-weight 0.1"
  [C]="--depth-weight 0.1"
  [D]="--depth-weight 0.1 --anisotropy-weight 0.1"
  [E]="--depth-weight 0.1 --anisotropy-weight 0.1 --fix-rounds 4"
)
# E starts from D's work, whose depth stage is done; the others from the job's.
declare -A FROM=([E]="$OUT/D/reconstruction/work")
VARIANTS=("${@:-A B C D}")
read -r -a VARIANTS <<< "${VARIANTS[*]}"

nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader \
  || { echo "The GPU is not usable (reboot after a driver update?)." >&2; exit 1; }

cd "$CODE"
for variant in "${VARIANTS[@]}"; do
  recon="$OUT/$variant/reconstruction"
  echo "== $variant: ${FLAGS[$variant]:-as now}"
  if [ ! -d "$recon/work" ]; then
    mkdir -p "$recon"
    # Frames, COLMAP and the finished stages' markers, so only depth and training rerun.
    cp -r "${FROM[$variant]:-$JOB/work}" "$recon/work"
  fi
  # shellcheck disable=SC2086
  "$PYTHON" -m backend.reconstruction "$VIDEO" "$recon" ${FLAGS[$variant]} \
    > "$OUT/$variant/progress.jsonl" 2> "$OUT/$variant/errors.log"
  "$PYTHON" experiments/room-refine/make_room.py "$recon" "$PLACED" "$OUT/$variant/room"
  "$PYTHON" - "$recon/report.json" <<'EOF'
import json, sys
t = json.load(open(sys.argv[1]))["training"]
print(f"  held-out PSNR {t['psnr_db']} dB, {t['splats']:,} splats, {t.get('needles')} needles, "
      f"{t.get('depth_guided_frames')} depth-guided frames, peak GPU {t['peak_gpu_memory_gb']} GB")
for repair in t.get("fix_rounds") or []:
    print(f"  repair round {repair['round']} after step {repair['after_step']}: "
          f"{repair['views']} views, {repair['covered']:.0%} covered by splats")
EOF
done
