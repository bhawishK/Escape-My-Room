# Escape My Room interaction prototype

Updated 12 October 2026 to reflect the latest scope and theme discussion. This specifies the first working prototype; the mobile-master and VR interaction with room objects will continue to develop through implementation and testing.

## Problem Statement

A mobile game master in a physical room and a remote VR solver need to interact with virtual content associated with recognizable personal objects. Their devices offer different viewpoints and input capabilities. The project needs a working prototype that makes a specific shared spatial interaction concrete enough to test and develop into a potential 3DUI contest contribution.

The current candidate is physical phone movement controlling a selected virtual object's movement. Reconstruction supplies the shared spatial setting and recognizable objects. The prototype should reveal how the mobile master and VR solver can interact effectively with shared room content despite their different devices and viewpoints. The exact interaction technique remains under development.

## Solution

Build a minimal connected mobile and VR experience in a reconstructed room. As the starting interaction candidate, the mobile master selects a virtual object, holds a control to engage manipulation, moves the phone to move the object, and releases the control to place it. The master retains authority during manipulation. The VR solver sees the resulting shared state and can explore and interact with placed content under the ownership rules below. Testing can refine or extend the input and placement technique.

Use a room with a recognizable desk or cabinet and one movable virtual object for the first experiment. Test movement around furniture and placement on the desk, beside the cabinet, and on the floor. Tune the movement mapping through testing before expanding the technique or fitting it into a puzzle.

The escape-room setting remains secondary. The master can prepare hidden items, communicate by voice, and choose what assistance to provide. Live manipulation need not be justified as clue delivery or moving previously hidden keys in this first prototype.

### Theme alignment and priorities

The proposal fits the contest's shared spatial interaction theme: a mobile participant and a remote VR participant use different inputs and viewpoints to act around the same room content. Its components have different roles in the demonstration:

- Primary contribution: the mobile-master and VR interaction with shared objects, including selection, manipulation, placement, control awareness, and the solver's response.
- Supporting capabilities: recognizable room reconstruction, simple object behavior and authoring, primitive participant presence, and human voice communication.
- Application context: a small escape-room scenario using personal objects. Extensive puzzles, timers, traps, narrative, and detailed avatars are optional expansion work.
- Implementation approach: WebXR browser clients and Python services are the chosen stack. Browser delivery supports access across devices; its use alone does not establish an interaction contribution.

All these parts can support the theme, but the first build should concentrate effort on a clear shared interaction. Reconstruction needs sufficient quality for recognition and usable spatial relationships; photorealism or a new AI reconstruction model is not a prerequisite for the initial experiment.

The contest still requires interaction innovation and asks entrants to identify techniques they create, adapt, or extend. Use the known phone-motion technique as a starting point, then develop and explain the project's interaction contribution through focused iteration. An exhaustive search for an unprecedented end-to-end system is not a prerequisite for building the prototype. [Official contest requirements](https://ieeevr.org/2027/contribute/3dui-contest/)

## User Stories

1. As a mobile master, I want to participate from the physical room, so that I can use its layout and personal objects as spatial references.
2. As a VR solver, I want to enter the corresponding virtual room, so that I can explore the same spatial setting remotely.
3. As a participant, I want recognizable personal objects in the shared scene, so that the experience feels connected to the master's room.
4. As a mobile master, I want to select a virtual object, so that my movement affects the intended item.
5. As a mobile master, I want clear selection feedback, so that I know which object I will manipulate.
6. As a mobile master, I want to hold a control to engage manipulation, so that ordinary phone movement does not accidentally move content.
7. As a mobile master, I want phone movement to move the selected object, so that I can manipulate shared 3D content through physical motion.
8. As a mobile master, I want releasing the control to finish placement, so that I can deliberately commit the object's position.
9. As a mobile master, I want the object to remain in place while manipulation is disengaged, so that I can reposition my phone independently.
10. As a mobile master, I want a new hold to resume from the object's current position, so that repositioning the phone does not cause an object jump.
11. As a mobile master, I want control over the object throughout active manipulation, so that another participant cannot unexpectedly take it away.
12. As a VR solver, I want the scene to reflect the master's object movement, so that I can perceive changes to shared spatial content.
13. As a VR solver, I want to understand when an object is controlled by the master, so that my attempted interactions have predictable outcomes.
14. As a VR solver, I want to interact with released objects, so that the shared scene supports exploration and eventual puzzle solving.
15. As a VR solver holding an object, I want my control respected, so that the master cannot unexpectedly move it without release or an accepted transfer.
16. As a mobile master, I want to assign simple virtual behaviors to reconstructed personal objects, so that a recognizable cabinet can act as a game container.
17. As a mobile master, I want object-relative placement such as inside a cabinet or on a desk, so that personal objects can host virtual game content.
18. As a mobile master, I want preparation controls and hidden content kept private, so that the solver does not learn the puzzle solution from my interface.
19. As a mobile master, I want to deliberately reveal assistance, so that I can choose how to guide the solver.
20. As a participant, I want a visible representation of the other participant, so that I can perceive their presence in the shared room.
21. As a participant, I want human-to-human voice communication, so that we can talk naturally during play.
22. As a mobile master, I want to act on shared virtual room objects during the session, so that I can participate beyond initial scene preparation.
23. As a prototype evaluator, I want repeatable manipulation tasks, so that I can identify mapping and coordination problems.
24. As a prototype developer, I want adjustable movement parameters, so that testing can guide subsequent technique development.

## Implementation Decisions

### Confirmed behavior

- The prototype has an asymmetric mobile master and remote VR solver. The master stays in the scanned physical room.
- The implementation will use WebXR and Python. WebXR runs in the browser clients; Python provides shared session services and can host reconstruction processing when needed. The browser rendering library, transport, and reconstruction tools remain to be selected.
- The master needs interaction with shared room content during the session, beyond initial scene preparation. The precise mobile-master and VR object interactions will be developed further.
- The agreed starting candidate uses physical phone movement to manipulate a selected virtual object, with hold to engage and release to place. Selection, active manipulation, and released placement are distinct interaction states. This candidate is a basis for testing, not the finalized contest technique.
- Movement mapping starts with an initial default and is refined through testing. No exact gain, reference frame, or numerical tuning values have been approved.
- The master keeps control during active manipulation; grabbing by the solver does not automatically transfer control.
- An object already held by the solver remains under solver control until release or an explicitly accepted transfer. The interaction for requesting such a transfer remains open.
- Simple virtual behaviors assigned to reconstructed objects remain a project direction. Which behavior belongs in the first build is still open. Geometry reconstruction does not by itself establish containers, interiors, or articulation.
- Object-relative placement is supported as a design direction. Its relationship to continuous phone movement still needs to be specified.
- Presence may use a primitive representation. Private controls and hidden content remain concealed; deliberately issued assistance can be shared.
- Voice communication is between people. Speech recognition and voice-command interpretation are not part of the agreed technique.
- Physical-action detection and synchronization are excluded from this prototype. The specification does not prescribe how physical drawer actions would affect the virtual scene.

### Proposed implementation boundaries

There is no application code, domain glossary, ADR, or existing test framework in the inspected workspace. These responsibilities are proposed boundaries, not existing modules or approved technology choices:

- Shared scene content: reconstructed geometry, object identity, transforms, and manually assigned virtual behaviors.
- Mobile manipulation: selection, hold/release input, tracked phone motion, and movement mapping.
- Shared session state: synchronized object state, manipulation authority, and participant presence.
- VR interaction: scene display, observation of master-controlled content, and interaction with available objects.

Object identity, transforms, ownership, and visibility must have consistent meaning across both clients. Transport, browser rendering library, tracking APIs, Python framework, and data schema are still to be chosen.

### Chosen WebXR and Python approach

Use WebXR for the mobile and VR clients, connected through Python shared session services. Browser-side code will drive WebXR input and rendering. Confirm support for the actual phone and headset, positional tracking, room alignment, and the required inputs in the first working slice. WebXR and Python are selected; the exact devices and supporting libraries remain open.

Treat room capture, reconstruction, and object preparation as a separate pipeline initially; do not assume WebXR supplies these capabilities. That pipeline may use existing tools or processing outside the browser. The first interaction test can load prepared reconstructed assets. An entirely browser-based capture-to-play workflow is not a first-build requirement.

### Proposed defaults for the first build

- Use prepared reconstructed content to isolate interaction testing; automatic end-to-end reconstruction is a later integration step. Recognizable personal objects and usable geometry are the initial reconstruction goals; further fidelity improvements should support interaction needs.
- Begin with translation, one selectable movable object, and a single manipulation at a time. Rotation and larger object sets require later decisions.
- Record the phone and object positions when a hold begins, then apply relative phone displacement. Re-engagement must preserve the current object position.
- Evaluate room-coordinate movement as the initial mapping candidate. It is not a settled requirement.
- Prevent solver manipulation of an actively master-controlled object. After release, allow normal solver interaction, subject to any hidden-content rules.
- For the visible manipulation experiment, use a non-hidden object. Solver observation of that object does not authorize exposing hidden puzzle content or the master's private operations.

### Decisions still required before implementation

- Target phone and VR hardware, browser rendering library, Python framework, and available positional tracking within the chosen WebXR and Python stack.
- Shared room alignment and calibration between physical and virtual views.
- Object selection method and hold-control input.
- Initial movement coordinate frame and gain.
- Placement semantics: whether release fixes the position, enables gravity, or snaps to a surface. Releasing to place does not yet imply a physics-based drop.
- Collision and invalid-placement behavior, including access to a virtual container's interior.
- How tracking loss, disconnects, and conflicting acquisition requests preserve a consistent object state.
- Minimal virtual behavior needed for the first object-relative demonstration.

### Build sequence and scope boundary

1. Establish one mobile-master and one remote-VR session with a prepared room, stable object identity, shared transforms, and basic participant presence.
2. Implement the selection–hold–phone movement–release candidate and the agreed control rules. Run the connected interaction tests before adding game mechanics.
3. Test placement around room objects and develop the mobile-master and VR interaction based on what participants find difficult or useful. Choose one simple virtual behavior or assisted-placement feature only when it makes this interaction clearer.
4. Add a small escape-room demonstration using that interaction, with voice communication and appropriate hidden-content handling. Expand reconstruction or game features when they improve the demonstration.

The initial candidate experiment and the later contest demonstration are separate milestones. Completing the candidate experiment provides evidence for the next interaction design; it does not finalize the contribution.

## Testing Decisions

The user confirmed one primary test boundary: the complete connected mobile-to-VR interaction, covering selection, hold, phone movement, release, and ownership. Prefer tests through this boundary rather than tests of internal implementation structure.

- Test the integrated mobile manipulation, shared session state, and VR interaction responsibilities by observing client-visible selection, object position, and control authority.
- Verify that an unselected or disengaged object does not move when the phone moves.
- Verify that an active hold moves the intended object according to the configured mapping and that the VR client reflects the change.
- Verify that release ends manipulation and that repositioning the phone afterward does not move the object.
- Verify that re-engagement does not cause an object jump.
- Verify that the solver cannot take an actively master-controlled object and that the master cannot silently move a solver-held object.
- Verify that a released available object can be interacted with by the solver.
- Verify hidden content and private controls from the solver's view, separately from the visible-object manipulation experiment.
- Include the agreed failure behavior for tracking loss and disconnection once those policies are selected.
- Run manual tasks for desk, cabinet, and floor placement. Record placement error, completion time, unintended motion, repeated holds, and participant observations. Set acceptance thresholds after an initial baseline rather than inventing them now.
- Check that presence is perceivable and voice communication works during the shared interaction.
- A good test checks externally observable behavior and catches a meaningful failure. It does not mirror the movement implementation or assert internal helper calls.
- No existing tests or prior test patterns were found in the workspace. Framework selection remains open.

The first experiment is complete when both clients can perform the full selection-to-release sequence, ownership is consistent, repeated engagement preserves position, and the three placement tasks have documented observations. This establishes prototype behavior, not usability superiority or novelty.

## Out of Scope

- A complete escape-room game, puzzle library, or general room-authoring platform.
- Proving that mobile placement is easier than VR placement; its ease is an accepted project premise.
- Mandatory clue-delivery mechanics or compulsory live movement of hidden keys.
- Solver takeover of an actively master-controlled object or a cross-device handoff demonstration.
- Precision levels for hints and previews from the solver's viewpoint.
- Automatic speech interpretation.
- Front-camera gesture recognition as a committed input method.
- The phone-as-flashlight alternative.
- Physical furniture actuation or synchronization of physical door states.
- Detection of physical actions such as opening a drawer and mirroring them in VR.
- Automatic inference of every object's interior, mechanics, and game behavior.
- Developing or training a new reconstruction model within the first manipulation experiment.
- Selection-driven partial reconstruction, object rescanning, or local geometry refinement as committed features. These were explored during research and have not been adopted as prototype requirements.
- Requiring the complete capture, reconstruction, authoring, and play pipeline to run inside a browser.
- Photorealistic reconstruction, elaborate avatars, timers, traps, and extensive puzzle content as first-build requirements.
- Rotation, complex multiplayer scaling, production hosting, and a final contest submission in this initial spec.

## Further Notes

The specification synthesizes the proposal and the subsequent confirmed decisions. It gives later decisions priority where the conversation changed direction: the solver does not take control during the master's manipulation, and the first test therefore excludes the previously suggested handoff.

The related-work review has identified close precedents for hold–phone movement–release manipulation and for asymmetric mobile–VR collaboration, including systems with browser-based scene manipulation. These findings establish useful starting points, not a reason to abandon the proposal. Describe existing techniques accurately and avoid claiming the basic mechanism or browser delivery as new. See the companion related-research report for sources and evidence limits.

Keep subsequent research proportional to the contest prototype. Build and test the shared interaction, then use focused comparisons to explain what was adapted or extended. Testing should identify which aspect warrants development; adding features alone does not establish an interaction contribution.

The reconstructed room, recognizable personal objects, asymmetric views, and authoritative master role provide the context for the candidate contribution. The project must ultimately explain how its technique supports shared spatial interaction across those differences.

The user approved the 17-ticket technical breakdown and selected local publication on 12 October 2026. The implementation tickets are published under `.scratch/escape-my-room/issues`, each with status `ready-for-agent` and explicit blocking edges. The companion ticket-breakdown document links to the published files. WebXR and Python are confirmed; remaining implementation defaults and pilot-dependent interaction decisions are identified in the tickets. No implementation has started.
