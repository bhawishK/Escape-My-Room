# Escape My Room technical ticket breakdown

Approved and published as 17 GitHub issues on 12 October 2026. This replaces the original eight-ticket proposal. Each issue has an end-to-end deliverable, technical approach, acceptance checks, scope boundary, and the ready-for-agent label. GitHub is the implementation tracker, with 21 native blocking relationships. Local ticket files remain source snapshots and earlier drafts remain as drafting history.

## Confirmed scope and proposed technical defaults

WebXR and Python are confirmed. Proposed supporting choices are TypeScript with Three.js for the browser, FastAPI/Pydantic for the Python service, JSON/WebSocket for scene commands/state, and GLB/glTF plus an entity manifest for prepared assets. Pin compatible versions during ticket 01 rather than assuming current library combinations are already tested. These defaults are implementation proposals; they do not settle the interaction contribution or device compatibility. Three.js provides WebXR management and glTF loading, and FastAPI documents WebSocket endpoints. [Three.js documentation](https://threejs.org/docs/), [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)

The browser handles XR input, coordinate conversion, selection feedback, and rendering. Python validates commands and owns accepted object transforms, ownership, room version, and later behavior/visibility state. Reconstruction is a prepared-asset pipeline initially; no Python ML model or all-browser scanning requirement is introduced.

Phone movement uses positional WebXR poses relative to a chosen reference space, converted to room coordinates. DOM overlay controls must be checked on the target device; no support guarantee is assumed. [WebXR Device API](https://immersive-web.github.io/webxr/), [WebXR DOM Overlays Module](https://immersive-web.github.io/dom-overlays/)

## Technical contracts to establish through the slices

| Contract | Initial content | First delivered in |
|---|---|---|
| Session identity | Session, participant, role, connection generation, room version | 01–02 |
| Room entities | Stable ID, transform, bounds/proxy, static/movable flags | 02 |
| Coordinate mapping | Canonical room frame, meters, client XR-to-room transform, alignment validity | 03 |
| Manipulation commands | Acquire, movement, release; object ID, manipulation ID, movement sequence | 06 |
| Accepted object state | Owner, accepted transform, server revision, acknowledgement/rejection | 06–08 |
| Recovery | Tracking/alignment status, ownership expiry/release policy, full accepted snapshot | 10–11 |
| Room-relative placement | Host ID, anchor/region ID, local transform, detach policy | 14 |
| Virtual game content | Role-filtered concealed/revealed state and explicit behavior/completion state | 15–16 |

These contracts are developed alongside usable client behavior, rather than in standalone schema-only tickets. Networking correctness tests use two client connections to the running Python service and observe accepted/client-visible state. Real WebXR tracking, touch/controller input, calibration, and perceived motion also require target-device exercises.

## Approved breakdown

1. **[Connect mobile and VR through Python with a tracked pose](https://github.com/bhawishK/Escape-My-Room/issues/1)**
   - **Blocked by:** None.
   - **What it delivers:** The mobile master and remote VR solver join a WebXR session served by Python; moving the phone moves a diagnostic marker in the VR view. This proves the actual device-to-service-to-headset path before room content is added.

2. **[Load a prepared room and independently selectable objects](https://github.com/bhawishK/Escape-My-Room/issues/2)**
   - **Blocked by:** 01.
   - **What it delivers:** Both participants enter the same recognizable prepared room, with matching furniture identities and one independently movable virtual item.

3. **[Align both WebXR views with the shared room](https://github.com/bhawishK/Escape-My-Room/issues/3)**
   - **Blocked by:** 02.
   - **What it delivers:** Participants calibrate their local XR views so known room locations and virtual content agree across mobile and VR.

4. **[Show each participant's position and orientation](https://github.com/bhawishK/Escape-My-Room/issues/4)**
   - **Blocked by:** 03.
   - **What it delivers:** The master and solver see primitive representations of one another at consistent locations in the room.

5. **[Select the intended room object from mobile](https://github.com/bhawishK/Escape-My-Room/issues/5)**
   - **Blocked by:** 03.
   - **What it delivers:** The master points or taps to select the movable virtual item, sees clear feedback, and receives an understandable result when an object is unavailable.

6. **[Implement hold, phone translation, release, and clutching](https://github.com/bhawishK/Escape-My-Room/issues/6)**
   - **Blocked by:** 05.
   - **What it delivers:** The master moves the selected item with tracked phone translation while holding a control; the VR solver sees the accepted movement, and release leaves the item in place.

7. **[Add solver grab and exclusive control](https://github.com/bhawishK/Escape-My-Room/issues/7)**
   - **Blocked by:** 06.
   - **What it delivers:** The solver grabs, moves, and releases available items while both participants respect exclusive control.

8. **[Reject competing and stale interaction commands](https://github.com/bhawishK/Escape-My-Room/issues/8)**
   - **Blocked by:** 07.
   - **What it delivers:** Both participants get consistent results when they request control together or delayed commands arrive after a release or new acquisition.

9. **[Tune motion delivery and VR display](https://github.com/bhawishK/Escape-My-Room/issues/9)**
   - **Blocked by:** 06.
   - **What it delivers:** The solver sees usable continuous motion while the master manipulates an item, with a correct final placement even under imperfect network timing.

10. **[Stop manipulation when tracking or room alignment becomes invalid](https://github.com/bhawishK/Escape-My-Room/issues/10)**
   - **Blocked by:** 06.
   - **What it delivers:** The master receives clear feedback on tracking loss or a reference-space reset and resumes only after valid tracking/alignment, without jumping the object.

11. **[Restore shared state after disconnect and rejoin](https://github.com/bhawishK/Escape-My-Room/issues/11)**
   - **Blocked by:** 08.
   - **What it delivers:** A disconnected participant rejoins the existing room state, and an abandoned object becomes usable under a defined recovery policy.

12. **[Measure placement and refine the motion mapping](https://github.com/bhawishK/Escape-My-Room/issues/12)**
   - **Blocked by:** 07, 09.
   - **What it delivers:** Participants perform repeatable desk, cabinet, and floor placement tasks, producing evidence to tune the mapping and select the next interaction extension.

13. **[Add two-way voice to the session](https://github.com/bhawishK/Escape-My-Room/issues/13)**
   - **Blocked by:** 01.
   - **What it delivers:** The master and solver talk while using their WebXR views.

14. **[Place virtual content relative to a room object](https://github.com/bhawishK/Escape-My-Room/issues/14)**
   - **Blocked by:** 12.
   - **What it delivers:** The master places content relative to recognizable furniture, and both participants observe the same room-object relationship.

15. **[Prepare hidden content and deliberately reveal it](https://github.com/bhawishK/Escape-My-Room/issues/15)**
   - **Blocked by:** 14.
   - **What it delivers:** The master privately prepares one virtual game item associated with a room object and can deliberately make it available to the solver.

16. **[Let the solver complete one authored room-object task](https://github.com/bhawishK/Escape-My-Room/issues/16)**
   - **Blocked by:** 15.
   - **What it delivers:** The solver uses the chosen simple virtual behavior to retrieve/interact with the prepared item and reaches a shared, clear puzzle outcome while the master remains able to participate.

17. **[Verify and document the integrated prototype](https://github.com/bhawishK/Escape-My-Room/issues/17)**
   - **Blocked by:** 04, 10, 11, 13, 16.
   - **What it delivers:** Run a repeatable mobile-master/remote-VR demo on actual devices with room alignment, presence, voice, manipulation, recovery, and the selected small room-object scenario.

## Milestones and parallel work

- Device path: 01 proves real phone-to-Python-to-headset tracking before room work.
- Basic shared interaction: 02, 03, 05, 06, and 07 establish the room, alignment, selection, phone manipulation, and solver control.
- Robustness and usability: 08, 09, 10, 11, and 12 address stale commands, visible motion, tracking loss, reconnects, and the placement pilot.
- Application demonstration: 14, 15, and 16 add one room-relative placement and one small authored task informed by the pilot.
- Presence (04) and voice (13) can proceed once their respective prerequisites are complete; neither gates the first manipulation experiment.
- Integration: 17 verifies the complete prototype after its direct prerequisites. Transitive prerequisites are not repeated as extra blocking edges.

Tickets 14–16 retain concrete proposed defaults while leaving the exact assisted-placement/virtual behavior choice to the pilot. They do not commit the project to physical drawer synchronization, inferred interiors, selective reconstruction, or a large puzzle game. Ticket 12 yields the input needed to finish those choices.

## Review and publication

The user approved the revision and requested GitHub issues on 12 October 2026. Issues #1–#17 are published with the ready-for-agent label; all 21 native blocked-by relationships and the approved acceptance criteria were verified. Local files under .scratch/escape-my-room/issues remain source snapshots and link to the corresponding issues.

GitHub issues are the selected tracker. Ready-for-agent means an issue is specified for implementation; its blocking edges must still be satisfied before work starts. Issue #1 is the only initially unblocked issue. Once it is complete, issues #2 and #13 become available. Implementation has not started.
