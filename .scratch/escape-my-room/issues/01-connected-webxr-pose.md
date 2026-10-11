# 01: Connect mobile and VR through Python with a tracked pose

**What to build:** The mobile master and remote VR solver join a WebXR session served by Python; moving the phone moves a diagnostic marker in the VR view. This proves the actual device-to-service-to-headset path before room content is added.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

## Proposed technical approach

- Suggested baseline: TypeScript browser code, Three.js rendering, FastAPI/Pydantic on Python, and JSON over WebSocket. These are proposed implementation defaults, not additional user-confirmed requirements.
- Use a small session contract with a session ID, participant ID, role, connection generation, and diagnostic pose message. Python assigns identities and maintains one in-memory session; both clients render the accepted state.
- Obtain phone translation from WebXR positional poses within XR frames, not by integrating accelerometer readings. Verify immersive-ar, immersive-vr, the chosen reference-space types, and available input on the actual devices.
- Document an HTTPS/WSS setup reachable by the remote participant, including certificate trust and server address configuration. A working desktop simulator helps development but does not substitute for device evidence.

## Acceptance criteria

- [ ] Both actual target devices join the same session under the correct roles and display connection status.
- [ ] Phone translation reaches Python and changes the marker position in VR; each client can start and end its XR session.
- [ ] Record the tested phone, headset, browsers, modes, positional tracking, and whether DOM overlays are usable for a held mobile control.
- [ ] Unsupported capabilities and denied permissions give actionable feedback; no simulated pose is presented as working phone tracking.
- [ ] Define and exercise valid/invalid message handling and session isolation through the running service.
- [ ] Provide repeatable startup instructions and a device smoke-check record.

## Scope boundary

A neutral diagnostic scene only. No reconstruction, room alignment, object ownership, or voice yet. Hardware availability remains a prerequisite for completing the device acceptance checks.
