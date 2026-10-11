# 11: Restore shared state after disconnect and rejoin

**What to build:** A disconnected participant rejoins the existing room state, and an abandoned object becomes usable under a defined recovery policy.

**Blocked by:** 08 — Reject competing and stale interaction commands

**Status:** ready-for-agent

**GitHub issue:** [#11](https://github.com/bhawishK/Escape-My-Room/issues/11)

## Proposed technical approach

- Bind ownership to a participant connection generation/manipulation. Detect disconnects using socket closure plus a documented timeout where needed; choose timeout values from initial testing.
- On loss of the owner, preserve the last accepted transform and clear or expire ownership according to the chosen policy.
- Resume with a full role-filtered authoritative snapshot and a fresh connection generation. Old socket commands cannot affect the rejoined session.
- Give both clients visible connection/recovery status. In-memory state is acceptable for this prototype; document that Python process restart differs from client reconnection.

## Acceptance criteria

- [ ] Disconnect during either master or solver control does not leave permanent stale ownership.
- [ ] Rejoining restores object transform, availability, room version, and participant state consistently.
- [ ] Messages from a prior connection/manipulation cannot move the object after rejoin.
- [ ] Recovery does not replay obsolete movement or cause a fresh hold to jump.
- [ ] Connected checks cover both roles, idle disconnect, active disconnect, and rejoining.

## Scope boundary

Client reconnection only. Durable persistence and high-availability server restart are excluded.
