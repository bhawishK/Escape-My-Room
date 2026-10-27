# Phone view and tracking decision

Issue 19 is about physical phone movement reaching Python and the headset. For now the phone shows the room full screen, turns the view as the phone turns, and moves it a step at a time as the person walks. Walking is counted, not measured, so the position is a rough estimate. This page records what the phone does, what was tried for position, and the options still open.

## What the phone shows

- **Room view:** connecting as the phone opens the room full screen. **Close** returns to the page, and **Open room view** opens it again.
- **Viewpoint:** the view stands at `(0, 1.5, 1.6)`, behind the floor center at phone height, facing the desk and tilted 20° down, so the desk, floor, box and cabinet fit on the screen. Walking moves it from there.
- **Turning:** the view turns with the phone's orientation sensor (`deviceorientation`) whenever the room view is open. There is no button: tapping **Connect phone**, or **Open room view**, asks iPhone for motion permission, which it only allows during a tap. The first reading faces the desk; nothing is printed or measured.
- **Field of view:** 70° along the screen's long side, close to what a phone camera sees.
- **Drift:** the sensor's heading drifts slowly on its own. Nothing corrects it yet; **Close** and **Open room view** re-anchor it to face the desk.

- **Walking:** whenever the room view is open, steps are counted from the accelerometer (`devicemotion`), and each moves the view one step length toward where the phone faces, gliding over 0.35 s. Without turning readings, steps go toward the desk. **Back to start** returns to the starting viewpoint, and **Step** cycles the step length through 0.4–0.8 m (default 0.6 m). Closing the room view stops walking.

Turning was checked on an iPhone on 19 October 2026 and worked.

## Walking by counting steps

The user accepted on 19 October 2026 that walking need not be accurate. Without AR tracking, the phone cannot measure where it is, but its accelerometer shows the bounce of each step.

- **Steps:** gravity's direction is tracked slowly, over about 0.8 s, so the phone may be held at any angle. The acceleration along gravity, smoothed over 60 ms, is the bounce. A step is counted when the bounce rises above the threshold after falling back below zero, at most one every 0.3 s. Readings while the phone turns faster than 150°/s are ignored, so turning it does not take steps.
- **Sensitivity:** the threshold is 1.1 m/s². The user removed the button for choosing it on 20 October 2026; the code keeps 1.6 and 0.7 m/s² for low and high. Smoothing lowers the measured bounce by about a quarter at walking pace, so in synthetic tests normal counts steps that bounce about 1.5 m/s² or more, and high about 1.0.
- **Where a step goes:** one step length along the phone's heading, level with the floor. The floor's edge and the static furniture, widened by a 0.25 m body radius, stop a step; a step into them slides along them when it can. Movable objects do not block. Thin static entities are the floor; taller static ones are furniture.
- **Headset:** each step sends the new position to Python as a tracked room-frame pose, so the headset's phone sphere moves with the steps. The pose also carries where the screen centre aims, as heading and pitch. Closing the room view sends `inactive`.

What it cannot do: small moves such as leaning or moving the phone in the hand, sideways or backward steps (each counts as a step forward), or walking in a different direction from where the phone faces. Step length varies, and the heading drifts, so the error grows with every step. **Back to start**, from the starting spot facing the desk, recovers.

## Position: tried and dropped

iPhone browsers expose no WebXR. Every iPhone browser, Chrome included, runs on Apple's WebKit engine, and the [recorded iPhone Chrome report](device-reports/2026-10-12-iphone-chrome-connected.json) (iOS 26.6.1, Chrome 155) shows `api_available: false`. Markerless tracking with real meters is therefore unavailable to an iPhone web page.

On 19 October 2026 the phone was given camera tracking against a printed AprilTag: OpenCV.js in a Web Worker detected tag 36h11 ID 0, 150 mm, taped to the desk front, and solved the phone's room position from it. It passed desktop tests with synthetic frames and a fake camera. On the first iPhone try it reported **No room marker in view**, meaning no tag was detected at all; the cause was not established.

The same day the user dropped it as too messy: the tag had to be printed at exact scale and taped at a measured place, and position existed only while the tag stayed in view, which works against moving the phone freely to manipulate objects. The tracking code, the OpenCV.js dependency, the printable sheet, and the manifest's `markers` were removed. It remains in git history at commit `f45a6d4`.

Options considered for position later:

| Option | Setup | Tracking | Cost |
| --- | --- | --- | --- |
| Android phone with WebXR (ARCore) | None | Markerless, real meters | Needs an ARCore Android phone; keeps the browser and Python stack |
| Native iPhone app (ARKit) | Install the app | Markerless, real meters | Needs a Mac with Xcode; a second codebase |
| Printed tag | Print and place | Only while the tag is in view | Dropped, as above |
| Motion sensors alone | None | Rotation only; position drifts within seconds | Used for turning only |

No choice has been made.

## What stays in place for position

The pose message is unchanged: a tracked pose carries `reference_space: "room"` and a position in room meters, and Python publishes it as the phone's marker, which the headset draws as a sphere. See the [connection and pose contract](diagnostic-protocol.md). The phone sends a pose only while walking, as a step-counted estimate rather than a measurement; otherwise its marker stays `inactive`. The headset keeps the manual calibration from [room alignment](room-alignment.md).

## Measured tracking with 8th Wall (Issue 57)

Since Issue 59, a phone where the [8th Wall engine](https://github.com/8thwall/engine) can track uses it instead of turning and counted steps:
- **Tracking:** the engine uses the back camera and motion sensors together, and gives position in metres and the phone's real height above the floor.
- **Start:** it starts at the room view's starting place, facing the desk.
- **Camera image:** never drawn.
- **Fallback:** elsewhere, or before the engine loads, the phone counts steps as described above, and Back to start and the step length button appear only then.
- **Scale (issue 112):** 8th Wall works its scale out from the camera and motion sensors, and was off on the iPhone: it put the phone 0.72 m and then 1.16 m above the floor against a real 1.3–1.4 m, so the room moved 50–85% as far as the person walked.
  - **How it's measured:** over the first 1.5 s of unbroken tracking (at least 5 poses) after each start and each restart, the phone takes the median of the heights 8th Wall reports. The factor is the real height divided by that median, kept between 0.5 and 2.
  - **How it's applied:** 8th Wall's movement is scaled by the factor, so distances come out in real metres. Until the first measurement the factor is 1. When it arrives, scaling continues from where the phone is, so the view doesn't jump; only the phone's height rises to the real height, once, after a start.
  - **Restarts:** after a loss, a restarted 8th Wall is lined up with the last good place, keeping the last factor until it's measured again. A "found its place again" recovery is the same world, so its factor stands. Recentring starts the measuring over too.
  - **The real height** is 1.4 m (the camera height splat rooms are scaled for) unless the link gives one, for example `?height=1.35`. A height given once is kept on the phone, so later links without it still use it.
  - **Reporting:** the tracking summary (Send log and diagnostic report) gives `scale`: the factor, both heights, and whether it was clamped. The movement log has a `scale` event.
- **Calibrating by two objects (issue 120):** the height correction was not enough. Walking 5–6 m to the hallway's sink moved the scene about 3.3 m, because 8th Wall's wrong height doesn't fully reflect its wrong distances. When the room has a landmark map (`landmarks.json`, #110), **Calibrate** in the room view lists its objects.
  - **Steps:** the person stands at one and taps it, walks to another at least 1.5 m away, and taps that.
  - **What the phone works out:** 8th Wall's **scale** is the room distance between the two over 8th Wall's distance between the taps, its **heading** is the turn between the two directions, and the person is **placed** at the second object. Each object's point is taken 0.4 m toward the other, where a person stands.
  - **Effect:** this replaces the height-based scale. It also removes the need to start on one spot facing one way.
  - **When it's undone:** a restart after a loss, or Recentre, undoes it, because 8th Wall starts a new world with a new scale. The phone says to calibrate again.
  - **Refusals:** taps before tracking, objects closer than 1.5 m, or no walk between the taps are refused with what to do.
  - **Reporting:** the calibration is in the tracking summary and Send log.
- **Choosing step counting:** add `?tracking=steps` to the link (for example `https://…trycloudflare.com/?tracking=steps`) to count steps even where the engine could track, to compare the two on the same phone. The tracking summary in Send log gives the reason as "step counting chosen in the link".
- **Version:** the engine is pinned to `@8thwall/engine-binary@1.0.0`.
- **Credits:** the room view carries the credits its licence requires.

On 21 October 2026 it ran in iPhone Chrome without its camera image. It tracked well between losses, but lost tracking four times in three minutes, each time pointing steeply at the floor and turning fast. See [the iPhone tracking check](iphone-tracking-check.md).

### Movement log for device checks

The room view records what tracking does. **Send log** posts it to Python, which saves it as `movement-logs/<UTC time>.json` in the data folder (`data/` by default). Nothing has to be copied off the phone. The log keeps the last five minutes:
- **Poses, ten a second:** time since the room view opened, mode (`measured` or `steps`), status, position in metres, heading and pitch in radians.
- **Events:**
  - Which mode was chosen, and if steps, why the engine could not track.
  - The camera opening: `requesting`, `hasStream`, `hasVideo` or `failed`.
  - The engine's tracking status and reason changes, such as `LIMITED INITIALIZING` then `NORMAL UNSPECIFIED`.
  - Engine errors.
  - The room view opening and closing.

For a check without video, mark the floor with tape 1 m from the start toward the desk and 1 m to the side. Then:
1. Stand on the start facing the desk, and tap **Connect phone**.
2. Move the phone gently until it follows you.
3. Stand on each mark for a few seconds, then come back.
4. Crouch, turn a quarter left, and point at the plain floor for a few seconds.
5. Tap **Send log**.

The log shows how far the phone thought each mark was.

## What is verified

Automated, desktop only:

- The room view opening full screen, closing and reopening, turning on and off with its status line, and a refused motion permission (`frontend/tests/connected-view.spec.ts`).
- The turn math: an upright phone looks ahead, turning changes the heading by the same angle, tilting does not, and landscape matches portrait (`frontend/tests/phone-view.spec.ts`).
- Step counting on synthetic motion with the phone tilted: a walk counts its steps, holding still or turning quickly counts none, and gentle steps need the high sensitivity. Steps follow the heading, and the floor's edge and the furniture stop or slide them (`frontend/tests/steps.spec.ts`).
- Walking end to end: synthetic motion events count steps on the phone page, the desk stops the walk, and the headset page shows each position through Python, then the start position after **Back to start** and `inactive` after **Close** (`frontend/tests/connected-view.spec.ts`).

On a real iPhone: turning works, as reported by the user on 19 October 2026. Landscape, permission refusal, and drift over time are not recorded. Walking is not yet tried on a phone: record whether steps are counted while walking, missed or added, and how far the view ends up from where you walked.

A separate spike tests pointing at objects with the eyes or head through the front camera; see [gaze cursor](gaze-cursor.md). The front camera sees the face, not the room, so it cannot measure the phone's position.

## Later work

- **Issue 19:** choose and build a way to measure the phone's position.
- **Issue 33, room scale:** the user chose to confirm reconstructed room scale with markers. A tag of known size visible in the capture photos can fix the scene's scale. This is separate from phone tracking.
- **Issue 4:** show each person to the other, including which way they face. See [participant presence](participant-presence.md).
- **Issue 10:** tracking loss during object manipulation.
