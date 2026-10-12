# Escape My Room

A shared spatial interaction prototype for the IEEE VR 3DUI Contest. A mobile master participates from a recognizable reconstructed room while a remote VR solver explores and interacts with its virtual content.

The chosen stack is **WebXR browser clients and Python services**. The starting interaction candidate uses selection, hold, phone translation, and release to manipulate virtual objects. The technique will develop through connected-device testing; the escape-room scenario provides its application context.

## Project documents

- [Prototype specification](<Escape My Room Prototype Spec.md>) — agreed scope, interaction candidate, open implementation decisions, and testing boundary.
- [Approved ticket breakdown](<Escape My Room Ticket Breakdown.md>) — milestones and dependencies for the 17 implementation tickets.
- [Related research](<Escape My Room Related Research.md>) — primary-source findings and limits of the related-work review.
- [Original proposal](<Escape My Room.docx>) — source proposal; later decisions in the specification and approved tickets take precedence.

## Implementation issues

The [17 GitHub issues](https://github.com/bhawishK/Escape-My-Room/issues) are the implementation tracker. Each preserves the approved technical approach, acceptance criteria, and scope boundary, and has the `ready-for-agent` label. Native blocked-by relationships record dependencies; an issue can start only when its blockers are complete.

Start with [Issue #1: Connect mobile and VR through Python with a tracked pose](https://github.com/bhawishK/Escape-My-Room/issues/1). Once it is complete, [room loading (#2)](https://github.com/bhawishK/Escape-My-Room/issues/2) and [voice communication (#13)](https://github.com/bhawishK/Escape-My-Room/issues/13) become available.

The [local ticket files](.scratch/escape-my-room/issues/) remain source snapshots and link to their corresponding GitHub issues. Use GitHub for ongoing issue status and dependency tracking.

## Current state

Issue #1 now has a Python service and a responsive browser diagnostic. Open the same URL on both devices, choose **Connect phone** on the phone and **Connect VR headset** on Quest, then **Enter VR**. The phone shows **VR device connected** when the headset page joins. One shared room replaces session IDs, invite links, and authentication. The simulator and manual coordinate controls have been removed.

The agreed first target is **iPhone 16 Chrome for the mobile page and Meta Quest 3 for immersive VR**. The user chose to build the iPhone page first and add movement tracking later. Quest VR entry has been confirmed by the user through the HTTPS tunnel. The remaining iPhone/Quest smoke checks and the original phone-translation acceptance criterion are pending; Issue #1 is not yet complete on hardware.

- [Start the diagnostic](docs/diagnostic-startup.md) — installation, HTTPS/WSS, and checks.
- [Connection and pose contract](docs/diagnostic-protocol.md) — shared device status, validation, and marker coordinates.
- [Device smoke-check record](docs/device-smoke-check.md) — approved scope adjustment, evidence, and remaining manual checks.
