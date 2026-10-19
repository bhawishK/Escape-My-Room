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
    "frame": "y_up_right_handed",
    "quaternion_order": "xyzw",
    "error": null,
    "entities": [],
    "loaded_by": { "mobile_master": null, "vr_solver": null }
  }
}
```

The example omits the entity objects. The default room lists `floor`, `desk`, `cabinet`, and `box`. Each entity has `id`, `label`, `asset_url`, `node`, `kind`, `selectable`, `size`, `position`, and a unit-quaternion `rotation` in `(x, y, z, w)` order. In the stand-in room every entity shares `/assets/prepared-room/room.gltf` and has the identity rotation; a multi-asset room gives each entity its own GLB. `units`, `frame`, and `quaternion_order` are null while the room is unavailable. Revision increases for joins, accepted poses, room acknowledgements, accepted entity moves, and disconnects. Closing the VR socket sets `vr_connected` to false. Closing the phone socket also clears its marker to `lost`, without disconnecting VR. Restarting Python removes all state. There is no automatic reconnect; the role button starts a fresh connection. There are no HTTP reservations to release if a socket fails.

Connected status represents a live page connection, not proof that immersive VR has started or positional tracking works. Roles constrain message behavior; they are not authentication. Anyone who can access this prototype URL can choose either role.

## Publish a marker pose

Only the phone role can publish:

```json
{
  "type": "pose",
  "sequence": 1,
  "tracking_status": "tracked",
  "reference_space": "room",
  "position": { "x": 0.25, "y": 1.3, "z": 0.4 }
}
```

Sequences strictly increase within each socket, starting at 1. Coordinates must be finite numbers within ±100 meters. Unknown fields are rejected. A tracked pose requires a position and `reference_space: "room"`: its position is already in room meters. `inactive` and `lost` require a null position. WebXR spaces (`local`, `local-floor`), `emulated`, and `simulated` are no longer accepted.

The phone page sends no poses at present, so the marker stays `inactive`; see [phone tracking](phone-tracking.md). The contract is kept for whichever position tracking is chosen.

Malformed JSON, binary frames, schema violations, solver publications, and repeated sequences produce `{ "type": "error", "code": "...", "message": "..." }` without changing the marker. Codes are `invalid_message`, `role_forbidden`, and `stale_sequence`. Text messages are limited to 16 KiB; the documented server invocation enforces the same transport limit, which may close oversized frames. These are correctness checks, not sensor attestation.

## Prepared room

`GET /api/room` returns the same room descriptor served in `state.room`, without `loaded_by`. Python loads `manifest.json` from `assets/prepared-room/`, or from `ESCAPE_ROOM_PREPARED_DIR` when set, at startup. The manifest is the identity contract: room version, entity IDs, static or movable kind, selectable flag, and bottom-center placement in meters. Node names in the assets are only pointers. If the manifest is missing or invalid, or an asset disagrees with it, the room is unavailable. The [prepared room note](prepared-room.md) lists both manifest forms and their checks. `/api/room` then returns HTTP 503 with that reason, and both sockets receive `room.available: false` plus the same `room.error`. Neither device is given a different room.

## Render accepted state

Both clients render the Python-accepted marker and the prepared room. Each distinct `asset_url` is loaded once. Every entity gets its own placement root at the manifest position and rotation, and its node keeps its child transforms. Nothing is drawn until every asset has loaded. The floor, desk, and cabinet stay fixed. The box is a separate object. A failed asset load shows the asset name and removes any partial room. The phone's marker is drawn in room meters with the furniture, so the headset sees it where the phone is in the room. The phone's room view draws no marker for itself. Manual coordinate controls have been removed.
