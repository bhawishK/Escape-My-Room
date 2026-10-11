# 13: Add two-way voice to the session

**What to build:** The master and solver talk while using their WebXR views.

**Blocked by:** 01 — Connect mobile and VR through Python with a tracked pose

**Status:** ready-for-agent

## Proposed technical approach

- Propose browser WebRTC audio with signaling scoped to the Python session; microphone permission starts through explicit user interaction.
- Keep voice signaling separate from object commands. Media transport is not automatically carried by the object-state WebSocket.
- Verify connectivity between the actual remote networks and record STUN/TURN requirements. Do not assume LAN success proves remote media connectivity.
- Support mute, leave, and permission/connection feedback, cleaning up audio tracks on session exit.

## Acceptance criteria

- [ ] Two-way audio works on the target phone/headset while both are in XR.
- [ ] Permission refusal, mute, and connection failure have understandable outcomes.
- [ ] Voice stays usable while moving the phone and exploring the room.
- [ ] Leaving ends the participant's audio connection and releases microphone capture.
- [ ] Document the remote-network check and chosen audio/signaling configuration.

## Scope boundary

Human speech only; no transcription, commands, or required spatial audio.
