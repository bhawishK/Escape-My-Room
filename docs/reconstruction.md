# Reconstruction pipeline

Turns a video of a room into a splat room package, on the GPU desktop (issue #135, part of #134). It replaces the Colab notebook from spike #92. Videos are uploaded on the website ([room video captures](room-video.md), #136), and **Reconstruct room** runs the pipeline on one as a job ([room video reconstruction](room-preparation.md#room-video-reconstruction-issue-137), #137). It also runs from the command line.

```
python -m backend.reconstruction VIDEO OUT [--quick] [--max-frames N] [--exhaustive-up-to N] [--train-steps N] [--memory-budget-gb G]
```

`OUT` ends up holding:

| Path | What it is |
| --- | --- |
| `room.ply` | The trained splat, as a standard 3DGS PLY (the layout the app already reads) |
| `report.json` | Settings, each stage's report and time, and where each frame was filmed from. `build_room.py` reads the cameras. |
| `previews/` | Up to four held-out frames next to the splat's render of the same view |
| `vps/` | The positioning map for #133 (below) |
| `work/` | Frames, the COLMAP database and models, and one marker per finished stage |

Then build the room as before: `python assets/splat-room/build_room.py OUT data/splat-room`.

## Stages

1. **`frames`:** ffmpeg pulls frames at three times `frames_per_second`, and the sharpest of each three is kept, at most `max_frames`, with the long side at most `long_side` pixels.
2. **`colmap`:** feature extraction, matching (every pair up to 250 frames, otherwise 15 neighbours in time) and mapping. Matching every pair joins the walk where it passes the same place again; with neighbours only, 178 frames on the desktop placed only 83 (#139). It was 150 until 29 October 2026. If one mapper places fewer than 80% of the frames, the other is tried too. Then the frames are undistorted.
3. **`level`:** the floor goes to y = 0 with +y up, scaled as if the phone was held 1.4 m up. The similarity is kept in the stage's report and in `report.json` as `levelling_transform`.
4. **`splat`:** gsplat MCMC training, at most 400,000 splats at degree-1 colour, within a GPU memory budget (below).
5. **`vps_map`:** the positioning map (below).
6. **`package`:** writes `report.json`.

Each stage prints progress as one JSON line per event, for example `{"stage": "splat", "state": "step", "step": 4001, "total": 20000, "message": "312,000 splats, loss 0.0410", "seconds": 812.4}`. The states are `started`, `step`, `done`, `skipped` and `failed`. The exit code is 0 when done, 3 when training ran out of GPU memory twice, and 1 for any other failure, with the traceback on stderr. With `--watch-stdin`, the run stops when its standard input closes; the web server starts it that way, so it never outlives the server.

### Continuing a stopped run

A finished stage leaves `work/stages/<stage>.json` with its report, its time and the settings it used. Running the same command again skips every stage whose marker is there with the same settings and whose outputs (such as `work/colmap/undistorted` or `room.ply`) are still there. Once one stage runs again, because it never finished or a setting it uses changed, every stage after it runs too. For example, `--train-steps 5000` on a finished run retrains the splat and rebuilds the map, but keeps the frames and COLMAP.

### GPU memory

The RTX 3070 Ti has 8 GB, and the positioning service (#133) needs 1–2 GB of it. So training is limited to `memory_budget_gb` (5.5 GB by default) with `torch.cuda.set_per_process_memory_fraction`. If it runs out, it tries once more with frames and splat count at three quarters (for example 1600 → 1200 px and 400,000 → 300,000 splats). The splat stage's report lists each attempt under `memory`, with the peak memory used.

### Settings

The defaults suit a 1–2 minute walk round a room: 240 frames at 1600 px and 20,000 training steps. Frames are 1600 px on the long side rather than a full 1080p (1920 px), to keep training within the 3070 Ti's memory budget; `long_side` raises it. `--quick` gives 120 frames at 1280 px and 10,000 steps, as the notebook's `QUICK` did. All settings are in `Settings` in `backend/reconstruction/pipeline.py`.

For jobs started from the website, give the options in the server's `.env` as part of the pipeline's command, then restart the server. For example, to keep up to 400 frames and match all of them in pairs:

```
ESCAPE_ROOM_RECONSTRUCTION_COMMAND=[".venv/bin/python", "-m", "backend.reconstruction", "--max-frames", "400", "--exhaustive-up-to", "400"]
```

A changed frame or matching setting reruns frames or COLMAP and everything after them; a new job starts from the beginning anyway.

## The positioning map

#133 locates the phone by matching its camera frames against this map. `vps/` holds:

| Path | What it is |
| --- | --- |
| `map.json` | The models used, and each map frame's size, `K` and `camera_to_world` (x right, y down, z forward) |
| `frames/<frame>.npz` | `keypoints` (pixel x, y), `descriptors`, `scores` and `points3d`, one row per keypoint |
| `global.npz` | `names` and `descriptors`: one global descriptor per frame, in the order of `map.json` |
| `sparse/` | The COLMAP model, levelled into the same frame |
| `images/` | The undistorted frames the map was made from |

- **Local features:** SuperPoint (`magic-leap-community/superpoint` on Hugging Face), the strongest 2,048 keypoints per frame. It detects on the frame shrunk to 640 px on the long side, keeping its shape. Keypoints are stored in the frame's own pixels, measured from the image's corner like COLMAP's and gsplat's `K`, so a pixel's centre is at +0.5.
- **Global descriptors:** DINOv2 (`facebook/dinov2-small`): its class token and mean patch token, joined and normalised.
- **3D points:** each keypoint's 3D point comes from the trained splat's rendered depth at that pixel, instead of re-triangulating. Keypoints where the splat is less than 90% opaque are left out. Frames rendered from the splat, such as views back along the room that the video missed, can be added the same way.
- **Frame:** the map is already in the splat's own frame, because the levelling has been applied to it. `report.json` keeps `levelling_transform` only for reference; never apply it again. The manifest's placement (rotation, scale, lift) alone carries the map into room metres, exactly as it carries the splat. `build_room.py` doesn't copy `vps/` into the room yet; that's for #133.
- **Licence:** SuperPoint's weights are for non-commercial use only, which suits the contest. ALIKED is a BSD-licensed alternative if that changes.

The phone's frames must be described with the same two models; `map.json` names them. Matching them (LightGlue) belongs to #133, so it isn't installed here.

## Installing on the GPU desktop

The desktop's setup (Linux, CUDA, services) is #139. For the pipeline itself:

1. Install ffmpeg (`sudo apt install ffmpeg`).
2. Install torch for the desktop's CUDA first, from [pytorch.org](https://pytorch.org/get-started/locally/), so pip doesn't pick a CPU build.
3. Install the app with the GPU extra: `pip install -e ".[gpu]"`. gsplat compiles its CUDA code on first use, which takes 5–10 minutes.
4. pycolmap from PyPI is CPU-only: COLMAP's features and matching then run on the CPU, which is slower but gives the same result. A CUDA build of pycolmap makes them use the GPU without code changes (`Device.auto`).

The Hugging Face models download on first use into the Hugging Face cache.

## What is verified

Automated, on the laptop without a GPU:
- **Stage runner** (`tests/test_reconstruction_pipeline.py`): order, progress events, skipping finished stages, rerunning after a setting changes, failures, and stage times kept across a restart.
- **Levelling** (`tests/test_reconstruction_levelling.py`): a tilted, half-size scene comes out with the floor at 0, the cameras at 1.4 m and upright, and every point on the same pixel as before.
- **Memory retry** (`tests/test_reconstruction_memory.py`).
- **Positioning map** (`tests/test_reconstruction_vps_map.py`): keypoints get the floor points they show, worked out by hand, and see-through keypoints are left out.
- **Splat file** (`tests/test_reconstruction_splat_file.py`): a round trip, and the app's own reader reads it.

Not yet run: the stages that need ffmpeg, COLMAP, CUDA or the Hugging Face models, on the GPU desktop. `spikes/colmap-splat/check_pipeline.py` checks frames, COLMAP and levelling on a synthetic room. The hallway video, the timings for each stage and the peak GPU memory on the 3070 Ti are still to be recorded here.
