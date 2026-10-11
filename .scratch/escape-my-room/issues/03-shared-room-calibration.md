# 03: Align both WebXR views with the shared room

**What to build:** Participants calibrate their local XR views so known room locations and virtual content agree across mobile and VR.

**Blocked by:** 02 — Load a prepared room and independently selectable objects

**Status:** ready-for-agent

## Proposed technical approach

- Keep a canonical room coordinate frame and one transform between each client's XR reference space and that room. Define the transform direction explicitly and apply it to poses and displayed content.
- Propose a manual calibration using a known room point and heading; add a scale check against a known distance from the prepared room. Hit-test or anchors may assist if available but are not prerequisites.
- Persist the accepted room alignment for the current participant/session, and show an alignment status. Do not assume two independent XR sessions share an origin.
- The remote solver chooses a suitable local VR origin for viewing the room; their physical surroundings are not expected to match the master's room.

## Acceptance criteria

- [ ] Calibrate without hard-coding one developer device's initial XR origin.
- [ ] Both clients agree on several known room-space points; document the measured disagreement and scale check.
- [ ] Phone movement converted into room coordinates follows the intended room axes after calibration.
- [ ] A repeat calibration produces consistent content locations and a visible status update.
- [ ] Document initial reference-space choices and what will invalidate calibration; full reset recovery is addressed in ticket 10.
- [ ] Verify coordinate conversion with known poses and a connected-device landmark check.

## Scope boundary

Initial alignment only. Automatic shared-anchor discovery and localization infrastructure are outside scope.
