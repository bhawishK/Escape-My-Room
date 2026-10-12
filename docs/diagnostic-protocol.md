# Diagnostic session contract

The browser joins through HTTP and receives authoritative state over JSON WebSockets. Python state is local to one process. This contract concerns a marker only; room alignment, selection, object ownership, and manipulation are later slices.

## Join and identity

| Request | Result |
| --- | --- |
| `GET /api/health` | `{ "status": "ok" }` |
| `POST /api/sessions` | HTTP 201 with server-assigned `session_id` |
| `POST /api/sessions/{session_id}/participants` | HTTP 201 with `participant_id`, `connection_token`, and `role` |

The join body is `{ "role": "mobile_master", "tracking_source": "webxr" }`. The other role is `vr_solver`; the explicit development source is `simulator`. Unknown fields and values are rejected with HTTP 422, a missing session with 404, and an occupied role with 409. Each session has at most one participant in each role. A role reserved by HTTP but never connected is retained until process restart; automatic retry/expiry is not implemented in this first slice.

Connect to `/api/sessions/{session_id}/ws?participant_id={participant_id}` using WebSocket subprotocols `["escape-my-room", connection_token]`. Python selects `escape-my-room` and validates the credential against that participant in that session. The token is not included in shared state, invitation links, or query strings. Treat it as a connection credential. The invitation shares only the session ID.

The first message is `welcome`, containing the assigned `connection_generation` and the current state. A new socket for the same credential replaces the old one, increments its generation, resets its sequence, and clears an old master pose. A client must use the generation it received. The UI does not reconnect automatically: leave and rejoin after a dropped connection. On disconnect, Python removes that participant and releases its role.

## Publish a marker pose

Only the mobile master can publish a pose. Example from an XR frame:

```json
{
  "type": "pose",
  "connection_generation": 1,
  "sequence": 1,
  "tracking_status": "tracked",
  "reference_space": "local",
  "position": { "x": 0.25, "y": 0.1, "z": -0.3 }
}
```

Sequence numbers strictly increase within the current connection. Position contains finite numeric coordinates bounded to ±100 meters for this diagnostic. It is not an accelerometer estimate: the XR path sends `XRFrame.getViewerPose(localReferenceSpace).transform.position` only when positional tracking is not emulated and visibility is usable. The app samples at most 20 times per second and drops frames rather than buffering offline poses.

| Tracking status | Position | Meaning |
| --- | --- | --- |
| `tracked` | Required | Non-emulated WebXR position |
| `simulated` | Required | Explicit simulator input, never labelled tracked |
| `inactive` | `null` | XR has not started or has ended |
| `lost` | `null` | No usable pose, visibility lost, or master disconnected |
| `emulated` | `null` | Runtime is emulating position; not accepted as positional evidence |

Usable poses require `local` or `local-floor`; this client requests `local`. Simulator-source participants cannot publish `tracked`/`emulated`, and WebXR-source participants cannot publish `simulated`. These checks distinguish declared paths; they cannot attest to a browser's physical sensors. An unsupported iPhone view sends no positional input.

Malformed JSON, binary frames, schema violations, non-finite values, invalid sources, solver publications, stale generations, and repeated sequences are rejected without updating the marker. Application errors have `type: "error"`, a stable `code`, and an actionable `message`. Text payloads are limited to 16 KiB; the documented server invocation also enforces that limit at the WebSocket transport (oversized frames may close the socket). Invalid handshake credentials are refused before accepting the socket.

## Render accepted state

Both clients render `state` events with `session_id`, monotonically increasing `revision`, public `participants`, and `marker`. Participants report role, declared source, connected status, and connection generation. Marker state includes the originating participant/source, tracking status, reference space, and position. The publisher also waits for accepted state before moving its own marker. Session broadcasts go only to that session's sockets.

Coordinates are the sender's raw XR meters. The diagnostic places their origin at a visible presentation offset `(0, 1.2, -3)` in each viewer's scene. This is deliberately not a shared physical room origin or calibration. Unavailable positions hide the sphere; simulated positions use amber and an explicit label. Axes/grid remain visible as the neutral scene.
