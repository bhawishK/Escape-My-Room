# Phone view and tracking decision

Issue 19 makes physical phone movement reach Python and the headset. The phone shows the room full screen. Turning the phone turns the view, and walking moves it once the camera sees a printed AprilTag fixed in the room. This page records the chosen mechanism, its frames and units, the setup, and what is and is not verified.

## Why a printed tag

iPhone browsers expose no WebXR. Every iPhone browser, Chrome included, runs on Apple's WebKit engine, and the [recorded iPhone Chrome report](device-reports/2026-10-12-iphone-chrome-connected.json) (iOS 26.6.1, Chrome 155) shows `api_available: false`. The retained `immersive-ar` path could therefore never run on the target phone.

On 19 October 2026 the user approved changing the stack: the phone is an ordinary web page, and only the Quest uses WebXR. Three ways to measure the phone were weighed:

| Option | Real meters | Drift | iPhone browser | Outcome |
| --- | --- | --- | --- | --- |
| Printed tag + OpenCV.js | Yes, from the printed size | None while the tag is in view | Uses the camera API only | Chosen for position |
| Markerless SLAM in the browser (AlvaAR) | No; one camera has no scale | Accumulates | Untested; the project is unmaintained since 2023 and GPL-3.0 | Not chosen |
| Motion sensors | Rotation only | Position drifts within seconds | Yes | Used for turning the view only |

Later the same day the user asked for the room view first and found the camera calibration step too hard. The phone now opens straight into the room, turning needs nothing printed, and tracking uses built-in lens values instead of a calibration board.

## What the phone shows

- **Room view:** connecting as the phone opens the room full screen. **Close** returns to the page, and **Open room view** opens it again.
- **Before tracking:** the view stands at `(0, 1.5, 1.6)`, behind the floor center, facing the desk and tilted 20° down, so the desk, floor, box and cabinet fit on the screen.
- **Turn with phone:** turns the view with the phone's orientation sensor (`deviceorientation`). iPhone asks for motion permission once. The first reading faces the desk; nothing is printed or measured. **Stop turning** leaves the view where it is.
- **Start tracking:** the back camera looks for the printed tag. The camera picture is never shown; the room view is the display. While the tag is measured, the view moves to the phone's measured position, and each measurement pulls the sensor's heading toward the tag's, so the two agree. Without **Turn with phone**, the view uses the tag's measured direction instead.
- **Field of view:** 70° along the screen's long side, close to what the phone camera sees, so the virtual room lines up with the real one when tracking.

## How tracking works

```
back camera (getUserMedia, 1280 × 720 requested, never displayed)
  → frame drawn at most 960 px on its long side
  → Web Worker: OpenCV.js AprilTag 36h11 detection, sub-pixel corners, solvePnP
  → camera position in room meters
  → pose message, reference_space "room" → Python → both pages
```

- **Library:** [OpenCV.js 4.12.0](https://docs.opencv.org/4.12.0/) via the `@techstark/opencv-js` package, pinned at `4.12.0-release.1` (Apache-2.0). Its file is OpenCV's own published build. It runs in a worker so the 3D view keeps its frame rate. The worker chunk is about 10.8 MB and loads on the first **Start tracking**; the browser caches it afterwards.
- **Lens values:** the iPhone 16 main camera's 26 mm-equivalent lens spans about 67° across the sensor's long side, so the tracker assumes a focal length of 0.75 × the video's long side in pixels, the image center as principal point, and no distortion. If this is off, every distance from the tag is off by the same ratio. A 5 % error puts a phone 1.2 m from the tag about 6 cm too near or far. Measure it in the device check; a calibration step can return if the error matters.
- **Pose solving:** a single tag is solved in its own frame with `SOLVEPNP_IPPE_SQUARE`, then placed in the room. Several tags are solved together in room coordinates with `SOLVEPNP_SQPNP`. OpenCV.js's general `SOLVEPNP_IPPE` misplaced a square lying off the z = 0 plane in testing, so it is not used.
- **Rejection:** a frame is not used when no tag in the room's manifest is visible, the tag's shortest side is under 20 px in the processed frame, the mean corner reprojection error exceeds 3 px, or the position falls outside ±100 m.
- **Privacy:** camera frames stay on the phone. Only the measured position is sent.

## Frames and units

- **Source:** the phone camera's optical center. It is not the screen center.
- **Room frame:** the [prepared room frame](prepared-room.md#coordinate-frame). Units are meters, the origin is the floor center, +X is right, +Y is up, and +Z points toward the viewer, away from the desk.
- **Tag frame:** the center of the black square. +X points to the printed tag's right, +Y to its top, and +Z out of its printed face. The manifest's rotation turns this frame into the room. Size is the black square's edge.
- **Stand-in room tag:** ID 0, 150 mm, upright on the desk's front face. Its center is at `(0, 0.60, -0.90)` with the identity rotation, so it faces +Z toward the viewer.
- **Message:** a tracked pose has `reference_space: "room"`, and its position is already in room coordinates. Python applies no alignment to it, and the phone page offers no **Confirm alignment**, so the phone's alignment entry stays `not_aligned`. The Quest keeps the manual calibration from [room alignment](room-alignment.md).
- **Phone view:** the view uses the phone's own latest measurement, so it does not lag by a network round trip. This departs from rendering only Python-accepted state on the phone: the headset's sphere and both pages' diagnostics show the accepted position, but the phone's view does not wait for it. Orientation is not sent yet; Issue 4 adds it to the message.

Moving the phone 30 cm to the right raises the accepted X by 0.30. Moving it up raises Y. Moving it toward the desk lowers Z.

## Setting up

1. **Look around:** connect the phone, then select **Turn with phone** and allow motion access. Nothing needs printing for this.
2. **Print the tag** for walking: print [tag36h11-00.svg](markers/tag36h11-00.svg) at 100 % with no fit-to-page scaling. Check that the black square measures 150 mm; a different printed size changes every distance by the same ratio.
3. **Place it:** tape it flat and upright on the front of your real desk, horizontally centered, with its center 60 cm above the floor. The virtual desk then lines up with your real one.
4. **Track:** select **Start tracking**, allow camera access, and point the phone at the tag.

Regenerate the printable sheet with `npm --prefix frontend run markers`. A test fails if the committed sheet differs from what the generator writes.

## Lifecycle and feedback

The room view's status line shows these messages.

| Event | Phone shows | Python marker |
| --- | --- | --- |
| Start, tag not yet seen | Point the camera at the printed tag… | Unchanged until 0.3 s, then `lost` |
| Tag measured | Tracking · tag 0 | `tracked`, at most 20 updates per second |
| Tag not usable for 0.3 s | Lost · reason (for example "No room marker in view.") | `lost`; the last position is never sent again |
| Tag usable again | Tracking · tag 0 | `tracked` |
| Stop tracking | Tracking off; camera released | `inactive` |
| Page hidden or left | Tracking stopped while the page was hidden… | `inactive`; camera released |
| Camera taken by the system | The camera stopped. Start tracking again. | `inactive` |
| Phone disconnects | Room view closes; camera released | `lost`, set by Python |
| Camera permission refused | Camera permission was denied… | Unchanged |
| Motion permission refused | Motion permission was denied… | Unchanged |
| Room without markers | This room has no tracking markers… | Unchanged |

The 0.3 s grace keeps single missed frames from flickering the state, so the last accepted position can stay visible for up to 0.3 s after the tag disappears. Only one frame is processed at a time, so results never queue up. A result that arrives after a stop carries an old token and is discarded.

## Cadence and limits

- **Cadence:** publishing is capped at 20 per second. The actual rate is limited by detection time on the phone. The device report's `tracking` section records `frames_per_second` and `detect_ms`; measure them on the iPhone.
- **Range:** a 15 cm tag needs at least 20 px a side, roughly 5 m away. Expect the best results from 0.4 to 3 m.
- **Accuracy (synthetic):** 30 cm moves along each axis measured to within 1 cm with the true lens values. A lone tag seen off-center from 1.2 m measured depth to about 1 % of distance. On the phone, the assumed lens values add their own scale error; record it.
- **Visibility:** position exists only while a tag is in view. More tags extend coverage, but each must be placed exactly where the manifest says.
- **Jitter:** no smoothing is applied to the position yet. Measure it before adding any.
- **Turning:** the orientation sensor's heading drifts slowly on its own; while the tag is tracked it is pulled back into line.

## What is verified

Automated, desktop only:

- Synthetic frames rendered from known poses: placement, each room axis, turning in place, rotated and multiple tags, rejection reasons, and resized intrinsics (`frontend/tests/vision.spec.ts`).
- Chromium's fake camera playing a synthetic video of the desk tag, rendered with the assumed lens, through the full browser → worker → Python → headset-page path. This covers placement within 3 cm, lost and recovery, stop and resume with the camera released, page hiding, disconnect, refused permission, and a room without markers (`frontend/tests/camera-tracking.spec.ts`).
- The room view opening full screen, closing and reopening, turning on and off, and a refused motion permission (`frontend/tests/connected-view.spec.ts`). The turn math: an upright phone looks ahead, turning changes the heading by the same angle, tilting does not, and landscape matches portrait (`frontend/tests/phone-view.spec.ts`).
- The committed tag sheet matches the generator, and the printed tag is detected upright at its printed size (`frontend/tests/printable-sheets.spec.ts`).
- Python accepts only `reference_space: "room"` poses and publishes the manifest's markers (`tests/`).

Not verified: anything on a real iPhone or Quest. Fixtures and the fake camera do not establish physical translation, and the assumed lens values are untested on the iPhone.

## Device check

Run this with iPhone 16 Chrome and Meta Quest 3 on the same HTTPS URL, using the [startup guide](diagnostic-startup.md).

1. Connect the phone and confirm the room fills the screen. Select **Turn with phone**, allow motion access, and turn around; the view should turn with you.
2. Print and place the tag as above.
3. On the Quest, connect, enter VR, and confirm alignment at the floor center facing the desk.
4. On the iPhone, select **Start tracking** about 1.2 m in front of the desk. Confirm the Quest shows the phone's sphere where the phone is.
5. Measure the distance from the tag with a tape measure and compare it with the accepted position. This checks the assumed lens values.
6. Move the phone 30 cm right, then 30 cm up, then 30 cm toward the desk. Record the accepted position before and after each move from the diagnostics or a downloaded report.
7. Turn the phone in place without moving it. Record any position change.
8. Hold the phone still for 30 s and record the spread of positions.
9. Cover the tag, then uncover it. Record the lost and recovery behavior. Then stop and start tracking, switch apps, and disconnect.
10. Deny camera and motion permission once each, then allow them.
11. Download the device report on the phone and save it under `device-reports/`.

| Field | Result |
| --- | --- |
| Phone, OS, browser version | Pending |
| Headset, OS, browser version | Pending |
| Room view and turning | Pending |
| Printed tag size | Pending |
| Tape-measured vs accepted distance from the tag | Pending |
| Axis moves (expected 0.30 m each) | Pending |
| Turning in place | Pending |
| Still-phone spread over 30 s | Pending |
| Frames per second, detection time | Pending |
| Lost, recovery, stop/start, page exit, disconnect | Pending |
| Camera and motion permission refusal and recovery | Pending |

## Later work

- **Issue 33, room scale:** the user chose to confirm reconstructed room scale with markers. A tag of known size visible in the capture photos can fix the scene's scale.
- **Issue 4:** add the phone's orientation to the pose message.
- **Issue 10:** tracking loss during object manipulation.
