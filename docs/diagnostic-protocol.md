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
  "participants": {
    "mobile_master": { "tracking_status": "inactive", "position": null, "heading": null },
    "vr_solver": { "tracking_status": "inactive", "position": null, "heading": null }
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

The example omits the entity objects. The default room lists `floor`, `desk`, `cabinet`, and `box`. Each entity has `id`, `label`, `asset_url`, `node`, `kind`, `selectable`, `size`, `position`, and a unit-quaternion `rotation` in `(x, y, z, w)` order. In the stand-in room every entity shares `/assets/prepared-room/room.gltf` and has the identity rotation; a multi-asset room gives each entity its own GLB. `units`, `frame`, and `quaternion_order` are null while the room is unavailable. Revision increases for joins, accepted poses, accepted presence, room acknowledgements, accepted entity moves, and disconnects. Closing the VR socket sets `vr_connected` to false. Closing the phone socket also clears its marker to `lost`, without disconnecting VR. Restarting Python removes all state. There is no automatic reconnect; the role button starts a fresh connection. There are no HTTP reservations to release if a socket fails.

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

## Pick up, aim and drop an object

The phone picks up its selected object and places it by aiming, then lets go. The object goes where the ray from the centre of the phone's screen meets the floor. Turning the phone swings it around you, and tilting slides it nearer or further. This uses the phone's orientation sensor, which is reliable on the iPhone, rather than its position, which is only counted from steps ([phone tracking](phone-tracking.md)). Walking still moves you, and the aim with you, for longer distances.

The user chose this on 20 October 2026, after trying first to carry the object by counting steps and then to hold it in front of them. Both felt loose. The aim is the 3-degree-of-freedom ray-casting technique that orientation-only VR controllers use. Real 6-degree-of-freedom tracking, through Android WebXR or a native ARKit app, remains the route to the one-to-one room view.

Only the phone may send:

```json
{ "type": "acquire", "room_version": 1, "id": "box" }
{ "type": "release", "manipulation_id": 3 }
```

Poses carry where the phone's screen centre aims:
- `heading`, in radians: 0 faces the desk (-Z), and positive turns left.
- `pitch`, in radians: 0 is level, and negative looks down.

Both are `null` without a reading, which counts as facing the desk on the level, and must be `null` when the pose is not tracked. The pose's position is the view's: walking's place at the view's height, the measured one when there is one. The marker in the state carries all three.

An accepted `acquire` places the object where the aim meets the floor it rested on, and every later tracked pose places it there again. The rules:
- **Distance:** no nearer than 0.3 m and no further than 4 m. Aiming level, or upward, goes to the furthest.
- **Floor:** an aim past the floor's edge stops there, with the object whole on the floor. The floor is the thin static entities, as for walking.
- **Height:** the object keeps its floor height; it only slides.

`release` leaves it where it is, so it drops exactly where the phone shows it. Walking without a hold moves nothing.

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

A refused `acquire` starts nothing. A pose without a position, such as closing the room view, ends the hold where the object is, and so does the phone disconnecting. Only position is applied: no rotation, gravity, snapping, or collision with furniture.

**On the phone:**
- **Pick up:** tap the box, then press and hold it. After 0.3 s it jumps to where the screen centre meets the floor. A pink crosshair marks the centre, and the status line reads **Carrying box · turn and tilt to place it, let go to drop it**. A quick tap does not pick it up.
- **Aim:** turn and tilt the phone to place it. The phone draws the box at its own aim every frame, using the same rule as Python (`frontend/src/aim.ts`), so it does not lag behind the crosshair. It sends its pose to Python ten times a second, so the headset follows.
- **Drop:** lift your finger, and the status line reads **Dropped box**. Before letting go, the phone sends its latest pose, so Python places the box where the phone shows it.
- **Other ways the hold ends:** a cancelled touch drops it, and **Back to start** drops it first.

Tested through the WebSocket seam (`tests/test_manipulation.py`): picking up to the aim, turning, tilting, the 0.3 m and floor-edge limits, walking with the aim, dropping in place, refusals, ending on stopping and on disconnect, and the headset's view.

A desktop run of both pages with synthetic orientation readings, the phone 1.5 m up, went as follows:

| Phone aim | Box position |
| --- | --- |
| 45° down | 1.5 m ahead, under the crosshair |
| 30° down | 2.6 m ahead |
| Turned 90° left | Stopped at the floor's edge, with the crosshair beyond it |
| Let go | Stayed there; the headset page showed **Phone is moving box** until then |

Not yet tried on the iPhone and Quest.

## Motion delivery

Issue #9. While the phone moves a held object, the headset should see continuous motion and the exact final placement, even on a slow network, without anything queueing up during a long hold.

**Python.** Each connected device has its own outbox (`backend/delivery.py`), emptied by its own task, so a slow device holds up neither the phone nor the room.
- Replies (welcome, errors, selection results) are all delivered, and everything goes in the order it was handed over.
- Shared state is coalesced. Of the states waiting, only the newest is sent, so movement never builds a backlog. The final state, such as a release, always arrives.
- A device that takes more than 2 s to accept a message is disconnected, rather than left with a growing queue. It can connect again.
- Earlier, Python sent each state to every device one after another while holding the room lock, so a slow headset delayed the phone's next movement.
- The state carries `"delivery": { "simulated_delay_ms": 0 }`.

**Induced delay.** `ESCAPE_ROOM_SIMULATED_DELAY_MS` (0 to 5000) delays every item to every device by that long after Python accepted it. It reproduces network latency for testing, and works like a delay line: what waits is bounded by what arrives within the delay, and only the newest due state is sent.

**Phone.** The phone sends its pose ten times a second while holding, separately from drawing, which runs every frame. If the connection is congested (more than 16 KiB unsent), only the newest pose waits, replacing any older one, and it goes as soon as the connection drains. Letting go sends any waiting pose before the release, even when congested, so the release commits the last aim. The phone draws its own held object from its own aim, so the delay does not affect what the person holding it sees.

**Headset.** The other device's held object glides toward each accepted placement instead of stepping at each update. It closes about 63% of the gap every 120 ms; `?smoothing=<ms>` on the page URL sets this, from 0 (off) to 1000. Only the drawing is smoothed. When the hold ends, the next placement is Python's final one and is drawn exactly, not the last glide position.

**Measurements.** Each page records these, on the diagnostics line under **Device smoke-test diagnostics** and in the downloaded report's `motion` section:
- State and pose rates over the last 5 s.
- Poses replaced while the connection was congested.
- The acknowledgement round trip: from sending a pose until a state including it arrives, timed on the phone's own clock.
- Each jump from the drawn object to the final placement when a hold ends.
- The smoothing, the induced delay, and the browser's own connection estimate where it gives one.

No one-way latency between devices is worked out, since their clocks are not synchronised. No latency target is set before measurements on the real devices exist.

**Tested** through the WebSocket seam (`tests/test_motion_delivery.py`):
- A hundred moves sent in a burst under a 200 ms delay reach the headset as at most ten states. The last equals the phone's final placement.
- Movement sent after a release does not move the object.
- The delay holds back every state during steady movement, not only the first.
- The state reports the delay.

**Desktop measurements.** Two Edge pages on one computer, with synthetic orientation readings. The phone held the box and swept its aim 60° in 2.8 s, then let go. Desktop only; not evidence of device behaviour.

| Induced delay | Poses sent | States at headset | Phone ack (median) | Headset jump at release | Final placement |
| --- | --- | --- | --- | --- | --- |
| 0 ms | 28 | 28 | 1 ms | 0.091 m | Same on all three |
| 300 ms | 27 | 27 | 313 ms | 0.093 m | Same on all three |

The jump at release is the 120 ms glide trailing a box swung at about 0.6 m/s. A shorter `?smoothing=` shrinks it, and makes the steps between updates more visible. On the iPhone and Quest, record the same table: on the normal network and with a delay, the rates, the acknowledgement round trip, the corrections, and whether the motion is easy to follow.

## Publish presence

Either role can publish where that person is. A presence update changes only that role's entry in `participants`. It does not move a room object, and an object move does not change presence. Each socket has its own presence sequence, separate from the phone's pose sequence, starting at 1 and strictly increasing.

```json
{
  "type": "presence",
  "sequence": 1,
  "tracking_status": "tracked",
  "position": { "x": 0.0, "y": 1.5, "z": 1.6 },
  "heading": 0.0
}
```

`heading` is radians about Y. `0` faces the desk, along room `-Z`. Positive turns left. A tracked update requires a position and a heading, both already in the room frame. The Quest converts its `local` viewer pose with the alignment it confirmed before sending. The phone sends the room view's place directly. `inactive` and `lost` require a null position and a null heading.

The page sends at most 20 presence updates a second and drops one when the socket already has 16 KiB waiting. If a tracked participant sends nothing for 1.5 seconds, Python marks that entry `stale` and keeps the last position and heading. Disconnecting sets that role to `lost` and clears the position and heading. A new tab in the same role starts at `inactive`. Each page draws the other person's marker and hides its own. See [participant presence](participant-presence.md).

## Prepared room

`GET /api/room` returns the same room descriptor served in `state.room`, without `loaded_by`. Python loads `manifest.json` from `assets/prepared-room/`, or from `ESCAPE_ROOM_PREPARED_DIR` when set, at startup. The manifest is the identity contract: room version, entity IDs, static or movable kind, selectable flag, and bottom-center placement in meters. Node names in the assets are only pointers. If the manifest is missing or invalid, or an asset disagrees with it, the room is unavailable. The [prepared room note](prepared-room.md) lists both manifest forms and their checks. `/api/room` then returns HTTP 503 with that reason, and both sockets receive `room.available: false` plus the same `room.error`. Neither device is given a different room.

## Render accepted state

Both clients render the Python-accepted marker and the prepared room. Each distinct `asset_url` is loaded once. Every entity gets its own placement root at the manifest position and rotation, and its node keeps its child transforms. Nothing is drawn until every asset has loaded. The floor, desk, and cabinet stay fixed. The box is a separate object. A failed asset load shows the asset name and removes any partial room. The phone's marker is drawn in room meters with the furniture, so the headset sees it where the phone is in the room. The phone's room view draws no marker for itself. Manual coordinate controls have been removed.
