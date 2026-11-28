# Exit guidance

Issue #275. In a drill, the commander gets the occupant out of the room with one point and one pinch. The system then guides the phone user there with arrows, along a walkable route round the furniture and the fire.

It was built in five parts on one branch:

| Part | Issue | What |
| --- | --- | --- |
| Exits from the room's layout | #280 | Each door and window is an exit, anchored on the floor just inside it |
| The route | #281 | Python works out the walkable route to the chosen exit and shares it with both devices |
| Point and confirm | #282 | The headset points at a door and pinches "Exit · guide here" |
| The phone's arrows | #283 | Chevrons, an edge arrow, the distance left, and "You're out" |
| The commander's view and the log | #284 | The route and the occupant's progress on the headset, logged for the pilot |

## Using it

1. **Line the room up** on both devices, as for a drill.
2. **Point at a door** on the headset, with the index finger or a controller. This works in the dollhouse or at life size.
   - Pointing at the opening counts, and so does pointing at the floor just inside it.
   - The exit's outline turns yellow, and **Exit · guide here** floats over it.
3. **Pinch** to confirm. This must be while the offer shows, or within 0.8 s of the ray leaving it, so the pinch that ends the pointing still counts.
   - The outline turns green.
   - The headset says "Guiding the phone user to the door".
4. **The phone guides its user.** They see:
   - green chevrons on the floor along the route;
   - "Exit 3.2 m · follow the arrows";
   - an arrow at the screen's edge when the way on is out of sight.

   All of it updates as they walk.
5. **Arrival.** Within 0.5 m of the exit, the phone says **You're out** and the headset says "The phone user is out".
6. **To stop:** pinch **Guide** on the wrist menu's Drill page. It shows "Guiding · off" while guiding. Pointing at another exit and pinching guides to that one instead.

The phone sees nothing before the commander confirms an exit. The old pinch-a-spot guide and its straight strip (#248, #273) are gone.

| The phone says | Meaning |
| --- | --- |
| Finding your way out… | An exit is chosen, but the phone's position isn't known yet |
| Exit 3.2 m · follow the arrows | Following the route; the distance is what's left of it |
| No clear way to the exit · listen to the commander | Furniture or the fire leaves no walkable way. The commander guides by voice |
| You're out | Within 0.5 m of the exit |

## How it works

- **Exits** (`backend/room_exits.py`) come from the room's `layout.json`: SpatialLM's walls and openings (#270).
  - Each door and window is put on the wall its centre is nearest to.
  - Its anchor is 0.4 m inside it, on the floor, and at least 0.3 m from a corner.
  - They go to both pages with the room, as `room.exits`.
  - A room without a usable layout has none. #276 will fill them from AI for any room; room 10's layout works today.
- **The route** (`backend/route.py`, `backend/guidance.py`) is worked out by Python:
  - on a 10 cm grid of the floor;
  - keeping 0.25 m from furniture and the walls, and 0.6 m from anything on fire;
  - by A*, then straightened into a few legs.

  It is recomputed when the phone moves 10 cm or more, furniture moves, or a fire starts or stops, but no more than twice a second, except a fire change, which reroutes at once. It is shared state, `room.guidance`, so both devices draw the same route.
- **The headset** (`frontend/src/quest/exits.ts`) tests its ray against each opening (with a 0.25 m margin) and against the floor within 0.6 m of each anchor. It sends `guide_exit`; only the headset may, and only an exit the room has.
- **The phone** (`frontend/src/exit-route.ts`) draws the route from where it stands now, since Python's starting point is up to half a second old. It places a chevron every 0.5 m and points the edge arrow 1.5 m along the route.
- **Logged for the pilot:**
  - each exit chosen or cleared (`guide`);
  - each new route and its status (`route`).

  A run's summary says which exit and `out_seconds`, the time from the choice to the arrival. See [session logs](hazards.md#session-logs-259).

### Values to tune on the devices

| Value | Where | Now | Change it if |
| --- | --- | --- | --- |
| `INSET` | `backend/room_exits.py` | 0.4 m | The route ends too far from or too close to the door |
| `CLEARANCE`, `FIRE_CLEARANCE` | `backend/route.py` | 0.25 m, 0.6 m | Routes squeeze past furniture, or find no way in a small room |
| `ARRIVED_METRES` | `backend/guidance.py` | 0.5 m | "You're out" comes too early or never |
| `EXIT_MARGIN_METRES`, `EXIT_FLOOR_METRES` | `frontend/src/quest/exits.ts` | 0.25 m, 0.6 m | The door is hard to point at, or pointing near it offers it by mistake |
| `OFFER_GRACE_MS` | `frontend/src/quest/exits.ts` | 800 ms | The confirming pinch misses, or a later pinch confirms by mistake |
| `CHEVRON_SPACING_METRES` | `frontend/src/exit-route.ts` | 0.5 m | Chevrons are too dense or too sparse on the phone |

## The device check

Run on 28 November 2026 with the iPhone and the Quest 3, in the test room (`assets/splat-room`). Its door is written by hand for the tests, so this checked the flow, not a real door's position. Room 10, or a newly filmed room once #276 gives it exits, is still to do.

| Check | Result |
| --- | --- |
| The door shows as an exit outline in the dollhouse | Works (28 Nov, test room) |
| Pointing at the door in the dollhouse offers "Exit · guide here"; a pinch confirms it | Works (28 Nov, test room) |
| The same at life size | Works (28 Nov, test room) |
| The offer goes when the ray leaves the door | Works (28 Nov, test room) |
| The phone shows nothing before the confirm | Works (28 Nov, test room) |
| The phone's chevrons go round the furniture to the door | Works (28 Nov, test room) |
| The edge arrow shows when the phone faces away, and points the right way | Works (28 Nov, test room) |
| The distance goes down as the phone user walks | Works (28 Nov, test room) |
| "You're out" at the door, on the phone and the headset | Works (28 Nov, test room) |
| Guide on the wrist menu stops it on both devices | Works (28 Nov, test room) |
| Pointing at other walls or furniture, or moving the box, chooses no exit | Works (28 Nov, test room) |
| With a fire started, the route keeps clear of it | Not yet: the test room has no fire made |
| The session log has the exit, the routes and `out_seconds` | Not yet: needs a drill run |
| All of it in room 10, or a filmed room with a real door | Not yet |
