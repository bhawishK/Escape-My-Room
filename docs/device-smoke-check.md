# Issue #1: device smoke-check record

Status: **simplified shared-room software implemented; Quest VR entry previously confirmed by the user; fresh device checks pending**.

Targets are iPhone 16 Chrome for the mobile master and Meta Quest 3 for immersive VR. The user approved: “Build the iPhone page first; add movement tracking later.” On 12 October 2026, the user also requested removing the simulator and session IDs/authentication in favor of a simple VR connected status. This supersedes the original session-enrollment design. Keep [Issue #1](https://github.com/bhawishK/Escape-My-Room/issues/1) open while physical phone tracking and hardware acceptance remain unresolved.

## Current software evidence

Automated on Windows, 2026-10-12:

- **12 real Python WebSocket integration checks passed:** direct phone/VR connection, accepted shared pose, phone-only publication, stale sequence rejection, invalid/simulated input rejection, malformed/binary frame recovery, phone disconnect/reconnect, and replacement of a VR tab without incorrectly clearing its connection status.
- **4 Playwright browser checks passed:** phone sees VR join/disconnect without session fields or simulator; mobile-sized page works with XR unavailable; VR permission denial leaves the connection usable; a failed initial socket retries with one role button.
- The permission and unavailable-XR checks use browser API overrides. They are desktop Microsoft Edge checks, not iPhone or headset emulation. Generated test messages are protocol fixtures, not physical tracking evidence.
- Visual inspection of the live preview: desktop at 1440 pixels and mobile at 390 pixels show the new role buttons and VR connected status. No page errors or mobile horizontal overflow were observed in Edge 155.0.4283.45.
- Strict TypeScript/Python checks, Ruff, and the production build are documented in the [startup guide](diagnostic-startup.md). Independent review is recorded in [the review record](issue-1-code-review.md).

## Earlier manual observations

- The user started a Cloudflare Quick Tunnel to the laptop's port 8000. The public application returned HTTP 200 and the backend health endpoint returned `status: ok` when checked by the agent.
- The user confirmed that **Enter VR** worked on the selected Meta Quest 3, before this connection simplification. This is user-reported immersive entry; the new role-button flow still needs a fresh actual-device check.
- A brief tunnel QUIC interruption was followed by reconnection. Application reconnection is manual: press the role button after a dropped socket.
- iPhone participation, physical phone translation, Quest marker movement, exit/re-entry, and actual overlay/held-input behavior remain unrecorded. Simulator controls are now removed.

## Actual device record

“Pending” is not a pass or a measured capability.

| Field | Mobile master | VR solver |
| --- | --- | --- |
| Planned device | iPhone 16 | Meta Quest 3 |
| Planned browser | Chrome on iPhone | Quest WebXR browser; exact version pending |
| Actual OS / browser version | Pending | Pending |
| Date and tester | Pending | 2026-10-12, user-reported earlier VR entry |
| Shared trusted HTTPS URL | Pending | Cloudflare route previously used |
| New direct role connection / peer status | Pending | Pending |
| Immersive entry / exit / re-entry | Phone tracking deferred | Entry confirmed with previous join flow; new flow and exit/re-entry pending |
| Reference space / positional tracking | Phone tracking deferred | Pending |
| DOM overlay / held control events | Not exercised | Pending or unavailable |
| Physically tracked marker delivery | Deferred | Pending |
| Permission denial / recovery | Pending | Pending |
| Saved report | Pending | Pending |

## Test the current first slice

1. Build and serve through trusted HTTPS reachable by both devices using the [startup guide](diagnostic-startup.md). Refresh both pages after updating the app.
2. On iPhone, select **Connect phone** and confirm **Connected · Phone**. Until Quest joins, the status should read **Waiting for VR device**. The page remains usable without WebXR; physical phone movement is still deferred.
3. Open the same URL on Quest, select **Connect VR headset**, and confirm the phone changes to **VR device connected**. Select **Enter VR** on Quest; inspect the neutral grid/axes. Connected status refers to the headset page, not immersive-mode verification.
4. End XR with overlay **End XR**, or controller select when the overlay is unavailable. Enter VR again. Record actual mode, reference space, tracking status, and exit behavior.
5. Select **Disconnect** on Quest. The phone should return to **Waiting for VR device**. Reconnect using **Connect VR headset**. A new tab in that role replaces the earlier connection without a session ID or authentication step.
6. Deny XR permission once where supported. Restore permission and retry; record actual behavior. Open the optional diagnostics and download each device report. If a DOM overlay is available, check **Hold input probe**; otherwise record unavailable.

## Complete physical phone tracking later

The iPhone movement-tracking mechanism remains a separate decision. On a phone/browser with positional WebXR support, the retained AR path can be tested: enter AR, verify non-emulated `tracked` position, translate along each axis, and compare Python-accepted coordinates with the marker in Quest. Check start/end, lost tracking, and recovery. No marker movement is expected from the currently deferred iPhone tracking path.

Desktop message fixtures, connected status, and a rendered page cannot establish phone-to-VR physical translation acceptance.
