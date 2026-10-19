# Start the connected diagnostic

This is the connected prototype: a phone page, a headset view, the prepared room, and the phone's marker. Since Issue #19 the phone tracks its position with its back camera against a printed tag; see [phone tracking](phone-tracking.md). Use the [device record](device-smoke-check.md) to distinguish desktop checks from hardware evidence.

## Install and run on Windows

Prerequisites: Python 3.12 and Node.js 24 with npm. Run these commands from the repository root in PowerShell. The committed Python lock records the tested Windows development environment; npm uses its committed lockfile.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
npm --prefix frontend ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 16384
```

Open `http://localhost:8000` on the server computer. Building before starting Python is required: Python mounts `frontend/dist` at startup. If the page is missing, build it and restart Python. Stop the server with Ctrl+C.

The application uses one Python worker and one in-memory shared room. A restart disconnects both devices. There are no session IDs, participant credentials, or accounts. Each role has one connection; connecting another tab in that role replaces the previous tab. See the [protocol](diagnostic-protocol.md) for the wire format.

For frontend editing, keep Python running and use `npm --prefix frontend run dev` in a second terminal. Vite proxies `/api` and WebSockets to Python on port 8000. Its loopback development URL is for the server computer; use the built app for device testing.

## Reach the iPhone and remote Quest over HTTPS

Both devices must open the same trusted HTTPS origin. The page automatically uses that origin for the API and `wss://` socket; there is no separate backend URL to configure. A phone's `localhost` refers to the phone, not the server computer. HTTPS is also what lets the phone page use the camera. It does not add a missing WebXR capability; the phone does not need one.

A temporary public tunnel is the easiest certificate route for a remote headset. Install `cloudflared` using its [official downloads](https://developers.cloudflare.com/tunnel/downloads/). With Python listening on port 8000, run in another terminal:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Open the generated HTTPS URL on both devices. Quick Tunnels provide a temporary hostname, require no account, and stop when the tunnel process stops. Anyone with the URL can choose either role in this shared prototype. The user previously confirmed Quest VR entry through this route; the simplified join flow needs a fresh hardware check. See [Cloudflare's Quick Tunnel instructions](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

For a local network alternative, install [mkcert](https://github.com/FiloSottile/mkcert), substitute the server computer's actual LAN IP below, and generate a matching certificate:

```powershell
New-Item -ItemType Directory -Force .certs
mkcert -install
mkcert -cert-file .certs/cert.pem -key-file .certs/key.pem localhost 127.0.0.1 192.168.1.10
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8443 --workers 1 --ws-max-size 16384 --ssl-certfile .certs/cert.pem --ssl-keyfile .certs/key.pem
```

Open `https://192.168.1.10:8443` using the IP you substituted. Allow incoming port 8443 through the server firewall if necessary. Every client must trust the mkcert root CA separately; installing it on Windows does not establish trust on iPhone or Quest. Follow mkcert's mobile trust instructions. Transfer only `rootCA.pem`, never `rootCA-key.pem`; keep private keys local. If a device cannot establish certificate trust, use the public tunnel route. A LAN address alone is not reachable by a remote participant outside that network.

## Use the two views

1. On iPhone, select **Connect phone**. The room opens full screen; **Turn with phone** looks around as the phone turns, and **Start tracking** follows the phone as it walks once the printed tag is on the desk front. **Close** returns to the page, which shows **Waiting for VR device** until the headset joins. See [phone view and tracking](phone-tracking.md#setting-up).
2. Open the same URL on Quest and select **Connect VR headset**. The phone should show **VR device connected**. Both pages should show room version 1 with the floor, desk, cabinet, and movable box. Select **Enter VR** on Quest to look around that room. This separate click provides the browser gesture required to start immersive XR.
3. End VR using **End VR** when the overlay is available, or a controller select action when it is not. Select **Disconnect** to leave the shared room. The phone returns to **Waiting for VR device** after the VR page disconnects. Connected status means the headset page is connected; it does not prove immersive mode or positional tracking.
4. After a dropped connection, use the role button to connect again. There is no session ID to copy or reservation to clear. Opening a second tab in the same role replaces the first.
5. Optional diagnostics are collapsed below the preview. Download the browser report and fill in the hardware record. The report is capability/pose telemetry, not proof of a passed device test. The phone's report adds a `tracking` section with the video and processing sizes, frames per second and detection time.

## Automated checks

From the repository root:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run typecheck:python
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend run build
npm --prefix frontend test
```

Pytest runs real HTTP/WebSocket exchanges against spawned Python services, one for the stand-in room and one for the multi-asset room. Playwright's global setup first writes a synthetic camera video of the desk tag, and its `marker-camera` project launches Chromium with a fake camera playing it; the `default` project runs everything else. Playwright starts the same two rooms on ports 8771 and 8772, plus a stand-in room on port 8773 whose fixture preparation worker is set to fail, and loads the built app. Those servers run the fixture preparation worker; see [room preparation jobs](room-preparation.md). Each test run stores room-photo captures in a fresh temporary folder and uses small capture limits so the fixture photos can exceed them. Regenerate those photos with `.venv/bin/python frontend/tests/fixtures/photos/make_photos.py`. Windows defaults to installed Microsoft Edge; to use installed Chrome, set `$env:PW_BROWSER_CHANNEL = 'chrome'` first. On other platforms, Playwright defaults to bundled Chromium; install it with `npm --prefix frontend exec -- playwright install chromium` and use the platform's `.venv/bin/python` for Python commands. The Python lock was verified on Windows only.

Desktop tests verify shared state, VR connected status, rejected messages, role replacement, mobile layout, unavailable XR, denied permission handling, and the camera tracking pipeline on synthetic frames and a fake camera. They do not verify physical phone tracking, Quest XR rendering, DOM overlays, or held input on either actual device. Regenerate the printable tag with `npm --prefix frontend run markers`.
