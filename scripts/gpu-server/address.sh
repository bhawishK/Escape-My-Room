#!/usr/bin/env bash
# Prints the address the phone and the headset open: the tunnel's current trycloudflare.com link,
# which changes each time the tunnel service starts (#139).
set -euo pipefail

address=$(journalctl -u escape-room-tunnel --no-pager -o cat 2>/dev/null \
  | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n1 || true)
if [[ -z "$address" ]]; then
  echo "No tunnel address yet. Check the tunnel: systemctl status escape-room-tunnel" >&2
  exit 1
fi
echo "$address"
