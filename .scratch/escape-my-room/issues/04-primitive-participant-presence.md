# 04: Show each participant's position and orientation

**What to build:** The master and solver see primitive representations of one another at consistent locations in the room.

**Blocked by:** 03 — Align both WebXR views with the shared room

**Status:** ready-for-agent

## Proposed technical approach

- Convert tracked viewer poses to room coordinates and send bounded-rate presence updates through the Python session.
- Separate participant poses from object transforms and ownership. A presence update cannot change a game object.
- Render a simple head/device marker with heading and role; hide the local marker where it would obstruct the user's view.
- Track presence freshness and remove or mark departed participants without adding a detailed avatar system.

## Acceptance criteria

- [ ] Both clients see the other participant's room-space position and heading during movement.
- [ ] Presence remains independent of object manipulation and does not expose private controls.
- [ ] Joining, leaving, and stale presence have understandable visual outcomes.
- [ ] Record update cadence and device performance observations.
- [ ] Verify participant isolation and coordinate consistency through the connected clients.

## Scope boundary

Primitive presence only; no body tracking, expressive avatars, or spatialized voice.
