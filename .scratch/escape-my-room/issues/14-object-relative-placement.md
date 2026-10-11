# 14: Place virtual content relative to a room object

**What to build:** The master places content relative to recognizable furniture, and both participants observe the same room-object relationship.

**Blocked by:** 12 — Measure placement and refine the motion mapping

**Status:** ready-for-agent

**GitHub issue:** [#14](https://github.com/bhawishK/Escape-My-Room/issues/14)

## Proposed technical approach

- Use the placement direction selected in the pilot. An authored support anchor/region on a desk or floor is a proposed first implementation; interior containment is not assumed.
- Represent placement using host entity ID, anchor/region ID, and local item transform. Python validates the target and derives the resulting room-space transform from the host transform.
- Show the candidate relationship in mobile feedback before commitment, apply the selected placement policy, and synchronize the accepted result to VR.
- Specify what a later free grab does to the relationship: the proposed default detaches the item while preserving its room-space pose. Test this interaction rather than leaving a stale parent binding.

## Acceptance criteria

- [ ] Master commits an item relative to one authored furniture region/anchor and VR sees the same accepted pose.
- [ ] Unknown targets, incompatible placement, and unavailable objects are rejected consistently.
- [ ] Moving out of the placement relationship follows a documented policy without teleporting the item.
- [ ] Existing hold/release and exclusive-control rules still work.
- [ ] Demonstrate and test the selected room-relative behavior; record how it addresses a pilot finding.

## Scope boundary

One chosen placement relationship. Complex physics, inferred interiors, and automatic reconstruction refinement are excluded.
