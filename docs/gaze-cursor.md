# Gaze cursor spike

A test of whether the phone's front camera can point at room objects with the eyes or the head, before committing to it as a selection technique. It runs on the phone's room view; it does not measure the phone's position. See [phone view and tracking](phone-tracking.md) for that question.

## How it works

- **Face tracking:** MediaPipe's face landmarker (`@mediapipe/tasks-vision` 1.0.1, Apache-2.0) finds 478 face points, including both irises, and the head's pose in each front-camera frame. Its runtime is served by the app and loads on the first **Gaze cursor**; the 3.7 MB face model downloads from Google's model storage, so the phone needs internet access. Camera frames stay on the phone.
- **Inputs:** the head's forward direction and its offset from the camera, and each iris's offset from its eye's center in eye widths.
- **Calibration:** nine dots in a 3 × 3 grid. Look at each dot and tap it; the face from the 0.4 s before the tap is recorded. One calibration fits two cursors: **head** uses the head inputs only, **eyes** adds the irises. Both are linear mappings to the screen, lightly regularized so jitter in an input that barely moved does not steer the cursor.
- **Cursor:** smoothed and drawn over the room view. The object under it is outlined, the cursor turns yellow, and the status line names it.
- **Accuracy test:** five new dots, each looked at and tapped. The status line reports both cursors' mean distance from the dots in screen points, so the two can be compared on the same calibration.

Recalibrate after changing how the phone is held; the mapping assumes the grip and orientation used during calibration.

## Using it on the iPhone

1. Build and start the server as in the [startup guide](diagnostic-startup.md), connect the phone, and keep the room view open.
2. Hold the phone as you normally would, at a comfortable distance, in portrait. Select **Gaze cursor** and allow camera access. Your face shows top left; keep it in that preview.
3. Look at each dot and tap it, keeping the head still and moving the eyes as much as you can.
4. Move your eyes over the desk, cabinet and box, and watch the outline. **Switch to head** compares the head cursor.
5. Select **Test accuracy** and tap the five dots. Note the result, then download the diagnostic report: its `gaze` section keeps the numbers, frame rate and detection time.

## Device check

| Field | Result |
| --- | --- |
| Phone, OS, browser version | Pending |
| Model loads; frames per second; detection time | Pending |
| Eyes cursor mean error (points; screen size) | Pending |
| Head cursor mean error (points; screen size) | Pending |
| Can the desk, cabinet and box each be pointed at reliably? | Pending |
| Effect of moving the phone in the hand after calibrating | Pending |
| Lighting and glasses notes | Pending |

## Verified so far

Desktop only:

- The calibration fit, iris and head inputs, and regularization against imprecise taps (`frontend/tests/gaze.spec.ts`).
- A refused camera permission is explained and leaves the phone connected (`frontend/tests/connected-view.spec.ts`).
- One manual run in desktop Edge with a fake camera playing a portrait photo: the model loaded with the GPU delegate, found the face, and the calibration, cursor, outline and accuracy test completed. A still photo cannot measure accuracy, and this run is not an automated test, because it needs the downloaded model.

Not verified: anything on a real phone.
