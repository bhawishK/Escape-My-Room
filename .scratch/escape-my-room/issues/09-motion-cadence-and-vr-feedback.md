# 09: Tune motion delivery and VR display

**What to build:** The solver sees usable continuous motion while the master manipulates an item, with a correct final placement even under imperfect network timing.

**Blocked by:** 06 — Implement hold, phone translation, release, and clutching

**Status:** ready-for-agent

## Proposed technical approach

- Separate XR render cadence from network publication cadence. Coalesce unsent movement to the newest sample rather than growing an unbounded queue.
- Use accepted server revisions and a small configurable interpolation policy on the observing client; local smoothing must not change authoritative placement.
- Treat release as a committed event: pending/coalesced motion cannot overwrite its final position or leave interpolation running toward an obsolete target.
- Record sample/update rates, acknowledgements, visible correction magnitude, and network conditions. Do not infer cross-device one-way latency by subtracting unsynchronized clocks.

## Acceptance criteria

- [ ] Motion remains understandable under documented normal and induced-delay conditions on both devices.
- [ ] Release settles at the exact accepted final transform rather than the last interpolated preview.
- [ ] The service and clients avoid growing movement backlogs during a long hold.
- [ ] Metrics and tested settings are recorded without inventing a latency target before baseline measurement.
- [ ] Connected checks verify final-state agreement when movement messages are delayed or coalesced.

## Scope boundary

No speculative prediction system or performance claims based only on desktop simulation.
