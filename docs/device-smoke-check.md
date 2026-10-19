# Issue #1: device smoke-check record

Status: **connection prototype accepted by the user for Issue #1 closure; iPhone Chrome role/shared state recorded and VR side user-confirmed**.

Closure decision on 12 October 2026: the user confirmed that the VR side works and approved closing the ticket without a Quest report now. Quest versions, detailed exit/re-entry observations, and permission-recovery results were not supplied. They remain unrecorded evidence, not measured passes or blockers to the user's acceptance. The observations below preserve that distinction. Physical phone tracking remains separate work in Issue #19; closing the issue does not merge PR #18.

Targets are iPhone 16 Chrome for the mobile master and Meta Quest 3 for immersive VR. The user approved: “Build the iPhone page first; add movement tracking later.” On 12 October 2026, the user also requested removing the simulator and session IDs/authentication in favor of a simple VR connected status. This supersedes the original session-enrollment design. [Issue #1](https://github.com/bhawishK/Escape-My-Room/issues/1) covers connection status and Quest entry/exit; deferred physical phone tracking and its tracking-mode lifecycle now belong to [Issue #19](https://github.com/bhawishK/Escape-My-Room/issues/19). Tracking no longer blocks completion of Issue #1.

## Current software evidence

Automated on Windows, 2026-10-12:

- **12 real Python WebSocket integration checks passed:** direct phone/VR connection, accepted shared pose, phone-only publication, stale sequence rejection, invalid/simulated input rejection, malformed/binary frame recovery, phone disconnect/reconnect, and replacement of a VR tab without incorrectly clearing its connection status.
- **4 Playwright browser checks passed:** phone sees VR join/disconnect without session fields or simulator; mobile-sized page works with XR unavailable; VR permission denial leaves the connection usable; a failed initial socket retries with one role button.
- The permission and unavailable-XR checks use browser API overrides. They are desktop Microsoft Edge checks, not iPhone or headset emulation. Generated test messages are protocol fixtures, not physical tracking evidence.
- Visual inspection of the live preview: desktop at 1440 pixels and mobile at 390 pixels show the new role buttons and VR connected status. No page errors or mobile horizontal overflow were observed in Edge 155.0.4283.45.
- Strict TypeScript/Python checks and Ruff passed; the production build succeeded. Vite reports its chunk-size warning for the approximately 544 kB Three.js bundle (136 kB compressed). Commands are in the [startup guide](diagnostic-startup.md). Independent review found no actionable defects in this simplification; see [the review record](issue-1-code-review.md).

## Earlier manual observations

- The user started a Cloudflare Quick Tunnel to the laptop's port 8000. The public application returned HTTP 200 and the backend health endpoint returned `status: ok` when checked by the agent.
- The user confirmed that **Enter VR** worked on the selected Meta Quest 3, before this connection simplification. This is user-reported immersive entry; the new role-button flow still needs a fresh actual-device check.
- A brief tunnel QUIC interruption was followed by reconnection. Application reconnection is manual: press the role button after a dropped socket.
- After the simplification, the local preview was restarted successfully. The earlier temporary tunnel hostname no longer resolved and no cloudflared process was running; start a new tunnel before another Quest test.
- iPhone participation, physical phone translation, Quest marker movement, exit/re-entry, and actual overlay/held-input behavior remain unrecorded. Simulator controls are now removed.

## Latest user-provided observations on 2026-10-12

- The user reported being able to join from Meta Quest and see the grid with the current prototype. This confirms joining/grid visibility; the message does not separately establish exit/re-entry or permission recovery. Earlier immersive entry was already user-confirmed.
- The [iPhone report](device-reports/2026-10-12-iphone.json), captured at `2026-10-12T11:56:26.291Z`, records a secure context and no exposed WebXR API. No XR mode, reference space, position, or held-control events were recorded. This is consistent with the approved phone-page-first scope; it is not a phone-tracking failure for Issue #1.
- The report's user-agent identifies an iPhone, reports iOS `18_7`, and identifies Safari with `Version/26.6.1`; it does not identify the planned Chrome browser. These are reported user-agent values, not independently checked settings/version information. The exact phone model is not present in the report.
- `role: null` records no selected role, and `marker: null` records no accepted marker snapshot. This report does not establish a successful mobile-role connection or the phone's VR status display. Capture another report after **Connect phone** to record the joined role.
- Quest OS/browser versions and its own diagnostic report remain pending. Do not mark the combined exit/re-entry or complete device-record criteria passed from these observations alone.

Follow-up iPhone Chrome report at `2026-10-12T12:01:53.005Z`:

- The [joined-role report](device-reports/2026-10-12-iphone-chrome-connected.json) records `role: mobile_master` and a non-null marker snapshot. It establishes the selected mobile role and receipt of shared state, resolving the earlier report's missing-role evidence. The report does not include current socket status or the VR connected boolean, so it cannot independently establish those live status observations.
- Its user-agent reports iOS `26_6_1` and `CriOS/155.0.8059.37`, identifying the planned Chrome browser. The trailing `Safari/604.1` token does not change that Chrome identifier. Use these as reported version values; exact model and settings confirmation are separate.
- A secure context is confirmed; WebXR remains unavailable. The marker is `inactive` with null position/reference space, as expected while physical phone tracking is deferred. No mobile XR or held-overlay test occurred; Issue #19 owns physical tracking.
- The earlier Safari-like report remains preserved as a separate observation. This newer Chrome report is the current mobile record. Quest versions, exit/re-entry, and permission recovery remain pending.

## Actual device record

“Pending” is not a pass or a measured capability.

| Field | Mobile master | VR solver |
| --- | --- | --- |
| Planned device | iPhone 16 | Meta Quest 3 |
| Planned browser | Chrome on iPhone | Quest WebXR browser; exact version pending |
| Actual OS / browser version | Latest UA reports iOS 26_6_1, Chrome 155.0.8059.37; settings confirmation pending | Pending |
| Date and tester | 2026-10-12, user-provided Chrome report at 12:01:53 UTC | 2026-10-12, user-reported join/grid and earlier VR entry |
| Shared trusted HTTPS URL | Secure context confirmed; exact URL absent from report | Cloudflare route previously used |
| New direct role connection / peer status | Mobile-master role and received shared marker snapshot recorded; live VR-status observation not in report | Join and grid visibility confirmed; full peer-status observations pending |
| Immersive entry / exit / re-entry | Phone tracking deferred | Earlier entry confirmed; current join/grid confirmed; exit/re-entry pending |
| Reference space / positional tracking | Phone tracking deferred | Pending |
| DOM overlay / held control events | Not exercised | Pending or unavailable |
| Physically tracked marker delivery | Deferred | Pending |
| Permission denial / recovery | No XR API or mode exercised; tracking permission work deferred | Pending |
| Saved report | [Latest Chrome/mobile role JSON](device-reports/2026-10-12-iphone-chrome-connected.json); [earlier report](device-reports/2026-10-12-iphone.json) preserved | Pending |

## Test the current first slice

1. Build and serve through trusted HTTPS reachable by both devices using the [startup guide](diagnostic-startup.md). Refresh both pages after updating the app.
2. On iPhone, select **Connect phone** and confirm **Connected · Phone**. Until Quest joins, the status should read **Waiting for VR device**. The page remains usable without WebXR; physical phone movement is still deferred.
3. Open the same URL on Quest, select **Connect VR headset**, and confirm the phone changes to **VR device connected**. Select **Enter VR** on Quest; inspect the neutral grid/axes. Connected status refers to the headset page, not immersive-mode verification.
4. End XR with overlay **End XR**, or controller select when the overlay is unavailable. Enter VR again. Record actual mode, reference space, tracking status, and exit behavior.
5. Select **Disconnect** on Quest. The phone should return to **Waiting for VR device**. Reconnect using **Connect VR headset**. A new tab in that role replaces the earlier connection without a session ID or authentication step.
6. Deny XR permission once where supported. Restore permission and retry; record actual behavior. Open the optional diagnostics and download each device report. If a DOM overlay is available, check **Hold input probe**; otherwise record unavailable.

## Complete physical phone tracking later

These checks are acceptance work for [Issue #19](https://github.com/bhawishK/Escape-My-Room/issues/19), separate from Issue #1's connection checks.

The iPhone tracking decision is in [phone-tracking.md](phone-tracking.md). A position counts only when immersive AR reports a non-emulated `local` or `local-floor` pose. iPhone Chrome has no WebXR API, so no marker movement is expected there. On a phone browser with positional WebXR, enter AR, verify `tracked`, translate along each axis, and compare the Python-accepted coordinates with the marker in Quest. Check start, end, lost tracking, and recovery.

Desktop message fixtures, connected status, and a rendered page cannot establish phone-to-VR physical translation acceptance.
