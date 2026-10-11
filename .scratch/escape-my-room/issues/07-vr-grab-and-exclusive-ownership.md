# 07: Add solver grab and exclusive control

**What to build:** The solver grabs, moves, and releases available items while both participants respect exclusive control.

**Blocked by:** 06 — Implement hold, phone translation, release, and clutching

**Status:** ready-for-agent

**GitHub issue:** [#7](https://github.com/bhawishK/Escape-My-Room/issues/7)

## Proposed technical approach

- Use the tested headset input source and map target-ray/grip poses into room coordinates. Preserve a grab offset so acquisition does not teleport the item to the controller.
- Extend authoritative object state with solver-controlled, using the same acquire/move/release path as mobile.
- Python accepts movement only from the current participant and manipulation ID. Master-controlled objects reject solver acquisition, and solver-controlled objects reject master acquisition.
- Show control availability and rejected requests in both clients; releasing makes the item available without transferring it automatically.

## Acceptance criteria

- [ ] The solver grabs an available item without a position jump, moves it, and releases it; mobile observes the accepted result.
- [ ] Neither participant can move an item controlled by the other.
- [ ] Rejected grabs/holds have clear feedback and leave the current owner and transform unchanged.
- [ ] Connected checks cover both directions of acquisition, movement, release, and ownership conflicts.
- [ ] Document the selected headset input mapping.

## Scope boundary

Exclusive control only. Explicit handoff and simultaneous co-manipulation are excluded.
