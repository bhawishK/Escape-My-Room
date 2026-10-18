# Issue #25: iPhone Chrome capture record

Status: **implemented through the native camera picker; the user reported on 15 October 2026 that every real iPhone check passed. Device versions and the saved report were not supplied.**

## Decision

On 15 October 2026 the user chose to keep the native camera picker from [Issue #24](room-photos.md) for [Issue #25](https://github.com/bhawishK/Escape-My-Room/issues/25), rather than adding a live in-page viewfinder (`getUserMedia`). **Take photo** hands off to the phone's own camera; each shot returns to the page as one photo. The user also chose a real iPhone record as the only acceptance check for this issue, with no new automated browser test.

No new application code was added for #25. The capture flow, storage, orientation handling and refusals are the ones delivered and tested in #24.

## How the acceptance criteria are met

| Criterion | How | Evidence |
| --- | --- | --- |
| Review, removal before submission, adding views and overview selection, without WebXR or LiDAR | **Take photo** can be pressed repeatedly and mixed with **Choose photos**. Every photo shows in **Photos to save** with **Remove** and an **Overview** choice. The page uses no WebXR or LiDAR. | #24 browser tests; real iPhone steps 2–5 below |
| Camera denial or unavailable capture leaves upload usable; camera released when leaving capture | The page never requests camera permission or holds a camera stream. iOS asks for and owns camera access, and releases the camera when its camera view closes. **Choose photos** does not depend on the camera. | Real iPhone steps 6–7 below. A live-viewfinder release check does not apply. |
| Orientation and image identity consistent across preview, saved bundle and processing | Each photo gets a server ID and a SHA-256 of the original bytes. Sideways photos get an upright PNG copy, and processing reads that copy. | #24 browser and API tests with generated photos; real iPhone steps 4, 5 and 8 below |
| Browser checks for permission/retry/fallback; separate real iPhone Chrome record | The page has no permission or retry logic of its own to test, so the agreed check is this real-device record. | The record table below |

## Real iPhone Chrome check

Use the HTTPS tunnel from the [startup guide](diagnostic-startup.md). Open the tunnel link in **Chrome** on the iPhone, not Safari, and scroll to **Room photos**.

1. **Versions.** In iPhone Settings → General → About, note the model and iOS version. In Chrome, open `chrome://version` and note the Chrome version.
2. **Several camera shots.** Tap **Take photo**, take a photo, and confirm it appears under the buttons. Repeat for at least three views of the room, including one with the phone held in portrait and one in landscape.
3. **Mix with saved photos.** Tap **Choose photos** and add one existing photo, ideally an HDR or Portrait-mode photo.
4. **Review before saving.** Check every preview is the right way up. Remove one photo with **Remove**. Mark a different photo as **Overview**. Note what names the camera shots show; iOS may call every camera shot `image.jpg`.
5. **Save and reload.** Add a sentence of room instructions and tap **Save photos**. Confirm **Saved photos** shows the same photos, upright, with your overview selected. Reload the page and confirm they are still there.
6. **Camera access denied.** In iPhone Settings → Chrome, turn **Camera** off. Back in the page, tap **Take photo** and note what iOS shows. Then tap **Choose photos**, add a photo and save it, confirming upload still works.
7. **Camera access restored.** Turn **Camera** back on and confirm **Take photo** works again, reloading the page if needed.
8. **Save the evidence.** On the computer running the server, open `http://localhost:8000/api/captures` and save the page as `docs/device-reports/<date>-iphone-chrome-capture.json`. It records each saved photo's size, SHA-256, original and upright dimensions, and EXIF orientation.

## Record

“Pending” is not a pass. On 15 October 2026 the user reported “I have checked. All is okay.” covering the steps above. The rows below record that report; individual observations were not described separately.

| Field | Observation |
| --- | --- |
| Date and tester | 2026-10-15, the user |
| iPhone model / iOS version | Not supplied |
| Chrome version (`chrome://version`) | Not supplied |
| HTTPS route | Not supplied |
| Several camera shots added one after another (step 2) | OK, user-reported |
| Camera shots mixed with library photos (step 3) | OK, user-reported |
| HDR or Portrait-mode photo accepted (step 3) | OK, user-reported |
| Previews upright before saving (step 4) | OK, user-reported |
| Remove and overview change before saving (step 4) | OK, user-reported |
| Names shown for camera shots (step 4) | Not described |
| Saved photos upright with chosen overview (step 5) | OK, user-reported |
| Capture still shown after reload (step 5) | OK, user-reported |
| What iOS shows when camera access is off (step 6) | Not described; reported OK |
| Upload still works with camera access off (step 6) | OK, user-reported |
| Camera works again after restoring access (step 7) | OK, user-reported |
| Saved report | Not supplied |

If camera shots all show the same name, such as `image.jpg`, record it. Identity is kept by server image IDs and hashes either way, but identical names make the overview choice hard to read, and a follow-up could give each shot a distinct label.
