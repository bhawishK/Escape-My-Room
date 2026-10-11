# 12: Measure placement and refine the motion mapping

**What to build:** Participants perform repeatable desk, cabinet, and floor placement tasks, producing evidence to tune the mapping and select the next interaction extension.

**Blocked by:** 07 — Add solver grab and exclusive control; 09 — Tune motion delivery and VR display

**Status:** ready-for-agent

**GitHub issue:** [#12](https://github.com/bhawishK/Escape-My-Room/issues/12)

## Proposed technical approach

- Define room-space target regions and record final accepted object positions. Derive placement error from the shared geometry rather than screen pixels.
- Record task start/release, completion duration, repeated holds, invalid placements, unintended motion, and observations from both roles. Keep clocks and metric definitions explicit.
- Expose the initial reference-frame/gain configuration for controlled tuning; label each run with its configuration and room version.
- Record the fixed-release/collision policy used. Compare a small justified mapping change against the initial run and choose the next room-relative interaction/behavior from those observations.

## Acceptance criteria

- [ ] Both participants complete documented desk, cabinet, and floor tasks with the connected interaction.
- [ ] Collected metrics can be traced to accepted placements and a specific configuration.
- [ ] Any mapping adjustment is recorded and the affected tasks repeated; the approved interaction checks still pass.
- [ ] Participant observations include perceived movement and control availability.
- [ ] Document one justified next iteration and remaining device/network limitations; no superiority or novelty claim is inferred from the pilot.

## Scope boundary

A practical pilot, not a formal user study. Tickets 10 and 11 may run independently; known interruption limitations must be reported.
