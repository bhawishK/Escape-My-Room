# Escape My Room

A shared spatial interaction prototype for the IEEE VR 3DUI Contest. A mobile master participates from a recognizable reconstructed room while a remote VR solver explores and interacts with its virtual content.

The chosen stack is **browser clients and Python services**. The Quest uses WebXR. iPhone browsers expose no WebXR, so since 19 October 2026 the phone is an ordinary web page that turns its room view with the phone's orientation sensor. How to measure the phone's position is open. The starting interaction candidate uses selection, hold, phone translation, and release to manipulate virtual objects. The technique will develop through connected-device testing; the escape-room scenario provides its application context.

## Project documents

- [Prototype specification](<Escape My Room Prototype Spec.md>) — agreed scope, interaction candidate, open implementation decisions, and testing boundary.
- [Approved ticket breakdown](<Escape My Room Ticket Breakdown.md>) — milestones and dependencies for the 17 implementation tickets.
- [Related research](<Escape My Room Related Research.md>) — primary-source findings and limits of the related-work review.
- [Original proposal](<Escape My Room.docx>) — source proposal; later decisions in the specification and approved tickets take precedence.

## Implementation issues

The [GitHub issues](https://github.com/bhawishK/Escape-My-Room/issues) are the implementation tracker. The original 17 issues preserve the approved technical approach, acceptance criteria, and scope boundary, and have the `ready-for-agent` label. Issue #19 separately tracks physical phone movement. Native blocked-by relationships record dependencies; an issue can start only when its blockers are complete.

Start with [Issue #1: Connect phone and VR through Python with device status](https://github.com/bhawishK/Escape-My-Room/issues/1). Once it is complete, [room loading (#2)](https://github.com/bhawishK/Escape-My-Room/issues/2) and [voice communication (#13)](https://github.com/bhawishK/Escape-My-Room/issues/13) become available. Physical phone movement is tracked separately in [Issue #19](https://github.com/bhawishK/Escape-My-Room/issues/19); tracking-dependent alignment, presence, and manipulation work need that capability.

The [local ticket files](.scratch/escape-my-room/issues/) remain source snapshots and link to their corresponding GitHub issues. Use GitHub for ongoing issue status and dependency tracking.

## Current state

Issue #1 now has a Python service and a responsive browser diagnostic. Open the same URL on both devices, choose **Connect phone** on the phone and **Connect VR headset** on Quest, then **Enter VR**. The phone shows **VR device connected** when the headset page joins. One shared room replaces session IDs, invite links, and authentication. The simulator and manual coordinate controls have been removed. Issue #2 adds the prepared stand-in room: both devices load room version 1, with a fixed floor, desk, and cabinet, and one separate movable box. The room decision and asset procedure are in [the prepared room note](docs/prepared-room.md). Issue #23 extends that contract for AI-generated rooms: a second manifest form gives each entity its own GLB and rotation and allows several movable entities. A deterministic table, mug and book fixture exercises it, and the stand-in room is still served by default. Issue #24 adds a **Room photos** page (`/photos.html`, linked from the top of the page): the phone takes photos with its camera or picks existing ones, adds instructions, marks an overview, and saves them as one capture that survives reloads and restarts. See [room photo captures](docs/room-photos.md). Issue #25 keeps the phone's native camera picker for capture; its real iPhone Chrome check is recorded in [the capture record](docs/iphone-capture-check.md). Issue #26 adds **Prepare room**: a saved capture starts a background preparation job that reports each stage and ends with a candidate room for review, without changing the active room. Only a labelled fixture worker exists so far; see [room preparation jobs](docs/room-preparation.md). Issue #19 opens the room full screen on the phone, and the view turns as the phone turns; this works on the iPhone. Walking moves the view a step at a time from the accelerometer, roughly, and the headset sees the estimated position. Both start with **Connect phone**, without buttons. Camera tracking against a printed tag was tried and dropped as too fiddly, so the phone has no measured position yet. See [phone view and tracking](docs/phone-tracking.md). Issue #5 lets the phone select the movable box by tapping it in the room view; Python checks the request and answers the phone alone, so the headset never learns the selection. See [selecting an object](docs/diagnostic-protocol.md#select-an-object). Issue #6 places the selected box by aiming: press and hold it, and it goes where the centre of the screen meets the floor. Turn and tilt the phone to move it, then let go to drop it there. Python places it and shows the hold to the headset. See [picking up and aiming an object](docs/diagnostic-protocol.md#pick-up-aim-and-drop-an-object). Issue #9 keeps that motion flowing on a slow network:

- **No backlog:** each device is sent only the newest state, so nothing queues up during a long hold.
- **Headset:** the held object glides between updates and lands exactly on the final placement.
- **Testing and measurement:** a setting adds network delay for testing, and each page records rates, round trips and corrections.

See [motion delivery](docs/diagnostic-protocol.md#motion-delivery).

The agreed first target is **iPhone 16 Chrome for the mobile page and Meta Quest 3 for immersive VR**. The user chose to build the iPhone page first and add movement tracking later; Issue #19 has added turning, and position tracking is still to be chosen. The user confirmed the VR side works and accepted Issue #1 for closure without a Quest report. The iPhone Chrome report records the mobile-master role and shared state; Quest versions and detailed lifecycle/permission observations remain unrecorded. Physical phone translation is pending in Issue #19.

- [Start the diagnostic](docs/diagnostic-startup.md) — installation, HTTPS/WSS, and checks.
- [Connection and pose contract](docs/diagnostic-protocol.md) — shared device status, validation, and the phone's pose message.
- [Phone view and tracking](docs/phone-tracking.md) — the room view, turning, the dropped printed-tag attempt, and the options for position.
- [Gaze cursor spike](docs/gaze-cursor.md) — pointing at room objects with the eyes or head through the front camera, and how to measure its accuracy on the phone.
- [Floor height test](docs/floor-height.md) — estimating the phone's height above the floor from the back camera with an AI depth model (#49), its results so far, and the device check.
- [Device smoke-check record](docs/device-smoke-check.md) — approved scope adjustment, evidence, and remaining manual checks.
