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

From each pose, the floor point under the head, one meter straight ahead, and the two desk edges are converted with that device's alignment. Both conversions land on:

| Landmark | Room point |
| --- | --- |
| Floor center | `(0, 0, 0)` |
| One meter toward the desk | `(0, 0, -1)` |
| Desk left edge | `(-0.60, 0, -1.20)` |
| Desk right edge | `(0.60, 0, -1.20)` |

The disagreement between the phone conversion and the headset conversion is below `0.000000001` m. The distance between the converted desk edges is `1.20` m. Confirming again from a new pose still puts that device's floor point on `(0, 0, 0)` and leaves the other device's alignment in place. A measurement of these same points inside the Quest has not been recorded yet.

## Reference space

Calibration reads the viewer pose in the `local` reference space. The session requires `local`. `local-floor` is optional and is not the space used for the stored yaw and origin. In `local`, Y = 0 is the height of that session's origin, so the known floor point uses the head's X and Z, and the stored origin keeps Y at 0.

## What makes an alignment stale

- Disconnecting a device clears that device only: status returns to `not_aligned`, and yaw and origin return to 0. The other device stays aligned.
- Connecting the same role in a new tab does the same before the new page confirms. The new page has a new XR origin, so the previous yaw and origin are dropped.
- Confirming again replaces only that device's yaw and origin.
- A reset of the `local` reference space, or a loss of tracking, means the saved yaw and origin still describe the old origin. The status can remain `aligned`. Rebuilding the alignment after that loss is Issue 10.
- A new prepared-room version would move the landmarks this alignment was built on. The current room version is 1.

## What is stored

One transform per connected role, from that device's WebXR reference space into the room frame:

`room_point = rotate_y(yaw) * xr_point + origin`

`origin` is the room position of that device's XR origin. `yaw` is radians about Y. Yaw `0` keeps the view direction, XR `-Z`, pointing along room `-Z` toward the desk. The status is `not_aligned` until a confirmation, then `aligned`. Repeating confirmation replaces that device's transform only. Pitch and roll are not calibrated here.

## The phone

Issue 19 places the phone without this calibration. The phone measures itself against the room's printed marker and sends positions already in room coordinates, so Python applies no alignment to them. The phone page no longer offers **Confirm alignment**; the protocol still accepts a phone calibration, but nothing uses it. See [phone tracking](phone-tracking.md). The calibration above remains the headset's. Losing tracking and resetting a broken alignment is Issue 10.
