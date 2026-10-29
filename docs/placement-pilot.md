# Placement pilot

Issue 12. This is a practical check of where the box lands, not a formal study. The phone and the headset each put the box in three spots. The page records the accepted position and how far it is from that spot, in room metres.

## The spots

The stand-in room's furniture is in `assets/prepared-room/manifest.json`. Positions are the bottom centre. The box is a 0.20 m cube, so the target is where its bottom centre should be.

| Task | Target (x, y, z) | Counts as inside |
| --- | --- | --- |
| Desk | `(0, 0, -0.80)` | within 0.40 m left or right, 0.15 m forward or back, and 0.15 m up or down |
| Cabinet | `(1.4, 0, -0.90)` | within 0.30 m left or right, 0.15 m forward or back, and 0.15 m up or down |
| Floor | `(0, 0, 0.80)` | within 0.30 m left or right, 0.30 m forward or back, and 0.15 m up or down |

The desk spot is on the floor against the desk's front face (`z = -0.90`). The cabinet spot is on the floor against the cabinet's front face (`z = -1.00`). The floor spot is open floor, clear of both. The error is the distance outside that region. Inside the region, the error is 0. It is not measured in screen pixels.

## How to run one attempt

1. Connect the phone and the headset to the same room.
2. Press **Desk**, **Cabinet**, or **Floor**.
3. Pick up the box and let go at that spot. The phone puts it on the floor. The headset leaves it where the grip let go.
4. Read the line under the buttons. It says inside, or how many metres outside.
5. If the move felt wrong, type that in **How the move felt** before the next attempt. The note is stored with the release.
6. Repeat for the other two spots. Then the other person does the same three.
7. On the phone, tap **Send log**. On the headset page, **Download diagnostic report**. Each release is one `placement` record: the task, the attempt number, who let go, the room version, the tracking mode, the position, the error, how long the attempt took, and the note.

Letting go with no spot chosen is recorded as task `none`, so an accidental drop is visible.

## What is not changed

No aiming rule was changed. A phone release still keeps the box at its floor height. A headset release still keeps the grip height. The existing grab checks still cover that.

The desk and cabinet spots are on the floor in front of the furniture, because that is where the phone can put the box. Putting the box on the desk top would be a later change: add a desk-top region at `y = 0.75` and repeat only the desk task. That repeat has not been run, so this note does not say the current aiming is better or worse than another one.

## Limits to write down if they happen

Issue 10: if tracking is lost, the hold ends and the box stays. Issue 11: if the connection drops, the hold ends and the box stays. If either happens during an attempt, say so in the note. Restarting Python forgets the room. Reconnecting does not.
