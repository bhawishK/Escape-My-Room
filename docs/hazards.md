# Hazards: an object in the room, set on fire from a prompt

The core of the emergency drill (#221). A hazard is made for an object already in the room, or for a new one, and becomes an animated 3D Gaussian splat, played in place. Spike #220 proved the route; this is the built pipeline.

```
object in the room ─► picture cut from the room's splat ─┐                    (#223)
new object (words) ─► Z-Image picture ───────────────────┤
                                                          ▼
                     Wan 2.2 video, fixed template, 2 seeded candidates         (#224)
                                                          ▼
                     quality gate: trim, still camera, best candidate, on white (#225)
                                                          ▼
                     L4GM on the desktop GPU: one splat per frame               (#226)
                                                          ▼
                     4D check and compression (#227) · placement (#228) · playback (#229–#231)
```

## The steps built so far

- **Jobs** (#222): `POST /api/hazards/jobs` with `{"target": {"entity": "layout_bed_2"} | {"description": "a space heater"}, "hazard": "catches fire"}`.
  - A job goes `queued → image_ready → video_ready → ready`, and each step's output is served as it arrives (`/image`, `/video`, then the frames).
  - It keeps the gate's measures in `video_check`.
  - It can be cancelled at any step.
- **Picture of a room object** (#223): only the splats inside the object's box are rendered, on white, from its open side, 20° from above.
  - Objects the video barely showed are refused with the reason. The rule: less than twice the room's average splat density.
- **Video** (#224): Wan 2.2 I2V on a Hugging Face Space, 3 s at 16 fps.
  - The prompt is the hazard followed by fixed wording: still camera, the object unchanged, a plain white background.
  - Two seeds per hazard.
  - Running out of quota says how long to wait.
- **Quality gate** (#225), in `backend/video_gate.py`:
  - trims the frames where Wan straightens the view;
  - rejects a moving camera by the object's footing (12% of the frame at most);
  - keeps the candidate most like the picture;
  - puts the object alone on white, square, 512 px.
- **4D** (#226): L4GM runs as two processes in its own env: ImageDream's views of the first frame, then the frames 8 at a time. It takes the GPU in turn with room reconstruction (`backend/gpu.py`).
  - Live on the desktop: about 40 frames in about 40 s.
- **4D check and SPZ** (#227), in `backend/splat_frames.py`: the frames seen from the front must look like their video (median likeness at least 0.3), then are pruned and written as SPZ, about 176 KB a frame instead of 1.4 MB.
- **Placement** (#228), in `backend/hazard_placement.py`: L4GM puts the picture's camera at +z, so the asset's +z front is turned to the side the object was pictured from.
  - Its long side, measured on the first frame's solid splats, is scaled to the box's.
  - It stands on the box's base, over its centre, and the real object is hidden (`hide`).
  - A new object gets a box of its true size, from its description as furniture does, on the floor at the request's `at`.
  - The asset records `placement`, `seconds`, and `loops` (false: a hazard plays once and holds its end).
  - L4GM makes objects thicker than they are (the live bed about twice as tall), so a placed object can stand taller than the real one.

## Setting up the GPU desktop

1. Install L4GM: `bash scripts/l4gm/install.sh` (into `~/l4gm`).
   - It reuses the SpatialLM env's torch 2.4.1 when there is one, pins the versions that work, downloads the weights, and writes `infer_4d_ply.py`.
   - ImageDream's weights (about 5 GB) download on the first hazard.
2. The server's `.env` needs `ESCAPE_ROOM_FURNITURE_GENERATOR=huggingface` and `HF_TOKEN` (the video step uses the token's GPU allowance).
3. Restart the server (`scripts/gpu-server/update.sh`).

| Setting | Default | What it does |
|---|---|---|
| `ESCAPE_ROOM_L4GM_DIR` | `~/l4gm` | Where L4GM is installed |
| `ESCAPE_ROOM_L4GM_PYTHON` | `<dir>/.venv/bin/python` | L4GM's Python |
| `ESCAPE_ROOM_HAZARD_VIDEO_SPACE` | `zerogpu-aoti/wan2-2-fp8da-aoti-faster` | The Wan 2.2 Space |
| `ESCAPE_ROOM_HAZARD_VIDEO_CANDIDATES` | `2` | Videos per hazard (1–4); each uses quota |
| `ESCAPE_ROOM_FURNITURE_TIMEOUT_SECONDS` | `600` | The longest any one step may take |

## Licences

- Wan 2.2: Apache 2.0.
- L4GM, code and weights: Apache 2.0.
- ImageDream: OpenRAIL.
- Z-Image: Apache 2.0.

Nothing in the pipeline is research-only.

## Session logs (#259)

Each drill run is recorded for studies, as one JSON-lines file in `data/session-logs/`.

- **When:** a run starts when a drill's fire starts. It ends when the fire is stopped, removed or called off, the room changes, or the headset leaves.
- **What:**
  - each person's position and facing, at most 5 times a second each;
  - the exit the commander chose, each route to it, and when the occupant got out ([exit guidance](exit-guidance.md));
  - the giant hand (#185);
  - the fire's events.

  Each line is timed in milliseconds from the run's start. Positions and guidance only: no pictures, sound or video.
- **Reading them:**
  - `GET /api/session-logs` lists the runs, newest first. Each comes with its length, object and hazard, how it ended, how far the occupant walked, how much of the run they were being guided, which exit, and how many seconds after it was chosen they got out (`out_seconds`).
  - `GET /api/session-logs/{id}` downloads one.
- **Turning it off:** set `ESCAPE_ROOM_SESSION_LOGS=0`.
