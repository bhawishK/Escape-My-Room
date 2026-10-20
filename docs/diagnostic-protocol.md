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

On the phone's room view a tap selects the object drawn under the finger: the view casts a ray from the camera through the tap, and the nearest surface hit names the entity, so furniture in front hides what is behind it. Tapping empty space sends nothing and reads **Nothing to select there**. Python decides eligibility, so tapping the desk is refused with its message. An accepted selection is outlined with a pink halo, the status line reads **Selected box**, and **Deselect** appears. Closing the room view deselects. Tested on desktop through the WebSocket seam (`tests/test_selection.py`); not yet tried on the iPhone.

## Hold and move an object

The phone carries its selected object by walking. It has no measured position yet, so the phone's position is the step-counted one from **Walk with steps** ([phone tracking](phone-tracking.md)). Movement is therefore coarse: about one step length, 0.6 m by default, at a time. The user chose this on 20 October 2026 over dragging on the screen, so the technique stays phone movement until real tracking arrives.

Only the phone may send:

```json
{ "type": "acquire", "room_version": 1, "id": "box" }
{ "type": "release", "manipulation_id": 3 }
```

An accepted `acquire` starts a hold. Python records where the phone and the object are at that moment. Every later tracked pose moves the object by the phone's displacement since then, multiplied by the gain. The object keeps its height; only movement across the floor carries it. The pose `sequence` orders these movements, and `revision` orders the states. `release` ends the hold, and the object stays where it is. A new hold takes fresh starting places, so the object does not jump. Moving the phone without a hold moves nothing.

The hold is shared. The state carries `"manipulation": { "id": 3, "entity": "box", "owner": "mobile_master", "gain": 1.0, "sequence": 12 }`, or `null`. Ids count up across holds. `sequence` is the pose sequence of the latest movement applied, and is `null` until the first. The selection cannot change during a hold (`selection_held`). Both pages show **Phone is moving box** under the room status, and both scenes outline the held object in orange.

| Refusal | When |
| --- | --- |
| `not_selected` | `id` is not the phone's current selection |
| `not_tracked` | The phone has no tracked position; turn on **Walk with steps** |
| `already_held` | A hold is already in progress |
| `room_version_mismatch`, `room_unavailable` | As for selection |
| `stale_manipulation` | `release` names a hold that is not the current one |
| `role_forbidden` | The headset sent `acquire` or `release` |
| `entity_controlled` | An `entity_transform` for the held object |

A refused `acquire` starts nothing. A pose without a position, such as **Stop walking**, ends the hold in place, and so does the phone disconnecting.

**Gain:** 1.0 by default, so the object moves as far as the phone. `ESCAPE_ROOM_MANIPULATION_GAIN` sets it, from above 0 up to 10. The frame is room meters, the same as the furniture. Only translation across the floor is applied: no height change, rotation, gravity, snapping or collision. A held object can therefore pass through furniture or off the floor's edge. Positions are clamped to ±100 m.

**On the phone:** select the box, turn on **Walk with steps**, then keep **Hold to move** pressed and walk. The status line reads **Moving box · walk to carry it**, then **Placed box** on letting go. Lifting the finger, a cancelled touch, or losing the pointer all release the hold. **Back to start** releases it first, so returning does not carry the box back. While the hold is on, the selection's pink halo follows the box.

Tested through the WebSocket seam (`tests/test_manipulation.py`): carrying, release, re-holding without a jump, refusals, gain, ending on stopping and on disconnect, and the headset's view. A desktop run of both pages with synthetic steps carried the box 1.8 m in three steps, showed **Phone is moving box** on the headset page, and left the box in place when walking on after release. Not yet tried on the iPhone and Quest.

## Prepared room

`GET /api/room` returns the same room descriptor served in `state.room`, without `loaded_by`. Python loads `manifest.json` from `assets/prepared-room/`, or from `ESCAPE_ROOM_PREPARED_DIR` when set, at startup. The manifest is the identity contract: room version, entity IDs, static or movable kind, selectable flag, and bottom-center placement in meters. Node names in the assets are only pointers. If the manifest is missing or invalid, or an asset disagrees with it, the room is unavailable. The [prepared room note](prepared-room.md) lists both manifest forms and their checks. `/api/room` then returns HTTP 503 with that reason, and both sockets receive `room.available: false` plus the same `room.error`. Neither device is given a different room.

## Render accepted state

Both clients render the Python-accepted marker and the prepared room. Each distinct `asset_url` is loaded once. Every entity gets its own placement root at the manifest position and rotation, and its node keeps its child transforms. Nothing is drawn until every asset has loaded. The floor, desk, and cabinet stay fixed. The box is a separate object. A failed asset load shows the asset name and removes any partial room. The phone's marker is drawn in room meters with the furniture, so the headset sees it where the phone is in the room. The phone's room view draws no marker for itself. Manual coordinate controls have been removed.
