# Phone tracking decision

Issue 19 makes physical phone movement reach Python and the headset. The phone measures its own position with its back camera against a printed AprilTag fixed in the room. This page records the chosen mechanism, its frames and units, the setup, and what is and is not verified.

## Why a printed marker

iPhone browsers expose no WebXR. Every iPhone browser, Chrome included, runs on Apple's WebKit engine, and the [recorded iPhone Chrome report](device-reports/2026-10-12-iphone-chrome-connected.json) (iOS 26.6.1, Chrome 155) shows `api_available: false`. The retained `immersive-ar` path could therefore never run on the target phone.

On 19 October 2026 the user approved changing the stack: the phone is an ordinary web page that tracks itself with its camera, and only the Quest uses WebXR. Three options were weighed:

| Option | Real meters | Drift | iPhone browser | Outcome |
| --- | --- | --- | --- | --- |
| Printed marker + OpenCV.js | Yes, from the printed size | None while the tag is in view | Uses the camera API only | Chosen |
| Markerless SLAM in the browser (AlvaAR) | No; one camera has no scale | Accumulates | Untested; the project is unmaintained since 2023 and GPL-3.0 | Not chosen |
| Motion sensors | Rotation only | Position drifts within seconds | Yes | Ruled out by the issue |

The marker also gives the phone its room alignment directly, so the phone needs no "stand at the center and face the desk" step.

## How it works

```
back camera (getUserMedia, 1280 × 720 requested)
  → frame drawn at most 960 px on its long side
  → Web Worker: OpenCV.js AprilTag 36h11 detection, sub-pixel corners, solvePnP
  → camera position in room meters
  → pose message, reference_space "room" → Python → both pages
```

- **Library:** [OpenCV.js 4.12.0](https://docs.opencv.org/4.12.0/) via the `@techstark/opencv-js` package, pinned at `4.12.0-release.1` (Apache-2.0). Its file is OpenCV's own published build. It runs in a worker so the 3D view keeps its frame rate. The worker chunk is about 10.8 MB and loads on the first **Start tracking** or **Calibrate camera**; the browser caches it afterwards.
- **Pose solving:** a single tag is solved in its own frame with `SOLVEPNP_IPPE_SQUARE`, then placed in the room. Several tags are solved together in room coordinates with `SOLVEPNP_SQPNP`. OpenCV.js's general `SOLVEPNP_IPPE` misplaced a square lying off the z = 0 plane in testing, so it is not used.
- **Rejection:** a frame is not used when no tag in the room's manifest is visible, the tag's shortest side is under 20 px in the processed frame, the mean corner reprojection error exceeds 3 px, or the position falls outside ±100 m.
- **Privacy:** camera frames stay on the phone. Only the measured position is sent.

## Frames and units

- **Source:** the phone camera's optical center. It is not the screen center.
- **Room frame:** the [prepared room frame](prepared-room.md#coordinate-frame). Units are meters, the origin is the floor center, +X is right, +Y is up, and +Z points toward the viewer, away from the desk.
- **Marker frame:** the center of the black square. +X points to the printed tag's right, +Y to its top, and +Z out of its printed face. The manifest's rotation turns this frame into the room. Size is the black square's edge.
- **Stand-in room tag:** ID 0, 150 mm, upright on the desk's front face. Its center is at `(0, 0.60, -0.90)` with the identity rotation, so it faces +Z toward the viewer.
- **Message:** a tracked pose has `reference_space: "room"`, and its position is already in room coordinates. Python applies no alignment to it, and the phone page no longer offers **Confirm alignment**, so the phone's alignment entry stays `not_aligned`. The Quest keeps the manual calibration from [room alignment](room-alignment.md).
- **Phone view:** while tracking, the phone's own 3D view moves to its latest local measurement of position and camera direction, so the view does not lag by a network round trip. This departs from rendering only Python-accepted state on the phone: the headset's sphere and both pages' diagnostics show the accepted position, but the phone's camera view does not wait for it. Orientation is not sent yet; Issue 4 adds it to the message.

Moving the phone 30 cm to the right raises the accepted X by 0.30. Moving it up raises Y. Moving it toward the desk lowers Z.

## Setting up

1. **Print the tag.** Print [tag36h11-00.svg](markers/tag36h11-00.svg) at 100 % with no fit-to-page scaling. Check that the black square measures 150 mm; a different printed size changes every distance by the same ratio.
2. **Place it.** Tape it flat and upright on the front of your real desk, horizontally centered, with its center 60 cm above the floor. The virtual desk then lines up with your real one.
3. **Print the board.** Print [calibration-board.svg](markers/calibration-board.svg) and keep it flat, for example taped to a book. Its exact printed size does not matter.
4. **Calibrate once.** Connect the phone and select **Calibrate camera**. Hold the phone as you will track, usually portrait. Show the board from different angles and distances; the page keeps one view about every 0.7 s until it has 15, then solves and saves the result with Python. The page refuses a result whose reprojection error exceeds 2 px. A rotated phone delivers a different resolution and needs its own calibration.
5. **Track.** Select **Start tracking** and point the camera at the tag.

Calibrations are stored in `data/tracking/cameras.json`, one per video resolution (`GET` and `PUT /api/tracking/cameras`). They survive restarts. Regenerate the printable sheets with `npm --prefix frontend run markers`. A test fails if the committed sheets differ from what the generator writes.

## Lifecycle and feedback

| Event | Phone shows | Python marker |
| --- | --- | --- |
| Start, tag not yet seen | Looking for a room marker… | Unchanged until 0.3 s, then `lost` |
| Tag measured | Tracking · marker 0 | `tracked`, at most 20 updates per second |
| Tag not usable for 0.3 s | Lost · reason (for example "No room marker in view.") | `lost`; the last position is never sent again |
| Tag usable again | Tracking · marker 0 | `tracked` |
| Stop tracking | Tracking off; camera released | `inactive` |
| Page hidden or left | Tracking stopped while the page was hidden… | `inactive`; camera released |
| Camera taken by the system | The camera stopped. Start tracking again. | `inactive` |
| Phone disconnects | Tracking stopped because the phone disconnected. | `lost`, set by Python |
| Camera permission refused | Camera permission was denied… | Unchanged |
| No calibration for this resolution | Lost · Calibrate the camera at W×H first… | `lost` |
| Room without markers | This room has no tracking markers… | Unchanged |

The 0.3 s grace keeps single missed frames from flickering the state, so the last accepted position can stay visible for up to 0.3 s after the tag disappears. Only one frame is processed at a time, so results never queue up. A result that arrives after a stop carries an old token and is discarded.

## Cadence and limits

- **Cadence:** publishing is capped at 20 per second. The actual rate is limited by detection time on the phone. The device report's `tracking` section records `frames_per_second` and `detect_ms`; measure them on the iPhone.
- **Range:** a 15 cm tag needs at least 20 px a side. With a typical phone focal length at 960 px, that is roughly 5 m away. Expect the best results from 0.4 to 3 m.
- **Accuracy (synthetic):** 30 cm moves along each axis measured to within 1 cm. A lone tag seen off-center from 1.2 m measured depth to about 1 % of distance. Real accuracy depends on calibration, print size, light and motion blur; record it on the device.
- **Visibility:** position exists only while a tag is in view. More tags extend coverage, but each must be placed exactly where the manifest says.
- **Jitter:** no smoothing is applied yet. Measure it before adding any.
- **Single-tag ambiguity:** a small tag seen nearly face-on from far away can flip the estimated orientation. Position is affected less.

## What is verified

Automated, desktop only:

- Synthetic frames rendered from known poses: placement, each room axis, turning in place, rotated and multiple tags, rejection reasons, resized intrinsics, and calibration recovering known intrinsics (`frontend/tests/vision.spec.ts`).
- Chromium's fake camera playing a synthetic video of the desk tag through the full browser → worker → Python → headset-page path. This covers placement within 3 cm, lost and recovery, stop and resume with the camera released, page hiding, disconnect, refused permission, missing calibration, and a room without markers (`frontend/tests/camera-tracking.spec.ts`).
- The fake camera playing the board: calibration recovers known intrinsics within 2 % and saves them (`frontend/tests/camera-calibration.spec.ts`).
- The committed sheets match the generator, and the printed tag and board are detected (`frontend/tests/printable-sheets.spec.ts`).
- Python accepts only `reference_space: "room"` poses, publishes the manifest's markers, and stores and refuses calibrations (`tests/`).

Not verified: anything on a real iPhone or Quest. Fixtures and the fake camera do not establish physical translation.

## Device check

Run this with iPhone 16 Chrome and Meta Quest 3 on the same HTTPS URL, using the [startup guide](diagnostic-startup.md).

1. Print, place, and calibrate as above. Record the calibration's resolution and error.
2. On the Quest, connect, enter VR, and confirm alignment at the floor center facing the desk.
3. On the iPhone, connect and start tracking from about 1.2 m in front of the desk. Confirm the Quest shows the phone's sphere where the phone is.
4. Move the phone 30 cm right, then 30 cm up, then 30 cm toward the desk, using a tape measure. Record the accepted position before and after each move from the diagnostics or a downloaded report.
5. Turn the phone in place without moving it. Record any position change.
6. Hold the phone still for 30 s and record the spread of positions.
7. Cover the tag, then uncover it. Record the lost and recovery behavior. Then stop and start tracking, switch apps, and disconnect.
8. Deny camera permission once, then allow it.
9. Download the device report on the phone and save it under `device-reports/`.

| Field | Result |
| --- | --- |
| Phone, OS, browser version | Pending |
| Headset, OS, browser version | Pending |
| Calibration resolution and error | Pending |
| Printed tag size | Pending |
| Axis moves (expected 0.30 m each) | Pending |
| Turning in place | Pending |
| Still-phone spread over 30 s | Pending |
| Frames per second, detection time | Pending |
| Lost, recovery, stop/start, page exit, disconnect | Pending |
| Permission refusal and recovery | Pending |

## Later work

- **Issue 33, room scale:** the user chose to confirm reconstructed room scale with markers. A tag of known size visible in the capture photos can fix the scene's scale.
- **Issue 4:** add the phone's orientation to the pose message.
- **Issue 10:** tracking loss during object manipulation.
