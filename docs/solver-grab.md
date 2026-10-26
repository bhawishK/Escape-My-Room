# Headset grab

Issue 7 lets the Quest pick up a free object, move it, and put it down. The phone already holds objects by aiming. This adds the headset on the same acquire and release path, and keeps the hold exclusive: one person at a time.

## Which control

Checked on the Quest controls the page already uses.

| Control | Before alignment | After alignment |
| --- | --- | --- |
| A on the right controller, or X on the left (button 4) | Confirm alignment | Confirm alignment again |
| Grip, either hand (button 1, the squeeze) | Confirm alignment | Grab the object the target ray hits. Release the grip to put it down |
| Trigger | Press a button in the headset panel, or end VR when that panel is unavailable | Same. It does not grab |

The grip pose is the controller's `gripSpace`. The object is chosen with `targetRaySpace`, the pointing ray. Both are converted with the headset's stored alignment into room meters. Python does not convert them again.

## No jump

At the moment of the grab, Python remembers where the object sits relative to the grip. The object stays there. Later grip poses move it by the same amount the hand moved, including the hand's turn. Letting go leaves it where it is, in the air or on the floor. It is not passed to the phone.

A phone aim still slides the object on the floor, and only while the phone is the one holding it. A phone pose does not move an object the headset is holding. Disconnecting ends that person's hold only.

## What the other person sees

The shared state says who is holding it: `owner` is `mobile_master` or `vr_solver`. Both pages show that line, and both outline the object. A refused grab says **The other person is holding that object.** The owner and the object's place do not change.
