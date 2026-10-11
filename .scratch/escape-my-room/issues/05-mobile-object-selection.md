# 05: Select the intended room object from mobile

**What to build:** The master points or taps to select the movable virtual item, sees clear feedback, and receives an understandable result when an object is unavailable.

**Blocked by:** 03 — Align both WebXR views with the shared room

**Status:** ready-for-agent

## Proposed technical approach

- Implement one selection method supported by the tested device: a touch ray or a center-view ray with an explicit select control is a proposed default.
- Resolve hit render nodes to stable entity IDs and restrict selection to eligible proxies/entities; ignore static background geometry.
- Python validates role, room version, object existence, and eligibility when queried. Selection is private intent and is separate from acquiring manipulation authority.
- Use mobile controls supported during the actual XR session; DOM overlay support must be feature-checked rather than assumed.

## Acceptance criteria

- [ ] Selection reliably resolves to the intended stable entity and highlights it on mobile.
- [ ] Empty-space selection, static geometry, and unknown entities do not select or move unintended content.
- [ ] Selection alone does not move the object or assign ownership.
- [ ] Private selection/preparation controls are not broadcast to the solver as puzzle information.
- [ ] Exercise valid selection, deselection, invalid IDs, and unavailable-object feedback through the client and Python service.

## Scope boundary

One selection technique and one movable object. Gesture recognition and multiple concurrent selections are excluded.
