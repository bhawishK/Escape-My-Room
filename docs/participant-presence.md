# Participant presence

Issue 4 shows each person to the other one. The phone and the Quest already share one room. This adds a simple marker for the other person: where they are, and which way they face. It is not a body, a face, or a voice.

## What each device sends

A presence update is one role's own place. The phone cannot overwrite the headset, and the headset cannot overwrite the phone. The update does not move the desk, the box, or any other object. Moving an object does not change presence.

The position is room meters. The heading is radians about Y. Heading `0` faces the desk, along room `-Z`. Positive turns left.

- **Phone:** while the room view is open, the page sends the view's place and the phone's heading. With turning off, the heading stays `0`, facing the desk. Closing the room view sends `inactive`.
- **Quest:** after Confirm alignment, and only while immersive VR is tracking, the page converts the `local` viewer pose with that alignment and sends the room position and heading. Leaving VR, or standing there before confirmation, sends `inactive`.

Python stores the numbers as sent. It does not apply alignment a second time.

## How often

Each page sends at most 20 presence updates a second. If the socket already has 16 KiB waiting, that update is dropped. A tracked person who sends nothing for 1.5 seconds becomes `stale`: the marker stays where it was and turns faint. Disconnecting removes it (`lost`, no position). Joining, or opening the same role in a new tab, starts at `inactive` until the next update.

A timing check on an iPhone and a Quest has not been recorded yet.

## What each screen draws

Each page draws the other person's marker and hides its own, so the marker is not sitting in front of the camera. The phone marker is teal. The headset marker is amber. A short arrow shows the heading. `stale` keeps that marker and draws it faint. `inactive` and `lost` draw nothing.

The older phone step position is still the `pose` message. When a live phone presence exists, the screen shows the presence marker instead of that step sphere.
