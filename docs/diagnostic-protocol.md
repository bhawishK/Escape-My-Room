# Prototype connection and pose contract

Python owns one shared room in one process. There are no session IDs, participant IDs, join grants, tokens, accounts, or simulator inputs. The headset grabbing objects, and competing requests for control, remain later slices.

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

## Select an object

The phone selects the object it means to manipulate. Only the phone may send:

```json
{ "type": "select", "room_version": 1, "id": "box" }
```

`"id": null` deselects. Python checks the room version, that the entity exists, and that it is movable and `selectable`. It replies to the phone alone:

```json
{ "type": "selection", "id": "box", "rejected": null }
```

`id` is the phone's selection after the request. A refused request leaves the current selection in place and says why in `rejected`, as `{ "code": "...", "message": "..." }`. Codes are `entity_not_selectable` (static furniture or the floor), `unknown_entity`, `room_version_mismatch`, and `room_unavailable`; the socket stays open for all of them. The headset's `select` gets an `error` event with `role_forbidden`.

Selection is private intent. It is not in the shared state, does not change the revision, is never sent to the headset, and does not move the object or give anyone control of it. A new phone connection, or the phone disconnecting, clears it.

On the phone's room view a tap selects the object drawn under the finger: the view casts a ray from the camera through the tap, and the nearest surface hit names the entity, so furniture in front hides what is behind it. Only movable, selectable objects are sent; tapping anything else, including furniture, the floor and empty space, deselects. Python still checks every request. An accepted selection is outlined with a pink halo and the status line reads **Box selected · press and hold it to pick it up**. There are no select or deselect buttons. Closing the room view deselects. Tested on desktop through the WebSocket seam (`tests/test_selection.py`); not yet tried on the iPhone.

## Pick up, carry and drop an object

The phone picks up its selected object, carries it in front of itself, and drops it. The phone has no measured position yet, so its position is the step-counted one from walking ([phone tracking](phone-tracking.md)). Movement is therefore coarse: about one step length, 0.6 m by default, at a time. On 20 October 2026 the user chose this over dragging on the screen, then chose to have the object come in front of them while carried and drop where they let go.

Only the phone may send:

```json
{ "type": "acquire", "room_version": 1, "id": "box" }
{ "type": "release", "manipulation_id": 3 }
```

Poses carry the phone's `heading` in radians: 0 faces the desk (-Z), and positive turns left. It is `null` without an orientation reading, which counts as facing the desk, and must be `null` when the pose is not tracked. The marker in the state carries it too.

An accepted `acquire` picks the object up. Python places it 0.8 m in front of the phone, along the heading, with its bottom 0.6 m below the phone. Every later tracked pose places it there again, so it stays in front while the phone walks and turns. `release` drops it straight down to the height it rested at when picked up. Walking without a hold moves nothing.

The hold is shared. The state carries `"manipulation": { "id": 3, "entity": "box", "owner": "mobile_master", "sequence": 12 }`, or `null`. Ids count up across holds. `sequence` is the pose sequence of the latest movement applied, and is `null` until the first. Both pages show **Phone is moving box** under the room status, and both scenes outline the held object in orange.

| Refusal | When |
| --- | --- |
| `not_selected` | `id` is not the phone's current selection |
| `not_tracked` | The phone has no tracked position |
| `already_held` | A hold is already in progress |
| `room_version_mismatch`, `room_unavailable` | As for selection |
| `stale_manipulation` | `release` names a hold that is not the current one |
| `role_forbidden` | The headset sent `acquire` or `release` |
| `entity_controlled` | An `entity_transform` for the held object |
| `selection_held` (on `select`) | The selection cannot change during a hold |

A refused `acquire` starts nothing. A pose without a position, such as closing the room view, drops the object, and so does the phone disconnecting. Only position is applied: no rotation, gravity, snapping or collision. A carried object can therefore pass through furniture, and be dropped off the floor's edge. Positions are clamped to ±100 m.

**On the phone:** tap the box, then press and hold it. After 0.3 s it comes in front of you and the status line reads **Carrying box · let go to drop it**. Walk and turn to carry it, then lift your finger: **Dropped box**. A quick tap does not pick it up. A cancelled touch also drops it. **Back to start** drops it first, so returning does not carry it back. While carrying, the phone sends its pose ten times a second, so the object follows each step's glide and every turn.

Tested through the WebSocket seam (`tests/test_manipulation.py`): pick-up in front, staying in front while walking and turning, dropping to the floor, refusals, dropping on stopping and on disconnect, and the headset's view. A desktop run of both pages with synthetic sensor events went as follows. The tap selected the box, and a tap on the sky deselected it. A press and hold brought the box to 0.8 m in front at 0.9 m. Steps carried it to the desk, and a 90° turn left swung it to the left. Letting go dropped it to the floor, and the headset page showed **Phone is moving box** throughout. Not yet tried on the iPhone and Quest.

## Prepared room

`GET /api/room` returns the same room descriptor served in `state.room`, without `loaded_by`. Python loads `manifest.json` from `assets/prepared-room/`, or from `ESCAPE_ROOM_PREPARED_DIR` when set, at startup. The manifest is the identity contract: room version, entity IDs, static or movable kind, selectable flag, and bottom-center placement in meters. Node names in the assets are only pointers. If the manifest is missing or invalid, or an asset disagrees with it, the room is unavailable. The [prepared room note](prepared-room.md) lists both manifest forms and their checks. `/api/room` then returns HTTP 503 with that reason, and both sockets receive `room.available: false` plus the same `room.error`. Neither device is given a different room.

## Render accepted state

Both clients render the Python-accepted marker and the prepared room. Each distinct `asset_url` is loaded once. Every entity gets its own placement root at the manifest position and rotation, and its node keeps its child transforms. Nothing is drawn until every asset has loaded. The floor, desk, and cabinet stay fixed. The box is a separate object. A failed asset load shows the asset name and removes any partial room. The phone's marker is drawn in room meters with the furniture, so the headset sees it where the phone is in the room. The phone's room view draws no marker for itself. Manual coordinate controls have been removed.
