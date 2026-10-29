# The GPU desktop as the server

The GPU desktop runs the whole project for the contest (issue #139, part of #134):
- the website (Python);
- reconstruction of uploaded room videos ([reconstruction pipeline](reconstruction.md), [room video reconstruction](room-preparation.md#room-video-reconstruction-issue-137));
- the Cloudflare tunnel that gives the phone and the headset an HTTPS address.

Development stays on the laptop. The desktop pulls `main` from GitHub.

| | |
| --- | --- |
| Machine | i7-13700K, 64 GB, RTX 3070 Ti (8 GB), NVIDIA driver 580 |
| System | Ubuntu 22.04.5 LTS, on the 500 GB SSD |
| Repository | `~/escape-my-room` |
| Data | `~/escape-my-room/data/` (rooms, captures, jobs, movement logs) |
| Address | a Cloudflare quick tunnel: a `trycloudflare.com` link that changes when the tunnel restarts |

Qwen stays on OpenRouter: Qwen3-VL-8B needs about 17 GB, which the 8 GB card can't spare next to splat training.

## Set it up

### 1. Get the wizard onto the desktop

The repository is private, so the desktop can't clone it until stage 6 of the wizard has added its key. Get the one file there first:
1. On the desktop, open <https://github.com/bhawishK/Escape-My-Room/blob/main/scripts/gpu-server/setup-wizard.sh> in a browser signed in to GitHub.
2. Click **Download raw file** (the download arrow above the file), so it lands in `~/Downloads`.

Or copy `scripts/gpu-server/setup-wizard.sh` over on a USB stick.

### 2. Run it

In a terminal on the desktop:

```bash
bash ~/Downloads/setup-wizard.sh
```

It shows one stage at a time and asks before anything that needs `sudo`. Stop it with Ctrl-C at any point; running it again skips what is already done.

| Stage | What it does |
| --- | --- |
| 1. Check this machine | Ubuntu 22.04, `nvidia-smi` sees the GPU, free disk space |
| 2. System packages | `apt install git ffmpeg build-essential curl ca-certificates`. ffmpeg brings `ffprobe`, which checks uploaded videos (#136). |
| 3. CUDA toolkit 12.8 | NVIDIA's apt repository, then `cuda-toolkit-12-8` in `/usr/local/cuda-12.8` (about 8 GB). The driver is left alone. gsplat compiles its CUDA code on first use, which needs the toolkit's `nvcc`. |
| 4. Node.js 24 | The NodeSource repository and `nodejs`, because Vite needs a newer Node than Ubuntu 22.04 has |
| 5. cloudflared | Cloudflare's apt repository and `cloudflared` |
| 6. GitHub deploy key | Makes `~/.ssh/escape_room_deploy` and an SSH host alias `github-escape-room`, then opens the repository's **Deploy keys** page for you to add it, read-only |
| 7. Clone | `git clone git@github-escape-room:bhawishK/Escape-My-Room.git ~/escape-my-room` |
| 8. Python and the app | `uv`, then Python 3.12 and `.venv`, torch for CUDA 12.8 (`--index-url https://download.pytorch.org/whl/cu128`), then `pip install -e ".[gpu,dev]"` |
| 9. Server settings | `.env` with `ESCAPE_ROOM_VIDEO_WORKER=reconstruction`, and, if you give one, `OPENROUTER_API_KEY` with `ESCAPE_ROOM_PREPARATION_WORKER=openrouter`. The key is typed hidden and stays in `.env`. |
| 10. Build the website | `npm ci && npm run build` in `frontend/` |
| 11. GPU check | `python -m backend.gpu_check` (below). The first run compiles gsplat for 5–10 minutes with no output. |
| 12. Services | Installs `escape-room` and `escape-room-tunnel` as systemd services that start at boot, starts them, and shows the phone address |

Set `REPO=/some/other/path` before running it to put the repository elsewhere.

### 3. Check it

- **The address:** `~/escape-my-room/scripts/gpu-server/address.sh` prints the link to open on the iPhone and the Quest.
- **After a reboot:** don't log in. From another device, open the address: the website should load. The address is new after each reboot, so read it with `address.sh` (over SSH, or once logged in).
- **The GPU:** `~/escape-my-room/.venv/bin/python -m backend.gpu_check` should end with "Ready to reconstruct rooms."

## Every day

| To | Run |
| --- | --- |
| Find the address | `scripts/gpu-server/address.sh` |
| Deploy the latest `main` | `scripts/gpu-server/update.sh` (pulls, reinstalls, rebuilds the website and restarts the server; the address stays) |
| Watch the server | `journalctl -u escape-room -f` |
| Restart the server | `sudo systemctl restart escape-room` (the tunnel keeps its address) |
| Get a new address | `sudo systemctl restart escape-room-tunnel` |
| Stop everything | `sudo systemctl stop escape-room-tunnel escape-room` |

A reconstruction's own log is in its job folder: `data/jobs/<job id>/reconstruction/pipeline.log`.

## The services

Both units are in `scripts/gpu-server/`, with `@USER@` and `@REPO@` filled in by the wizard:
- **`escape-room.service`:** `uvicorn backend.app:app` on `127.0.0.1:8000`, as your user, in the repository, restarting on failure. Python reads `.env` itself. The CUDA toolkit is on its `PATH`, with `CUDA_HOME` set, because reconstruction jobs run as its child processes and gsplat may compile there.
- **`escape-room-tunnel.service`:** `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000`, started after the server.

There is no separate worker service: reconstructions run as child processes of the server, one at a time, and stop with it (#137).

## The GPU check

`python -m backend.gpu_check` prints one line per check and exits 1 if any fails:

| Check | What it shows |
| --- | --- |
| NVIDIA driver | `nvidia-smi`'s name, memory and driver version |
| CUDA in torch | The GPU torch sees, its free memory, and torch's CUDA version (12.8) |
| ffprobe | Its version |
| Pipeline libraries | pycolmap and transformers versions |
| gsplat training | 20,000 random splats trained for 30 s: steps, loss and peak GPU memory |

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `nvidia-smi` not found | Install the NVIDIA driver: **Software & Updates → Additional Drivers**, choose a 580 proprietary driver, reboot |
| "torch sees no CUDA GPU" | Install torch again for CUDA 12.8: `~/.local/bin/uv pip install --python .venv/bin/python --reinstall torch --index-url https://download.pytorch.org/whl/cu128` |
| gsplat fails to compile ("nvcc not found", "CUDA_HOME") | Check `/usr/local/cuda-12.8/bin/nvcc --version`, then run the check with `export PATH=/usr/local/cuda-12.8/bin:$PATH CUDA_HOME=/usr/local/cuda-12.8` |
| A room video is refused with 503 "ffprobe is not installed" | `sudo apt install ffmpeg`, then restart the server. The upload is kept, so press finish again. |
| A reconstruction fails with `configuration` "no NVIDIA GPU" | The server didn't find `nvidia-smi` on its `PATH`; check `/usr/bin/nvidia-smi` exists |
| A reconstruction fails with `resource` (out of GPU memory) | Close other programs using the GPU (`nvidia-smi` lists them), or lower the budget with `python -m backend.reconstruction … --memory-budget-gb 4.5` |
| No tunnel address | `systemctl status escape-room-tunnel`; Cloudflare's quick tunnels sometimes refuse for a minute; restart it |
| The deploy key is refused | The key must be added under the repository's **Settings → Deploy keys**, not your account's SSH keys |

## Not yet checked

The wizard and the GPU check were written on the laptop, which has no GPU. They passed a syntax check (`bash -n`) and have not been run on the desktop. #139 stays open until they have been, along with the rest of its checklist:
- the real pipeline on the hallway video, with timings for each stage and the peak GPU memory, recorded in [the reconstruction pipeline](reconstruction.md) (#135);
- a 300 MB iPhone video uploaded through the tunnel (#136);
- a real reconstruction made live (#138).

Fix anything in this guide that turns out wrong when you run it, so the next run follows the corrected steps.
