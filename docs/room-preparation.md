# Room preparation jobs

Issue 26 turns a saved [room-photo capture](room-photos.md) into a **candidate room** through an asynchronous preparation job. The job runs in the background, reports each stage as it happens, and ends **awaiting review** or **failed**. The candidate is only shown for inspection; it never replaces the room the phone and headset are using.

No AI runs yet. The only worker is a deterministic **fixture worker** for development and tests. It copies the [multi-asset fixture room](prepared-room.md#multi-asset-rooms-issue-23), and everything it produces is labelled **“Fixture output, not AI inference”**. Real models (#22) will run behind the same worker boundary later.

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
| `ESCAPE_ROOM_PREPARATION_WORKER` | unset | `fixture` enables the fixture worker; unset means preparation is not configured |
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

Restarting the service does not resume jobs. Jobs that were queued or running are marked **failed** with kind `interrupted` and the message “The service restarted before this job finished. Submit it again.” Cancellation and publishing a candidate as the active room are later issues.

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
