# Prototype connection and pose contract

Python owns one shared room in one process. There are no session IDs, participant IDs, join grants, tokens, accounts, or simulator inputs. Room alignment, selection, object ownership, and manipulation remain later slices.

## Connect a device

| Request | Result |
| --- | --- |
| `GET /api/health` | `{ "status": "ok" }` |
| WebSocket `/api/ws?role=mobile_master` | Connect the phone |
| WebSocket `/api/ws?role=vr_solver` | Connect the VR headset page |

Both devices use the same origin, with WSS on HTTPS. Unknown roles fail the handshake. One socket is active per role. Connecting a new tab in a role replaces the old socket, whose close reason explains that another tab connected. The old endpoint cannot remove the replacement. A new phone connection resets the marker and starts a fresh pose sequence.

The first event is `{ "type": "welcome", "state": ... }`. Later events are `{ "type": "state", "state": ... }`; both roles receive the same accepted state, including their own updates:

```json
{
  "revision": 2,
  "mobile_connected": true,
  "vr_connected": true,
  "marker": {
    "tracking_status": "inactive",
    "reference_space": null,
    "position": null
  },
  "room": {
    "available": true,
    "room_version": 1,
    "units": "meters",
    "asset_url": "/assets/prepared-room/room.gltf",
    "error": null,
    "entities": [],
    "loaded_by": { "mobile_master": null, "vr_solver": null }
  }
}
```

The example omits the four entity objects. A live room lists `floor`, `desk`, `cabinet`, and `box` with their kinds and starting positions. Revision increases for joins, accepted poses, room acknowledgements, accepted entity moves, and disconnects. Closing the VR socket sets `vr_connected` to false. Closing the phone socket also clears its marker to `lost`, without disconnecting VR. Restarting Python removes all state. There is no automatic reconnect; the role button starts a fresh connection. There are no HTTP reservations to release if a socket fails.

Connected status represents a live page connection, not proof that immersive VR has started or positional tracking works. Roles constrain message behavior; they are not authentication. Anyone who can access this prototype URL can choose either role.

## Publish a marker pose

Only the phone role can publish:

```json
{
  "type": "pose",
  "sequence": 1,
  "tracking_status": "tracked",
  "reference_space": "local",
  "position": { "x": 0.25, "y": 0.1, "z": -0.3 }
}
```

Sequences strictly increase within each socket, starting at 1. Coordinates must be finite numbers within ±100 meters. Unknown fields are rejected. A tracked pose requires position and `local` or `local-floor`; this client requests `local`. `inactive`, `lost`, and `emulated` statuses require a null position. Simulated status is no longer accepted.

The retained WebXR path samples `XRFrame.getViewerPose(localReferenceSpace).transform.position` at most 20 times per second when position is not emulated and visibility is usable. It drops frames instead of buffering offline poses. An unsupported iPhone page sends no positional input; the agreed iPhone tracking mechanism remains deferred.

Malformed JSON, binary frames, schema violations, solver publications, and repeated sequences produce `{ "type": "error", "code": "...", "message": "..." }` without changing the marker. Codes are `invalid_message`, `role_forbidden`, and `stale_sequence`. Text messages are limited to 16 KiB; the documented server invocation enforces the same transport limit, which may close oversized frames. These are correctness checks, not sensor attestation.

## Prepared room

`GET /api/room` returns the same room descriptor served in `state.room`, without `loaded_by`. Python loads `assets/prepared-room/manifest.json` at startup. The manifest is the identity contract: room version, entity IDs, static or movable kind, selectable flag, and bottom-center positions in meters. Node names in the glTF are only pointers. If the manifest is missing or invalid, the model file or its geometry is missing, a manifest node is absent, two entities share one mesh, or a node translation disagrees with the manifest, the room is unavailable. `/api/room` then returns HTTP 503 with that reason, and both sockets receive `room.available: false` plus the same `room.error`. Neither device is given a different room.

A client that has drawn the model sends `{ "type": "room_loaded", "room_version": 1 }`. A version other than the server's room version returns `room_version_mismatch` and that socket is closed, so it does not remain in the session. `loaded_by` records the version each connected role has acknowledged.

`{ "type": "entity_transform", "id": "box", "position": { "x": 0.25, "y": 0.0, "z": 0.1 } }` changes only that entity. Static furniture returns `entity_not_movable` and does not change any position. An unknown ID returns `unknown_entity`. This proves the movable item is independently addressable. It is not phone manipulation; selection and phone movement remain later issues.

## Render accepted state

Both clients render the Python-accepted marker and the prepared room. The room model is loaded from `asset_url` and each entity is placed from the manifest position. The floor, desk, and cabinet stay fixed. The box is a separate object. A failed model load shows the error and removes any partial room. The marker still uses a presentation offset `(0, 1.2, -3)`. The room itself is in manifest meters at the scene origin. This is not shared physical alignment or room calibration. Manual coordinate controls have been removed.
