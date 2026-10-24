# Room photo captures

Issue 24 lets the mobile master save the photographs and instructions that later room preparation (#22) will use. Nothing here runs AI. A saved capture is reviewed, kept, and shown again after a reload or a service restart.

## Using it

**Room photos** has its own page, `/photos.html`, reached from the navigation bar at the top of the shared room page.

- **Take photo** opens the device camera. On iPhone and Android it uses the browser's native camera picker (`<input capture="environment">`); each tap adds one photo. On desktop it opens a file chooser.
- **Choose photos** adds existing JPEG or PNG photos, several at once.
- Photos from both buttons collect in one list. Mark one as the **overview**: the photo that shows the most of the room. The first photo is the overview until another is chosen.
- **Room instructions** describe the room and the objects that matter. They are optional.
- **Save photos** saves everything as one capture. The panel then shows the saved photos, instructions and overview. The overview can still be changed there; the change is saved immediately.

The panel always shows the most recent capture. No capture or photo ID is shown or typed, and none is used to join the shared room.

A saved capture can be turned into a candidate room with **Prepare room**; see [room preparation jobs](room-preparation.md).

## What is stored

Captures live in `data/captures/` (gitignored), or in `$ESCAPE_ROOM_DATA_DIR/captures/` when that variable is set.

```text
data/captures/cap_<32 hex>/
  capture.json             the record returned by the API
  originals/img_<id>.jpg   the uploaded file, byte for byte
  processed/img_<id>.png   an upright copy, only when the photo had an EXIF orientation
```

Each photo records its original filename, media type, size in bytes (`size_bytes`), SHA-256 of the original file, stored width and height, and EXIF orientation (1 when absent). Its `processed` entry says which file later processing should read:

- `"source": "original"`: the original was already upright, so it is used as is.
- `"source": "exif_orientation_applied"`: the EXIF orientation was applied and an upright PNG without orientation metadata was written. Its `width` and `height` are the upright size.

Phones often store photos sideways with an orientation tag. Browsers apply the tag when displaying, but processing code such as SAM reads raw pixels, so it must read the processed file. The original is never modified.

A capture is assembled in a hidden `.incoming-…` folder and renamed into place only after every photo has been read successfully. A rejected upload leaves no capture behind.

## Checks and limits

Each photo is decoded completely, so the file extension and browser-reported type are not trusted. Only JPEG and PNG are accepted. A photo that cannot be decoded is refused by name.

Many phones add extra pictures, such as HDR gain maps or previews, to a JPEG. Pillow reports those files as `MPO`; they are accepted and stored as JPEG. A sideways photo in CMYK colour is converted to RGB for its upright copy; the original keeps its CMYK data. If the upright copy still cannot be written, the refusal names the photo and its colour mode and asks for an ordinary JPEG or PNG instead of failing with a server error.

Resource limits apply to every upload. The defaults are generous placeholders, not measured performance limits; change them with environment variables before starting Python:

| Variable | Default | Refused when |
| --- | --- | --- |
| `ESCAPE_ROOM_CAPTURE_MAX_IMAGES` | 40 | more photos are saved at once |
| `ESCAPE_ROOM_CAPTURE_MAX_IMAGE_BYTES` | 26214400 (25 MiB) | a photo file is larger |
| `ESCAPE_ROOM_CAPTURE_MAX_IMAGE_PIXELS` | 50000000 | a photo has more pixels |
| `ESCAPE_ROOM_CAPTURE_MAX_INSTRUCTIONS` | 4000 | the instructions have more characters |

Pillow also refuses photos above roughly 179 megapixels whatever the configured limit. Every refusal returns a message naming the photo and the reason; the browser shows it and keeps the unsaved photos so the user can remove the problem one.

## API

| Request | Result |
| --- | --- |
| `POST /api/captures` | multipart form: one or more `images` files, `overview` (index of the overview in the uploaded order), optional `instructions`. Returns 201 with the capture. |
| `GET /api/captures` | `{ "captures": [...] }`, newest first |
| `GET /api/captures/{capture_id}` | one capture, or 404 |
| `PUT /api/captures/{capture_id}/overview` | JSON `{ "image_id": "img_…" }`. A photo from another capture returns 400. |
| `GET /api/captures/{capture_id}/images/{image_id}/original` | the uploaded file |
| `GET /api/captures/{capture_id}/images/{image_id}/processed` | the file processing should read |

Refusals are 400 for unreadable photos and overview choices, and 413 for limits, with `{ "detail": "<message>" }`. Each image in a response also carries `original_url` and `processed_url`.

This is a trusted prototype service: anyone who can open the URL can save captures. There is no account or ownership model.

## What was checked

Desktop Chromium tests save a library photo plus a camera-picker photo, choose and later change the overview, reload and see the same capture. They also refuse an unreadable file and each configured limit, then confirm after a reload that the previous capture is still the latest. A photo stored sideways with EXIF orientation 6, in RGB and in CMYK, is saved as an upright 20 × 40 file with no orientation metadata, and a multi-picture (MPO) JPEG is accepted. Python tests against a spawned service refuse an overview outside the uploaded photos or from another capture, and return the same capture, hashes and original bytes after the service process restarts.

The iPhone camera picker and real phone photos have not been tried yet; [the Issue #25 record](iphone-capture-check.md) lists the real iPhone Chrome checks. The MPO and CMYK fixtures are generated to match those formats; they are not photos from a real phone.
