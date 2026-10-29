# Room video captures

The **Room video** section of `/photos.html` films the room, or picks a saved video, and uploads it as a video capture (issue #136, part of #134). **Reconstruct room** then turns it into a splat room on the GPU desktop; see [room video reconstruction](room-preparation.md#room-video-reconstruction-issue-137) (#137).

## Using it

1. **Record video** opens the phone's back camera; **Choose video** picks a saved one. The server accepts MP4 or MOV, which is what phone cameras record. A picked file whose type the browser leaves blank is named by its extension.
2. The page shows the file's name and size, and its length once the browser has read it. Add room instructions if you like, then tap **Upload video**.
3. A progress bar fills as the chunks go, then the server checks the video. **Saved videos** lists each video with its length and its resolution as filmed, upright. A portrait iPhone video shows as 1080 × 1920.

The page's advice on filming:
- Film at 1080p with HDR off.
- Walk slowly round the edge of the room, facing across it.
- Film each end both ways: walk there, turn round, and walk back. Visual positioning (#133) needs those views back along the room.
- Keep it under 5 minutes.

## Why chunks

The free Cloudflare tunnel refuses requests over 100 MB, and a minute of 4K video is larger. So the page asks the server to start an upload, sends the file in chunks (8 MB by default), and then asks it to finish.

Each chunk is written at its own place in a file reserved at the video's full size. A chunk sent twice after a dropped connection therefore does no harm.

The page tries each chunk up to four times, waiting 0.5, 1 and then 1.5 s between tries. It stops if the server refuses a chunk (a 4xx answer), because trying again wouldn't help. Finishing is retried the same way. If its answer was lost after the server saved the video, the server answers again with that same capture instead of saving a second one.

Each upload has its own lock, so checking one large video never holds up another upload's chunks.

## What is stored

A finished upload becomes `data/captures/<capture id>/video.mp4` (or `.mov`) beside `capture.json`. The capture records:
- `kind: "video"`;
- the original file name, media type, size and SHA-256;
- the instructions;
- the video's length, upright width and height, frame rate and codec, from ffprobe.

Video captures share the captures folder with photo captures. Photo captures now carry `kind: "photos"`; older ones without it are read as photos.

An upload in progress lives in `data/captures/.uploads/<upload id>/`. An upload not finished within a day is removed the next time any upload starts. A refused video (too long, or not a video) leaves nothing behind. A failure on the server's side, such as ffprobe missing, keeps the upload, so finishing can be tried again once it is fixed, without sending the video again.

## Checks and limits

| Setting | Default | Refused when |
| --- | --- | --- |
| `ESCAPE_ROOM_VIDEO_MAX_BYTES` | 2147483648 (2 GB) | the video is larger, before any chunk is sent |
| `ESCAPE_ROOM_VIDEO_MAX_SECONDS` | 300 (5 minutes) | ffprobe finds the video longer |
| `ESCAPE_ROOM_VIDEO_CHUNK_BYTES` | 8388608 (8 MB) | a chunk is larger, or not the size its place needs |

- **Type:** only `video/mp4` and `video/quicktime` are accepted at the start, and ffprobe must then find an MP4 or MOV container with a video stream in it.
- **ffprobe:** the server needs it. Without it, finishing an upload is refused with 503 and the reason, and the upload is kept.
- **Chunk size:** checked against `Content-Length`, and again as the body streams in, so a chunk with no declared length is still cut off at the limit.
- **Tests:** `ESCAPE_ROOM_VIDEO_PROBE=fixture` replaces ffprobe with a stand-in. It reads ffprobe's JSON stored after a real MP4 header, so the parsing code is still the real one.

## API

| Request | Result |
| --- | --- |
| `POST /api/videos` | JSON `{ "filename", "size_bytes", "media_type" }`. Returns 201 with the upload: its `id`, `chunk_bytes` and number of `chunks`. 413 if too large, 415 for another type. |
| `PUT /api/videos/{upload_id}/chunks/{n}` | The chunk's bytes as the body. Returns 204; sending it again is fine. 400 if its size is wrong. |
| `POST /api/videos/{upload_id}/complete` | JSON `{ "instructions" }`, which is optional. Returns 201 with the video capture; asking again returns the same capture. 409 names the first missing chunk, and 503 means ffprobe is missing; both keep the upload. 413 if the video is too long, and 400 if it isn't a video; both remove the upload. |
| `GET /api/captures` | Photo and video captures together, newest first, each with its `kind` |
| `GET /api/captures/{capture_id}` | One capture of either kind, or 404 |

## What was checked

Automated:
- **Python, against a spawned service** (`tests/test_video_uploads.py`):
  - chunks sent out of order make one capture with the right hash and video facts;
  - a missing chunk is named, and the upload then finishes after a repeated chunk and the missing one;
  - a file too large, empty or of another type is refused before any chunk is sent;
  - a file too long is refused and leaves no capture;
  - a chunk of the wrong size is refused, and so is one with no declared length that streams past the limit;
  - finishing again after a lost answer gives the same capture;
  - without ffprobe, finishing is refused with 503 twice and the upload is kept.
- **Python, on sample ffprobe output** (`tests/test_video_probe.py`): a portrait iPhone video's length, upright size and frame rate, a sound file, and a WebM file.
- **Desktop Edge** (`frontend/tests/room-video.spec.ts`):
  - a 200 KB video goes up in four chunks, the second one's connection is dropped once and resent, and the video is listed with its length and resolution after a reload;
  - a video too long, and one of another type, show the server's reason;
  - a MOV with no type is still sent;
  - when the answer to finishing is lost, the page asks again and the video is saved once;
  - the record button opens the back camera.

Showing the length before upload is not tested: the test files are not real videos, so the browser cannot read their length.

Not yet tried: a 300 MB video through the tunnel from the iPhone, and real ffprobe on a real iPhone video.
