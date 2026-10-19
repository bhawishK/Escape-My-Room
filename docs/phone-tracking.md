# Phone view and tracking decision

Issue 19 is about physical phone movement reaching Python and the headset. For now the phone shows the room full screen and turns the view as the phone turns. Walking does not move the view, and the phone sends no position. This page records what the phone does, what was tried for position, and the options still open.

## What the phone shows

- **Room view:** connecting as the phone opens the room full screen. **Close** returns to the page, and **Open room view** opens it again.
- **Viewpoint:** the view stands at `(0, 1.5, 1.6)`, behind the floor center at phone height, facing the desk and tilted 20° down, so the desk, floor, box and cabinet fit on the screen. It stays there.
- **Turn with phone:** turns the view with the phone's orientation sensor (`deviceorientation`). iPhone asks for motion permission once. The first reading faces the desk; nothing is printed or measured. **Stop turning** leaves the view facing where it was. The status line reads **Turning with the phone** or **Turning off**.
- **Field of view:** 70° along the screen's long side, close to what a phone camera sees.
- **Drift:** the sensor's heading drifts slowly on its own. Nothing corrects it yet; **Stop turning** and **Turn with phone** again re-anchor it to face the desk.

Turning was checked on an iPhone on 19 October 2026 and worked.

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

The pose message is unchanged: a tracked pose carries `reference_space: "room"` and a position in room meters, and Python publishes it as the phone's marker, which the headset draws as a sphere. See the [connection and pose contract](diagnostic-protocol.md). The phone sends no pose now, so its marker stays `inactive`. The headset keeps the manual calibration from [room alignment](room-alignment.md).

## What is verified

Automated, desktop only:

- The room view opening full screen, closing and reopening, turning on and off with its status line, and a refused motion permission (`frontend/tests/connected-view.spec.ts`).
- The turn math: an upright phone looks ahead, turning changes the heading by the same angle, tilting does not, and landscape matches portrait (`frontend/tests/phone-view.spec.ts`).

On a real iPhone: turning works, as reported by the user on 19 October 2026. Landscape, permission refusal, and drift over time are not recorded.

## Later work

- **Issue 19:** choose and build a way to measure the phone's position.
- **Issue 33, room scale:** the user chose to confirm reconstructed room scale with markers. A tag of known size visible in the capture photos can fix the scene's scale. This is separate from phone tracking.
- **Issue 4:** add the phone's orientation to the pose message.
- **Issue 10:** tracking loss during object manipulation.
