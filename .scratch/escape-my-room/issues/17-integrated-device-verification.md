# 17: Verify and document the integrated prototype

**What to build:** Run a repeatable mobile-master/remote-VR demo on actual devices with room alignment, presence, voice, manipulation, recovery, and the selected small room-object scenario.

**Blocked by:** 04 — Show each participant's position and orientation; 10 — Stop manipulation when tracking or room alignment becomes invalid; 11 — Restore shared state after disconnect and rejoin; 13 — Add two-way voice to the session; 16 — Let the solver complete one authored room-object task

**Status:** ready-for-agent

**GitHub issue:** [#17](https://github.com/bhawishK/Escape-My-Room/issues/17)

## Proposed technical approach

- Provide one startup/deployment procedure for the WebXR browser assets and Python service, including HTTPS/WSS, session configuration, prepared assets, and audio connectivity.
- Run the approved connected interaction test boundary against the integrated build. Include device exercises for XR/input behavior that simulated clients cannot establish.
- Record the exact room version, device/browser versions, mapping, publication/interpolation settings, calibration procedure, and selected recovery policies.
- Describe the implemented interaction as reused, adapted, or extended based on the work and evidence, without presenting WebXR delivery as novelty.

## Acceptance criteria

- [ ] A fresh session can be started, joined, calibrated, and played using the documented procedure.
- [ ] Actual-device demo covers primitive presence, voice, live master manipulation, solver action, and the selected task outcome.
- [ ] Selection, hold, movement, release, clutching, ownership, ordering, visibility, and recovery checks pass or material blockers are explicitly reported.
- [ ] Pilot findings, device limitations, and remaining contribution-development work are documented.
- [ ] The prototype is ready for further interaction iteration; final contest submission materials remain a separate task.

## Scope boundary

Prototype integration and evidence only. No production hosting, complete game, formal comparative study, or final contest submission.
