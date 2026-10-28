# Room alignment decision

Issue 3 calibrates each device onto the prepared room from [the room decision](prepared-room.md). The room objects stay where the manifest puts them. Calibration changes where the participant is standing and which way they face.

Each device has its own WebXR origin. The Quest user's physical room is not the phone user's room. A calibration saved for one device is not reused for the other.

## Landmarks

| Check | Room meaning | Room coordinates |
| --- | --- | --- |
| Known point | Center of the floor, on the top surface | `(0, 0, 0)` |
| Heading | Facing the desk from that center | Forward is room `-Z` |
| Scale check | Desk width, along X | `1.20 m` |

The desk's bottom center is `(0, 0, -1.20)`. Its front face, the side toward the viewer, is at `z = -0.90`. Its left and right edges are `x = -0.60` and `x = 0.60`. The 1.20 m width is the distance between those edges.

## How a person calibrates

1. Stand so the known point is at their feet: the floor center in the virtual room.
2. Face the desk. That facing direction becomes room `-Z`. Room `+X` is to their right, and room `+Y` is up.
3. Confirm. Python stores that device's alignment and marks it aligned.
4. Repeating the confirmation replaces the stored alignment and updates the status.

The scale check compares the desk's known 1.20 m width with the distance between its edges after conversion into room coordinates. It does not resize the room.

## Agreement on known poses

Two devices can stand in different WebXR coordinates and still name the same room points. The check uses these viewer poses:

| Device | XR position of the head | Facing |
| --- | --- | --- |
| Phone | `(0.40, 1.50, 0.25)` m | XR `-Z`, the identity view |
| Headset | `(-0.70, 1.60, 1.10)` m | Turned `0.50` rad about Y from that identity view |

From each pose, the floor point under the head (`STANDING_EYE_HEIGHT`, 1.5 m, below it; see [eye height](#reference-space)), one meter straight ahead, and the two desk edges are converted with that device's alignment. Both conversions land on:

| Landmark | Room point |
| --- | --- |
| Floor center | `(0, 0, 0)` |
| One meter toward the desk | `(0, 0, -1)` |
| Desk left edge | `(-0.60, 0, -1.20)` |
| Desk right edge | `(0.60, 0, -1.20)` |

The disagreement between the phone conversion and the headset conversion is below `0.000000001` m. The distance between the converted desk edges is `1.20` m. Confirming again from a new pose still puts that device's floor point on `(0, 0, 0)` and leaves the other device's alignment in place. A measurement of these same points inside the Quest has not been recorded yet.

## Reference space

Calibration reads the viewer pose in the `local` reference space. The session requires `local`. `local-floor` is optional and is not the space used for the stored yaw and origin. In `local`, Y = 0 is the height of that session's origin, near where the head started, not the floor. The known floor point therefore uses the head's X and Z only.

**Eye height (Issue 56).** Earlier, the stored origin kept Y at 0. That put the room's floor at the Quest user's eye level, while the phone shows the room from 1.5 m. Now confirming sets the origin's Y to `STANDING_EYE_HEIGHT - head Y` (`frontend/src/alignment.ts`). The head's height at confirmation becomes standing eye height, 1.5 m, with the floor 1.5 m below it.
- **Same value as the phone:** the phone's starting view, `START_EYE` in `frontend/src/phone-view.ts`, uses the same constant. Both people see the room from the same height.
- **Head movement still counts:** standing up, crouching and leaning after confirming still move the headset view by the real amount.
- **Presence:** the headset's presence marker now reports about 1.5 m when standing, like the phone's.
- **Before confirming:** in VR, the room is drawn 1.5 m below the `local` origin, so the floor is already under the user's feet.
- **Users of other heights:** everyone sees the room from 1.5 m at confirmation. A taller or shorter user is mapped to that height, not to their own.

## What makes an alignment stale

- Disconnecting a device clears that device only: status returns to `not_aligned`, and yaw and origin return to 0. The other device stays aligned.
- Connecting the same role in a new tab does the same before the new page confirms. The new page has a new XR origin, so the previous yaw and origin are dropped.
- Confirming again replaces only that device's yaw and origin.
- A reset of the `local` reference space, or leaving VR, forgets the saved yaw and origin (`clear_alignment`). The status returns to `not_aligned`, and the person presses A again. A brief tracking loss lets go of a hold but keeps the alignment.
- A new prepared-room version would move the landmarks this alignment was built on. The current room version is 1.

## What is stored

One transform per connected role, from that device's WebXR reference space into the room frame:

`room_point = rotate_y(yaw) * xr_point + origin`

`origin` is the room position of that device's XR origin. `yaw` is radians about Y. Yaw `0` keeps the view direction, XR `-Z`, pointing along room `-Z` toward the desk. The status is `not_aligned` until a confirmation, then `aligned`. Repeating confirmation replaces that device's transform only. Pitch and roll are not calibrated here.

## The phone

The phone page does not offer **Confirm alignment**. Its room view stands at a fixed spot and turns with the phone, and a phone position would arrive already in room coordinates, so Python applies no alignment to it; the protocol still accepts a phone calibration, but nothing uses it. See [phone tracking](phone-tracking.md). The calibration above remains the headset's. Losing tracking and resetting a broken alignment is Issue 10.
