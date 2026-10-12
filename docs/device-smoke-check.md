# Issue #1: device smoke-check record

Status: **software diagnostic implemented; actual-device acceptance pending**.

User-approved scope adjustment: “Build the iPhone page first; add movement tracking later.” Targets are iPhone 16 Chrome for the mobile master and Meta Quest 3 for immersive VR. This changes the order of work; it does not provide evidence for the original phone-translation criterion. Keep [Issue #1](https://github.com/bhawishK/Escape-My-Room/issues/1) open until the remaining hardware criteria are resolved.

## Evidence from implementation

Automated on Windows, 2026-10-12:

- Real Python HTTP/WebSocket tests: master/solver state delivery, rejected role/source/schema/sequence/generation messages, isolated sessions and credentials, disconnect clearing, binary frames, connection replacement, and authenticated grant release after a failed initial socket.
- Playwright against the running service in desktop Microsoft Edge 155.0.4283.45: a simulator updates both separate browser views; a mobile-sized viewport works with XR unavailable; denied XR permission gives recovery guidance without losing the shared connection; a failed initial WebSocket allows a manual join retry in the same session.
- Visual inspection: 1440-pixel desktop and 390-pixel mobile layouts, no page errors or mobile horizontal overflow. These are desktop Edge screenshots, not hardware evidence.

Final automated result: **16 Python integration checks and 4 browser checks passed**. Strict TypeScript/Python checking and Ruff passed; the production build succeeded. Vite reports its standard chunk-size warning for the approximately 546 kB Three.js browser bundle (137 kB compressed). [Code review](issue-1-code-review.md) found one recovery bug and one optional typing improvement; both were resolved and re-reviewed.
- Strict TypeScript and Python typechecks, Ruff, and the production build are available in the [startup commands](diagnostic-startup.md).

The mobile viewport and permission tests use browser API overrides to exercise those branches. They are not iPhone or headset emulation. Simulator delivery proves the transport only. No iPhone, Quest, tunnel, certificate trust, real positional tracking, or real DOM-overlay held input was tested in this implementation session.

## Actual device record

Fill in observed results after following the steps below. “Pending” is not a pass or a measured capability result.

| Field | Mobile master | VR solver |
| --- | --- | --- |
| Planned device | iPhone 16 | Meta Quest 3 |
| Planned browser | Chrome on iPhone | Quest browser with WebXR; exact browser/version pending |
| Actual device, OS, browser/version | Pending | Pending |
| Date and tester | Pending | Pending |
| Shared trusted HTTPS URL | Pending | Pending |
| Correct role / connected state / peer visible | Pending | Pending |
| Immersive mode entered and ended | Phone tracking path deferred | Pending `immersive-vr` |
| Runtime reference space | Not exercised | Pending `local` |
| Positional tracking / emulated position | Phone tracking path deferred | Pending |
| DOM overlay type | Not exercised | Pending |
| Held DOM control events | Not exercised | Pending or unavailable |
| Marker received and displayed | Pending, simulator check separate | Pending, simulator check separate |
| Permission denial and recovery | Pending | Pending |
| Saved report / observations | Pending | Pending |

## Test the approved first slice

1. Build and serve the app through a trusted HTTPS URL reachable by both devices. Use the [startup guide](diagnostic-startup.md).
2. On iPhone Chrome, create a session with the default WebXR input. Confirm **Connected · Mobile master**, the session/invite values, and the diagnostics report. The page must remain usable when XR is unavailable; moving the iPhone must not be represented as working positional tracking.
3. Open its invite on Quest. Join as solver and confirm **Connected · VR solver** and both participant roles. Enter VR and inspect the neutral grid and axes. End the session using overlay **End XR** if available, otherwise controller select, then enter VR again. Record mode, reference space, position status, and exit behavior.
4. For a separate transport check, leave that session. On the computer choose **Simulator (testing only)** and create another session. Join its invite on Quest. Send `(0.25, 0.10, -0.30)`, then `(0.75, 0.10, -0.30)`. Confirm the solver page reports both accepted values, and the VR sphere moves along the diagnostic X axis. Record this as **simulator-to-Quest**, not phone tracking.
5. Leave the master session. The solver should retain its connection but lose the usable marker. Leave the solver and rejoin to check role release. If network connectivity drops, use **Leave session** and join again; automatic reconnect is not in this slice.
6. Deny XR permission once where the device permits it. Confirm recovery guidance, restore permission, and retry. Record the actual browser behavior, including any unsupported mode.
7. Download the report from each page and fill the table. When a DOM overlay is present, hold and release **Hold input probe** and check its event count. When absent, record “unavailable”; do not infer held-control support from the ordinary page.

## Complete the original tracked-phone criterion later

The approved iPhone movement-tracking mechanism remains a separate decision. On a phone/browser that actually supports positional WebXR, the implemented AR path can be exercised: enter AR, verify non-emulated `tracked` position, translate the phone along each axis, and check Python-accepted coordinates and the marker in Quest. Start/end AR, lose/recover tracking, and check overlay held input. These results still need recording; desktop simulator tests cannot substitute for them.

Do not mark phone-to-VR physical translation accepted merely because a 2D page, an XR support probe, or generated coordinates work.
