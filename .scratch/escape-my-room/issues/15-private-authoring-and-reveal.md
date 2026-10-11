# 15: Prepare hidden content and deliberately reveal it

**What to build:** The master privately prepares one virtual game item associated with a room object and can deliberately make it available to the solver.

**Blocked by:** 14 — Place virtual content relative to a room object

**Status:** ready-for-agent

**GitHub issue:** [#15](https://github.com/bhawishK/Escape-My-Room/issues/15)

## Proposed technical approach

- Add a small role-aware content state such as concealed/revealed, with master-authorized preparation and reveal commands accepted by Python.
- Create role-filtered session snapshots and updates. A hidden target's sensitive location/state must not be sent to the solver merely because its mesh is visually hidden.
- Keep master selection/preparation UI private. Revealing changes the solver's authorized content state and supplies the transform/behavior data needed to render it.
- Ensure the full snapshot used on rejoin follows the same visibility rules as incremental updates; this check does not require implementing reconnection from scratch.

## Acceptance criteria

- [ ] The master prepares one item relative to the room object without exposing its intended location or private controls to the solver.
- [ ] The solver cannot retrieve concealed target state from its session messages/snapshot.
- [ ] An authorized reveal makes the item visible/available consistently in VR.
- [ ] Solver attempts to invoke master preparation/reveal commands are rejected.
- [ ] Connected checks inspect client-visible behavior and role-filtered messages before/after reveal, including a newly joined solver.

## Scope boundary

One game's hidden-content boundary, not a general permission system. No precision-hint interface or compelled movement of hidden keys.
