# Spike #92: a room splat from a video

Throwaway code to answer issue #92: can COLMAP plus a trained Gaussian splat, made from one phone
video, give a room view that matches the real room in size, looks like it, and runs smoothly on
the iPhone and the Quest? Nothing here is used by the app.

| File | What it is |
| --- | --- |
| `room_splat.ipynb` | The Colab notebook: video → frames → COLMAP → level and scale → train → download |
| `room_splat.py` | The notebook's source; edit this, then run `make_notebook.py` |
| `check_pipeline.py` | Runs the notebook's CPU steps on a synthetic room with known size and checks the result |
| `../../frontend/splat.html` | The viewer: loads the splat with Spark, measures, enters VR |

## 1. Film the room

- **Settings:** in **Settings → Camera → Record Video**, choose **1080p at 30 fps** and turn **HDR Video** off, since HDR frames come out washed out. Lock the exposure if you can: press and hold on the screen until **AE/AF Lock** appears.
- **Walk round the edge, facing across the room:** walk slowly along the walls, about one step per second, with the phone at chest height, upright, pointing slightly down and *across* the room towards the middle and the far side. Sweep gently left and right as you go. Then the furniture shifts against the far walls with every step, which is what COLMAP measures depth from.
- **Don't stand in the middle and turn:** the synthetic tests showed that a camera turning on the spot, or walking a small loop facing outward, gives a bent, wrongly-sized room even though COLMAP reports no errors.
- **Get the floor in shot:** every few steps tilt the phone down so the floor along the walls is visible. The notebook takes the lowest large flat surface as the floor; in the first real run the floor was barely filmed and the mattress was taken instead.
- **Film the whole room:** what isn't filmed is simply missing. The first real run filmed one side, and the other side is black.
- **Close the loop:** finish where you started, and add a short second pass of any corner you missed.
- **Send the original file:** WhatsApp re-encodes video to about 576 px wide, which leaves COLMAP far fewer points. Use Google Drive, AirDrop or a cable instead.
- **Keep it still:** steady, smooth movements; no people or pets moving; lights on, curtains as they are.
- **Measure two things** with a tape: one long, like the desk's width, and one other for checking. Write them down.

1–2 minutes is plenty. Plain white walls and shiny surfaces reconstruct poorly; that is one of the things this spike finds out.

## 2. Make the splat in Colab

1. Open [colab.research.google.com](https://colab.research.google.com), **File → Upload notebook**, choose `room_splat.ipynb`.
2. **Runtime → Change runtime type → T4 GPU**.
3. **Runtime → Run all**. The upload cell asks for the video.
4. Wait, keeping the tab open. The download of `room-splat.zip` starts at the end.

**No video yet?** Set `SAMPLE_SCENE = "room"` in the settings cell, then Run all. Nothing is uploaded: the notebook reads one published indoor scene's photos straight out of its zip. The scenes are `room`, `kitchen` and `counter` from [Mip-NeRF 360](https://jonbarron.info/mipnerf360/) (80–100 MB each), and `playroom` from Deep Blending, as packaged with the 3D Gaussian Splatting paper (136 MB). Their authors state no licence, so use them for testing only and don't redistribute them.

Up to `EXHAUSTIVE_UP_TO = 150` frames, every frame is matched with every other. Above that, only each frame's 15 neighbours in time are matched.

The settings cell has two switches for speed:
- `QUICK = True` (the default): at most 120 frames at 1280 px and 10,000 training steps, about 20–30 minutes in total. `False` gives 240 frames at 1600 px and 20,000 steps, a little sharper, about 45–75 minutes.
- `MAPPER = "incremental"` (the default) uses COLMAP's classic mapper; `"global"` uses GLOMAP, which places all cameras at once. On the 90-frame synthetic room both were equally accurate and incremental was faster (84 s against 134 s on 12 CPU threads); global mapping usually pays off only with many hundreds of frames. If the chosen mapper places fewer than 80% of the frames, the notebook tries the other one too and keeps whichever placed more. `report.json` records which one was used and how long each took.

The zip holds `room.ply` (the splat), `report.json` (frames placed, time, quality, splat count) and `previews/` (held-out frames next to the splat's render of the same view).

## 3. Look at it

1. Unzip and copy `room.ply` and `report.json` to `frontend/public/spike/` (git ignores that folder).
2. Build and serve as usual: `npm --prefix frontend run build`, then start Python ([startup](../../docs/diagnostic-startup.md)).
3. Open `/splat.html` on the desktop, the iPhone and the Quest, through the same HTTPS route as the app.
   - **Desktop and phone:** drag to look, two fingers or arrow keys to move.
   - **Quest:** **Enter VR**. You stand on the reconstructed floor at the origin; walk or use the thumbsticks.
   - **Viewpoints:** the page opens where the video was filmed; **Next viewpoint** steps through the filmed places. Elsewhere the splat has gaps and smears.
   - **Set floor:** if the floor grid isn't on the real floor, tap **Set floor** and then a solid spot on the floor.
   - **Measure:** tap both ends of the length you measured, enter the real length, **Set scale**. Then measure the second length to check.
   - Positions can also be given in the address: `?at=x,z&yaw=degrees&pitch=degrees`.
   - **Floor grid:** a 0.5 m grid at the floor, to see whether the floor is level and at the right height.

## 4. Record on #92

Copy into a comment on #92:
- `report.json`'s numbers;
- the previews;
- the two measurements, before and after **Set scale**;
- the frame rate on each device;
- screenshots.

## First real run, 2026-10-24

A 1-minute iPhone video of a room with a loft bed, sent through WhatsApp, run with `QUICK = True`:

| | |
| --- | --- |
| Frames | 120, all placed by the incremental mapper; frames were 576 px wide after WhatsApp |
| COLMAP | 101 s (mapping 23 s); 2,202 sparse points; reprojection error 0.73 px |
| Training | 19.5 min for 10,000 steps; 98,585 splats, 10.3 MB |
| Quality on 12 held-out frames | PSNR 35.7 dB; previews nearly match the real frames |
| Levelling | Camera heights 1.33–1.46 m, so levelled, but the floor found was probably the mattress top |

Findings:
- **The look is very good from where the video was filmed.** Shelves, ladder, desk, wall, socket and mattress are all recognisable, but the unfilmed side of the room is empty.
- **Few points meant few splats.** MCMC grows the splat count by 5% per refinement, so starting from 2,202 points it reached only 98,585. The notebook now starts from at least 50,000 jittered copies of the points.
- **The floor was probably wrong**, and so was the scale that depends on it. The viewer now has **Set floor**, and the filming guide asks for the floor to be in shot.
- `report.json` now records each camera's direction, so the viewer can face the way the video did.

## Published room, 2026-10-25

The notebook's CPU steps on Mip-NeRF 360 `room` (120 of its 312 photos, 1280 px), compared with the camera positions the dataset's authors published:

| Matching | Frames placed | Points | Camera error vs published (median / max, % of the camera circle) | COLMAP time |
| --- | --- | --- | --- | --- |
| Neighbours only | 60 / 120 | 4,752 | 0.18% / 0.92% | 46 s |
| Every pair | **120 / 120** | **14,396** | **0.08% / 0.26%** | 79 s |

Matching only neighbours suits a single continuous video, but misses a corner seen again later in the walk. That is probably also why the second real video placed only 77 of its 120 frames. Hence `EXHAUSTIVE_UP_TO`.

## Checking the CPU steps without a GPU

Results on 2026-10-24 (90 frames from a 30 s synthetic walk round the room's edge, 12 CPU threads):

| | Incremental | Global |
| --- | --- | --- |
| Frames placed | 90 / 90 | 90 / 90 |
| Mapping time | 84 s | 134 s |
| Whole COLMAP step | 142 s | 184 s |
| Focal length (true 685.5 px) | 685.5 | 685.5 |
| Walk radius (true 1.56 m) | 1.562 m | 1.562 m |
| Floor height after levelling | 2 mm | 2 mm |
| Camera tilt (true 12°) | 12.0° | 12.0° |

Two earlier runs failed, and both lessons are built in. A walk in a small loop facing outward gave a bent room with a 13% wrong focal length, even though COLMAP reported a low error; hence the filming guide. The `OPENCV` camera model settled on unequal focal lengths and bent the room; hence `SIMPLE_RADIAL`.

`check_pipeline.py` renders a synthetic 4 m x 5 m x 2.6 m room with a table and a cabinet, filmed from 1.4 m along a loop. It runs the notebook's frame, COLMAP and levelling steps on it, and checks the cameras against the truth. It runs in a Linux container, because Windows Smart App Control blocks pycolmap's library on the dev laptop:

```bash
docker run --rm -d --name splatlab python:3.12-slim sleep infinity
docker exec splatlab sh -c "apt-get -qq update && apt-get -qq install -y ffmpeg && pip -q install pycolmap==4.2.1 numpy opencv-python-headless"
docker cp spikes/colmap-splat splatlab:/spike
docker exec splatlab python /spike/check_pipeline.py /tmp/out
docker cp splatlab:/tmp/out/room.ply frontend/public/spike/room.ply   # its sparse points, viewable as splats
```

The training step needs an Nvidia GPU, so it is only checked in Colab.
