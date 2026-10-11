# 08: Reject competing and stale interaction commands

**What to build:** Both participants get consistent results when they request control together or delayed commands arrive after a release or new acquisition.

**Blocked by:** 07 — Add solver grab and exclusive control

**Status:** ready-for-agent

**GitHub issue:** [#8](https://github.com/bhawishK/Escape-My-Room/issues/8)

## Proposed technical approach

- Serialize ownership transitions per session/object in Python. Use an accepted manipulation ID and monotonically ordered movement sequence so old messages cannot affect a later hold.
- Define acquisition ordering, command acknowledgements, and duplicate-command behavior. Retried commands must not create extra acquisitions or releases.
- Clients apply accepted server revisions consistently and clear optimistic feedback after rejection. WebSocket ordering within one connection does not resolve races across participants or reconnects.
- Add a controllable integration harness for delayed, duplicated, or interleaved application messages and assert visible shared outcomes.

## Acceptance criteria

- [ ] Simultaneous acquisition produces one accepted owner and one rejected requester on both clients.
- [ ] Movement/release from an earlier manipulation cannot change a newly acquired object.
- [ ] Duplicate commands leave the same accepted object state.
- [ ] An outdated client revision cannot replace a newer authoritative result.
- [ ] Connected tests exercise competing requests and delayed commands without relying on internal function-call assertions.

## Scope boundary

Two-participant correctness, not distributed multi-server coordination.
