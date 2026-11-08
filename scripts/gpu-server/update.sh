#!/usr/bin/env bash
# Deploys the latest main on the GPU desktop (#139): pull, reinstall, rebuild the frontend, install
# the physics worker, and restart the server. Run it from anywhere; it works in the repository it lives in.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo"
echo "▸ Pulling main"
git pull --ff-only
echo "▸ Installing the app"
# Package servers can be slow from the desktop; wait up to 5 minutes per request.
UV_HTTP_TIMEOUT=300 UV_CONCURRENT_DOWNLOADS=4 "$HOME/.local/bin/uv" pip install --python .venv/bin/python -e ".[gpu,dev]"
echo "▸ Building the frontend"
(cd frontend && npm ci && npm run build)
echo "▸ Installing the physics worker"
(cd physics && npm ci)
echo "▸ Restarting the server"
sudo systemctl restart escape-room
sleep 3
curl -fsS http://127.0.0.1:8000/api/health && echo
echo "Done. The tunnel address is unchanged: $("$repo/scripts/gpu-server/address.sh" || echo unknown)"
