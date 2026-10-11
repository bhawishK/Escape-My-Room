# 10: Stop manipulation when tracking or room alignment becomes invalid

**What to build:** The master receives clear feedback on tracking loss or a reference-space reset and resumes only after valid tracking/alignment, without jumping the object.

**Blocked by:** 06 — Implement hold, phone translation, release, and clutching

**Status:** ready-for-agent

## Proposed technical approach

- Handle missing/invalid viewer poses, session visibility/end events, and reference-space reset notifications separately; an XR pose is not guaranteed on every frame.
- Pause movement immediately, preserve the last accepted object transform, and follow a documented release/recovery policy. Do not keep integrating stale displacement.
- Invalidate or recompute room alignment when its reference frame changes. Re-engagement captures a fresh baseline after recovery.
- Exercise interrupted input as well as tracking, so disappearing UI or ending the XR session cannot silently sustain manipulation.

## Acceptance criteria

- [ ] Missing tracking does not move the object using stale or fabricated poses.
- [ ] Mobile shows tracking/alignment status and explains the action needed to resume.
- [ ] A reset or session end leaves an agreed object pose and ownership outcome visible in VR.
- [ ] After recalibration/recovery, a new hold starts without a jump.
- [ ] Record real-device interruption exercises and connected checks for the selected recovery policy.

## Scope boundary

Master phone tracking recovery. Network disconnection recovery is ticket 11.
