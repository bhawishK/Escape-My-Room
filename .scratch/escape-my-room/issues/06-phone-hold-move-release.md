# 06: Implement hold, phone translation, release, and clutching

**What to build:** The master moves the selected item with tracked phone translation while holding a control; the VR solver sees the accepted movement, and release leaves the item in place.

**Blocked by:** 05 — Select the intended room object from mobile

**Status:** ready-for-agent

## Proposed technical approach

- Use Python-authoritative states available/master-controlled, with acquire, movement, and release commands. Return accepted state or rejection; never let the client silently overwrite authority.
- At accepted acquisition capture the phone pose in room coordinates and the current object position. Apply relative phone displacement scaled by a configurable gain; repeated holds capture fresh baselines.
- Include object ID, manipulation ID, movement sequence, and server revision in the interaction contract. Broadcast accepted transforms and owner state; reject malformed poses and movement from non-owners.
- Start with translation only and fixed placement on release. This proposed policy excludes gravity and snapping until later experiments; record the initial coordinate frame and gain.
- Handle the held control's release/cancel path explicitly. A denied acquisition must not enter active manipulation, and moving the phone outside an active hold must not move the item.

## Acceptance criteria

- [ ] Selection–hold–movement–release works across mobile, Python, and VR on the actual devices.
- [ ] The solver sees active master control and accepted motion during the hold.
- [ ] Unselected/disengaged phone movement does not change the object.
- [ ] Release commits the accepted final position, and subsequent phone repositioning leaves it unchanged.
- [ ] Re-engagement starts from the current object position without a jump.
- [ ] Connected checks verify state transitions, non-owner rejection, and repeated engagement; record initial mapping parameters.

## Scope boundary

No rotation, solver grab, automatic handoff, assisted placement, or physical-object synchronization.
