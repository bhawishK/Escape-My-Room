# 16: Let the solver complete one authored room-object task

**What to build:** The solver uses the chosen simple virtual behavior to retrieve/interact with the prepared item and reaches a shared, clear puzzle outcome while the master remains able to participate.

**Blocked by:** 15 — Prepare hidden content and deliberately reveal it

**Status:** ready-for-agent

## Proposed technical approach

- Use the behavior selected in the pilot. A revealed-item retrieval followed by a completion state is the proposed minimal demo; do not infer mechanical drawers from room geometry.
- Represent the behavior's explicit state and permitted action in Python; validate visibility, current ownership, target identity, and the chosen eligibility condition on action requests.
- Render available/collected/completed feedback from accepted shared state, not from independent local puzzle flags. Duplicate completion requests have no additional effect.
- If the selected behavior uses an interaction region, define it relative to the authored host and document how the solver activates it. Both clients must see the same resulting item/game state.

## Acceptance criteria

- [ ] The solver performs the selected behavior and reaches a clear accepted task outcome.
- [ ] The mobile master observes the corresponding result and can continue using the agreed live controls when virtual content is available, without overriding solver ownership.
- [ ] Ineligible, concealed-target, and conflicting-control actions cannot bypass the behavior's rules.
- [ ] Both clients agree on the item and completion state, including a newly joined participant.
- [ ] Connected checks cover one successful path, denied actions, duplicate requests, and the existing visibility/control rules.

## Scope boundary

One small scenario. No puzzle library, timer/trap systems, physical drawer detection, or obligatory live clue-moving mechanic.
