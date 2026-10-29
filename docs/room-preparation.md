# Room preparation jobs

Issue 26 turns a saved [room-photo capture](room-photos.md) into a **candidate room** through an asynchronous preparation job. The job runs in the background, reports each stage as it happens, and ends **awaiting review** or **failed**. The candidate is only shown for inspection; it never replaces the room the phone and headset are using.

There are two workers. The deterministic **fixture worker** is for development and tests: it copies the [multi-asset fixture room](prepared-room.md#multi-asset-rooms-issue-23), and everything it produces is labelled **“Fixture output, not AI inference”**. The **OpenRouter worker** (#28) asks Qwen through OpenRouter which objects the overview shows, and ends with that object list for review; see [Qwen through OpenRouter](#qwen-through-openrouter-issue-28). Segmentation, geometry and stabilization (#29–#34) are not built yet and wait on a decision about where they run.

## Try it

A normal server has no preparation worker. **Prepare room** then explains that preparation is not configured. Turn the fixture worker on with server settings before starting Python.

Linux or macOS:

```bash
ESCAPE_ROOM_PREPARATION_WORKER=fixture .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 16384
```

Windows Command Prompt:

```bat
set ESCAPE_ROOM_PREPARATION_WORKER=fixture
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 16384
```

Save some room photos, then select **Prepare room** under **Saved photos**. The panel shows the job state, each stage with its time, and, when the job finishes, the candidate's objects with the overview photo. After a reload the panel shows the latest job for the saved capture again.

| Setting | Default | Effect |
| --- | --- | --- |
| `ESCAPE_ROOM_PREPARATION_WORKER` | unset | `fixture` enables the fixture worker, `openrouter` the OpenRouter worker; unset means preparation is not configured |
| `ESCAPE_ROOM_FIXTURE_STAGE_SECONDS` | `1.0` | how long each fixture stage waits |
| `ESCAPE_ROOM_FIXTURE_FAIL_STAGE` | unset | `scene_understanding`, `geometry`, `stabilization` or `export` makes that stage fail, to see a failure |

These are server settings for development and tests. Nothing in the page can make the worker fail.

## How a job runs

1. `POST /api/preparations` checks the capture exists and the overview is one of its photos. A refused request creates no job. A missing worker returns 503 and creates no job.
2. The job is saved as **queued** and added to one in-order queue.
3. A single background thread takes one job at a time. Request handlers and the shared-room lock never wait for it, so phone and headset connections stay responsive. A second job waits in **queued** until the first ends.
4. Stages run in order: **scene understanding → geometry → stabilization → export**. Each records when it started and finished, how long it took, and the files it wrote. While a stage runs, it reports its time so far, and the job reports its total time since submission, including any wait in the queue. Progress is these actual stages and times, not an estimated percentage.
5. After export the worker's candidate is loaded through the [prepared-room checks](prepared-room.md#validation). A valid candidate leaves the job **awaiting review**.
6. If a stage fails, that stage and the job become **failed**. The job keeps a structured error with the stage, a kind and a message, and later stages stay **not started**. The kinds are:
   - `configuration`, `resource`, `provider`, `inference` and `validation`, for real workers. An invalid candidate room is `validation`.
   - `fixture`: a failure the fixture worker was configured to produce, so it is never mistaken for an inference failure.
   - `worker`: an unexpected crash inside a worker. It is recorded and does not stop the worker thread.
   - `interrupted`: a service restart cut the job off.

Restarting the service does not resume photo jobs. Photo jobs that were queued or running are marked **failed** with kind `interrupted` and the message “The service restarted before this job finished. Submit it again.” Reconstructions of room videos are resumed instead; see [below](#room-video-reconstruction-issue-137). Cancellation is a later issue; making a reconstructed room live is described [below](#making-a-room-live-issue-138).

## What is stored

```text
data/jobs/job_<32 hex>/
  job.json                         the record returned by the API, rewritten atomically
  artifacts/<stage>.json           one note per stage (fixture output)
  candidate/manifest.json, *.glb   the candidate room (fixture output)
```

Each job records:

- **Input:** the capture ID, the overview photo ID, the SHA-256 of every photo in the capture, and the SHA-256 of the capture's room instructions.
- **Worker configuration:** worker, version, stage time, configured failure.
- **Input hash:** the SHA-256 of the input and configuration together, so two jobs with the same hash had the same input and settings.
- The state, each stage, any error, and the candidate's objects.
- **Finish time and total elapsed time**, once the job ends.

The fixture candidate keeps the fixture manifest's room version, 1, which is the same number as the stand-in room. Publishing (a later issue) must give a published candidate a new room version instead of reusing this one.

## API

| Request | Result |
| --- | --- |
| `POST /api/preparations` | JSON `{ "capture_id": "cap_…", "overview_image_id": "img_…" }`. Returns 202 with the queued job. |
| `GET /api/preparations` | `{ "jobs": [...] }`, newest first |
| `GET /api/preparations/{job_id}` | one job, or 404 |
| `GET /api/preparations/{job_id}/files/{path}` | a file the job wrote, such as `artifacts/geometry.json` or `candidate/mug.glb` |

Refusals return `{ "detail": "<message>" }`: 404 for an unknown capture or job, 400 for an overview from another capture, and 503 when no worker is configured.

## What was checked

Python tests against spawned services:
- A capture becomes an **awaiting review** job, with all four stages done and timed, artifacts written, the instructions hashed into its input, and the fixture candidate's objects listed. The active room is unchanged afterwards.
- An unknown capture, a foreign overview and an unconfigured server each create no job.
- A configured geometry failure leaves an inspectable failed job of kind `fixture`, with later stages not started, and the active room unchanged.
- Two jobs run strictly one after the other. While the first is running, the second is queued, the running stage and job report live elapsed times, and a phone WebSocket that was connected before submission still gets its pose accepted within half a second.
- A restart marks the running and queued jobs as interrupted.

Desktop Chromium tests:
- **Prepare room** shows **Running** with a live stage time, then **Awaiting review**, with timed stages, a total time, the labelled candidate objects and the overview photo. The result is still there after a reload.
- A second job shows **Queued**, with **Prepare room** disabled, while another job is being prepared.
- A server configured to fail at geometry shows the failed stage and its reason.

These checks use the fixture worker. They do not measure AI inference, GPU behaviour or real preparation times.

## Qwen through OpenRouter (issue #28)

The OpenRouter worker runs one stage, **scene understanding**. It sends the overview photo, scaled so its longer side is at most 1280 pixels, with [REST3D's object-list prompt](../backend/prompts/list_objects.txt) and the room instructions, to `qwen/qwen3-vl-8b-instruct` through [OpenRouter](https://openrouter.ai). The answer must be one object name per line. A job that gets one ends **awaiting review** with an **inventory**: each object's label and a stable ID made from it (`blue mug on desk` → `blue_mug_on_desk`, repeats get `_2`). Nothing is segmented, built or published yet, and the active room never changes.

The OpenRouter key has a **$1 spending limit** for testing; the teacher can raise it if needed. On 24 October 2026 OpenRouter listed this model at $0.25 per million input and $0.75 per million output tokens, so one object list costs well under a cent.

### Turn it on

Put the key in a `.env` file at the repository root. Python reads it when the service starts, and git ignores it. Copy the template and fill in the key:

```bash
cp .env.example .env
```

```bat
copy .env.example .env
```

```ini
OPENROUTER_API_KEY=sk-or-...
ESCAPE_ROOM_PREPARATION_WORKER=openrouter
```

Then start Python as usual. The key stays on the server: it never reaches the page, a job record, a log or a stored file. Any setting on this page can go in `.env` too. A variable already set in the shell wins over the file, so `set ESCAPE_ROOM_PREPARATION_WORKER=fixture` still switches workers for one run. `ESCAPE_ROOM_ENV_FILE` names a different file, or none when empty; the tests set it empty so they never read your key.

| Setting | Default | Effect |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | unset | the key; without it the stage fails with kind `configuration` |
| `ESCAPE_ROOM_OPENROUTER_MODEL` | `qwen/qwen3-vl-8b-instruct` | the model; other models are not assumed to be better or compatible |
| `ESCAPE_ROOM_OPENROUTER_URL` | `https://openrouter.ai/api/v1` | the API address; tests point it at a fake |
| `ESCAPE_ROOM_OPENROUTER_MAX_IMAGE_SIDE` | `1280` | longest side, in pixels, of each image sent |
| `ESCAPE_ROOM_OPENROUTER_MAX_IMAGES` | `7` | most images one request may carry; REST3D's support question uses seven |
| `ESCAPE_ROOM_OPENROUTER_MAX_OUTPUT_TOKENS` | `2048` | longest answer |
| `ESCAPE_ROOM_OPENROUTER_MAX_REPAIRS` | `2` | how many times a badly formatted answer is asked for again |
| `ESCAPE_ROOM_OPENROUTER_TIMEOUT_SECONDS` | `120` | how long one request may take |

The job records these settings, never the key. No other model or provider is used as a fallback.

### What is recorded

Every request is a **model call** on the job: the model and the upstream provider OpenRouter chose, token counts, the cost OpenRouter reported, the time it took, whether the answer was accepted and why not, and the answer itself as `artifacts/scene_understanding/answer-<n>.txt`. The job's `cost_usd` adds up every call, including refused answers and failed jobs, because those cost money too. The photos page shows the objects, then a line such as `qwen/qwen3-vl-8b-instruct via <provider> · 1 request · 1,240 tokens · $0.0004 · 2.1 s · Raw answer`. After a repair it links every answer, refused ones marked, and a request OpenRouter reported no cost for is counted separately instead of being left out of the total silently.

### Answers that do not fit

An answer is refused when it lists no objects, is cut off, repeats an object, or has a line that is not an object name: 100 characters or more, ending in a colon, or ending like a sentence. The worker then asks again, adding the refused answer and REST3D's reminder (“Output ONLY a plain list, one object per line…”). After the repair limit, the stage fails with kind `inference` and the last reason.

The adapter in `backend/openrouter.py` also reads the other three answer formats REST3D and SAM 3 use, for the later segmentation and support stages (#29, #30): a `<tool>` JSON call, an `Accept`/`Reject` `<verdict>`, and a support line `object -> parent | relation | type`. Unlike REST3D, a support line naming an unknown parent is refused instead of quietly becoming the floor.

### Failures

A request that fails is never retried in a loop. The stage fails, the job keeps what it recorded, and the active room is untouched.

| OpenRouter says | Kind | Message |
| --- | --- | --- |
| no key on the server | `configuration` | The server has no OpenRouter key. Set OPENROUTER_API_KEY and restart the service. |
| 401 | `configuration` | OpenRouter refused the server's key. Check OPENROUTER_API_KEY. |
| 402 | `resource` | The OpenRouter key has reached its spending limit. Ask for the limit to be raised, then submit again. |
| 429 | `provider` | OpenRouter is limiting requests right now. Wait a minute, then submit again. |
| 408, 502, 503, 504 | `provider` | The model is unavailable right now (…). Try again later. |
| no connection | `provider` | OpenRouter could not be reached (…). Try again later. |

### Checking the real service

The tests never call OpenRouter. They run the service against a local fake (`tests/fake_openrouter.py`) that replays scripted answers, and cover the inventory, the request's image and text order, cost and answer records, repairs, the repair limit, each failure above, and that the key appears in no response or stored file.

To see what the real model does, run the one-off check with a room photo; it reads the key from `.env` like the service. It sends five requests, the four formats plus an answer asked for in prose to exercise a repair, and costs a few cents at most:

```bash
.venv/bin/python -m backend.openrouter_check path/to/room.jpg
```

It prints and saves a report under `data/openrouter-checks/` with every answer, token count and cost. The support request carries seven images, REST3D's largest. No real run has been recorded yet.

Prompt sources and their licence are in [`backend/prompts/NOTICE.md`](../backend/prompts/NOTICE.md).

## Room video reconstruction (issue #137)

A saved room video ([room video captures](room-video.md)) is reconstructed by the pipeline from #135 ([reconstruction pipeline](reconstruction.md)), on the GPU desktop. Each saved video on `/photos.html` has a **Reconstruct room** button. The page then follows the job's stages: Frames, COLMAP, Levelling, Splat training, Positioning map, Package. Each shows its state and time, and splat training shows its steps as they happen, such as "step 4001 of 20000 · 312,000 splats, loss 0.0410". At the end the job is **awaiting review** with what it made: frames placed, splat count, PSNR, positioning-map keypoints, and whether training ran out of GPU memory and was trained again smaller.

### Turn it on

| Setting | Default | Effect |
| --- | --- | --- |
| `ESCAPE_ROOM_VIDEO_WORKER` | unset | `reconstruction` enables it; unset means a video job is refused with 503 |
| `ESCAPE_ROOM_RECONSTRUCTION_COMMAND` | `["<python>", "-m", "backend.reconstruction"]` | The pipeline's command line before its VIDEO and OUT arguments, as a JSON list. The tests point it at `tests/fake_reconstruction.py`. |
| `ESCAPE_ROOM_RECONSTRUCTION_REQUIRE_GPU` | `1` | `0` skips the GPU check, for the fake pipeline |

A video job is submitted as `POST /api/preparations` with only `{ "capture_id": "cap_…" }`; room videos have no overview photo.

### How it runs

- **A child process:** the worker runs the pipeline with `--watch-stdin`, reads its JSON progress lines into the job's stages (`step`, `total` and `message` while a stage reports progress), and keeps its error output in `reconstruction/pipeline.log` in the job folder. A CUDA crash or running out of memory can't take the web server down. If reading its progress ever fails, the worker stops the child before failing the job, so two GPU jobs never train at once.
- **Its own queue:** reconstructions run one at a time, separately from photo jobs, so a photo job never waits behind an hour of training.
- **The GPU check:** without `nvidia-smi` on the search path, the job fails at once with kind `configuration`: "This server has no NVIDIA GPU (nvidia-smi was not found); room videos are reconstructed on the GPU desktop."
- **What is kept:** the pipeline writes into the job folder's `reconstruction/` (`room.ply`, `report.json`, `previews/`, `vps/`, `work/`). Each finished stage has the pipeline's own report for it as an artifact, so a GPU memory retry can be read from the splat stage's report.

### Failures

| What happened | Job error kind | Message |
| --- | --- | --- |
| No GPU | `configuration` | as above |
| Training ran out of GPU memory twice (exit code 3) | `resource` | The pipeline's own message, naming both attempts |
| The pipeline described a failure, such as COLMAP placing no frames | `reconstruction` | The pipeline's message |
| The process died without a word, as if killed | `worker` | "The reconstruction process stopped unexpectedly (exit code N)." |

### Restarts

The pipeline reads its standard input and stops when it closes, so it never outlives the service that started it, on Linux or Windows. When the service starts again, an unfinished reconstruction goes back to its queue, and the pipeline skips every stage it finished. Those stages keep the time they took when they ran, from the pipeline's markers. A run stopped during training retrains the splat, but keeps the frames, COLMAP and levelling. A service started without the reconstruction worker marks such a job `interrupted` instead.

### What was checked

Python tests against a spawned service, with the fake pipeline (`tests/test_reconstruction_jobs.py`). The fake uses the real stage runner, so its progress lines, markers and skipping are the real ones. The tests cover:
- a video becomes a reconstruction to review;
- training steps show while the job runs;
- a killed pipeline gives `worker`;
- running out of GPU memory gives `resource`;
- no GPU gives `configuration`;
- a restart during training resumes, runs frames, COLMAP and levelling only once, and keeps their times;
- training that runs out of GPU memory once is trained again, the job says so, and the splat stage's report lists both attempts.

Desktop Edge (`frontend/tests/room-video.spec.ts`) reconstructs a saved video and watches the stages, the live training steps and the summary.

Not yet run with the real pipeline on the GPU desktop (#139).

## Making a room live (issue #138)

A reconstruction awaiting review shows a **Review** section in its panel:
- the held-out frames beside the splat's view of the same place;
- a link that opens the splat in the desktop viewer (`/splat.html?src=…`);
- **Make live**.

**Live room** below it says which room both devices share: its room version, whether it is the server's configured room or a reconstructed one, the floor size, the scale source and whether the positioning map is in place.

### Make live

`POST /api/preparations/{job_id}/activate`:
1. Builds the reconstruction with `assets/splat-room/build_room.py` into a new folder, `data/rooms/<job id>-v<room version>/`, so the room being served is never touched. It writes the manifest, the 100,000-splat phone splat, the map from above (when the renderer is available), and the positioning map from `vps/`.
2. Checks the built room as the server checks any room. A room that can't be built or doesn't pass is refused with 422, its folder is removed, and the live room is unchanged.
3. Makes it live for everyone without restarting Python. The room version is one higher than any before, so both devices see it change and reload. The selection, the devices' calibrations, the phone's position, both people's presence and their loaded versions are cleared, because they belonged to the old room. It works even when the configured room failed to load.

Only a reconstruction awaiting review can be made live (409 otherwise). The room is never changed while someone carries the box: that is refused with 409, "Someone is carrying the box. Let go of it before changing the room." One change of the live room runs at a time.

### Restore

`POST /api/rooms/restore` makes the room before the live one live again, under a new, higher room version; no room's own files are changed. Pressing it again goes forward to the room it replaced. With no earlier room it is refused with 409.

### What survives a restart

`data/live-room.json` lists every room made live, oldest first; the last is live, and the server starts with it. If that room's folder has gone, the server starts with the configured room instead. The first entry is the room `ESCAPE_ROOM_PREPARED_DIR` named, so Restore can always go back to it. `GET /api/rooms/live` describes the live room.

### What was checked

Python tests against a spawned service (`tests/test_live_room.py`). The fake pipeline writes `build_room.py`'s small test splat, and the real `build_room.py` builds it. They cover:
- Make live: the new room and its splat are served (`no-cache`), and a connected headset is sent the new version;
- Restore: the configured room comes back under a higher version;
- a candidate that can't be built is refused, leaves no folder, and keeps the live room;
- the live room outlasts a restart, and a restart falls back to the configured room when the live room's folder has gone;
- a reconstruction can be made live when the configured room is broken;
- the room isn't changed while the box is carried.

Desktop Edge (`frontend/tests/live-room.spec.ts`, on its own test server because it changes the room) makes a reconstruction live and restores the old room. A connected phone's and headset's room status both follow each change.

Not yet tried: a real reconstruction from the GPU desktop, and how long `build_room.py` takes on a 400,000-splat room (its phone splat is chosen in plain Python).
