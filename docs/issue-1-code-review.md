# Issue #1 code review

Baseline approved by the user: `507970ce3d0f20d8ae1f212fc96607f151a8c128`. Initial review used `git diff 507970c...0d8027f`, covering `0d8027f Implement mobile-first connected diagnostic for #1`. Two independent agents reviewed Standards and Spec in parallel, then reviewed the fixes separately. Original findings and follow-up reports are kept under their respective axes.

## Standards

No hard breaches of documented repository standards found. Tooling-enforced formatting and type rules were excluded from manual findings.

One optional heuristic:

- **[P3] Primitive Obsession — `backend/sessions.py`**: `marker: dict[str, Any]`, with marker mutations also in `backend/app.py`. The marker already has a stable, documented domain shape, but dictionary keys and values bypass strict Python checking. A small typed marker model would catch misspelled fields and invalid status values while keeping its transitions inside `Session`. This is a maintainability improvement, not a blocker for the diagnostic slice.

No other material baseline smells found. The modules remain proportionate to the first slice; deferred phone tracking and pending hardware evidence are clearly documented.

Follow-up review:

The optional Primitive Obsession finding is resolved: `MarkerState` gives the marker a typed domain shape, and `Session` now owns reset and removal transitions.

No new material documented-standard breaches or baseline smells found. The grant-release endpoint and browser cleanup address the failed-connection lifecycle without unnecessary abstraction. Stale socket callbacks are guarded, and the added regressions exercise the relevant service and browser boundaries.

## Spec

- **[P2] Failed initial WebSocket join permanently occupies the role.** `backend/sessions.py` reserves a participant through HTTP; `frontend/src/session.ts` discards its credential after socket failure. Fixing WSS and pressing Join again returns 409 because no socket existed to trigger server cleanup. This prevents recovery within the existing shared session. Relevant requirement: “Both actual target devices join the same session under the correct roles and display connection status.” Release unsuccessful reservations through an authenticated operation, or retain the grant for manual retry, and test that recovery.
- **Remaining acceptance evidence is correctly marked pending.** Requirements include “Phone translation reaches Python and changes the marker position in VR” and recording “tested phone, headset, browsers, modes, positional tracking.” Actual iPhone/Quest execution is unverified; phone movement is explicitly deferred by the user's instruction, “Build the iPhone page first; add movement tracking later.” The device record distinguishes simulator/browser tests from hardware evidence and correctly says to keep Issue #1 open.

No scope creep identified. The neutral scene, accepted-state rendering, server identities, role/source/generation validation, session isolation, HTTPS instructions, unsupported/denied XR feedback, and simulator labelling match the approved first slice. No additional XR correctness defect was established by inspection.

Follow-up review: **original recovery finding resolved**.

The browser now releases its participant grant with the matching credential after initial WebSocket failure, before allowing retry. The server serializes release and socket acceptance under the same session lock, preventing a released grant from being reattached. Initial welcome failures also run disconnect cleanup, and old socket callbacks cannot overwrite a newer connection.

The new service regression checks unauthorized release rejection and successful role reuse. The browser regression exercises a failed first socket followed by a real connection in the same session. No new material correctness concern found in the changes reviewed.

If HTTP release also fails, the explicit recovery message accurately explains the remaining limitation. Actual iPhone/Quest evidence and physical phone tracking remain pending as agreed.

Findings: Standards 1 optional, resolved; Spec 1 code defect, resolved, with actual-device acceptance still pending. No outstanding code blocker on either axis.
