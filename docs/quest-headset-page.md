# The headset page on Immersive Web SDK (#156)

The Quest opens **`/quest/`**. It is the headset's page built on [Immersive Web SDK](https://iwsdk.dev/) (`@iwsdk/core` 1.0.1), so it can use hands as well as controllers. The phone keeps the main page, `/`, which this work does not change. The headset path on `/` still works as before, as a fallback.

## Opening it

1. Build: `npm run build` in `frontend/` builds the phone's page and then the headset's (`npm run build:quest` builds the headset's alone). Python serves both from `frontend/dist`.
2. On the Quest, open `https://<the shared address>/quest/`, press **Connect headset**, then **Enter VR**.
3. For development, `npm run dev:quest` serves the headset page on port 5174 against Python on port 8000.

## Why it has its own build

IWSDK brings its own three.js, `super-three` (0.181 in IWSDK 1.0.1), and the phone's page uses three.js 0.186. If both copies loaded, Spark's splat could not be added to IWSDK's scene: three.js refuses objects made by another copy. So `vite.quest.config.ts` points every `three` import on the headset page, Spark's and the shared modules' included, at IWSDK's copy. Spark accepts three.js from 0.180. The phone's build, `vite.config.ts`, is unchanged.

## What the headset page reuses

It joins the same session as the phone's page, as the headset (`vr_solver`), with the shared modules unchanged: `session.ts`, `protocol.ts`, `alignment.ts`, `room.ts`, `grab.ts`, `room-map.ts`, `dom.ts` and `style.css`. Its own code is in `frontend/src/quest/`:

| File | What it does |
| --- | --- |
| `main.ts` | Starts the IWSDK world (`local` reference space, hand tracking, no locomotion), joins, aligns, loads the room, and runs each XR frame |
| `room-view.ts` | The room's objects, the Spark splat, the phone user's figure, rays and outlines, in IWSDK's scene |
| `hands.ts` | Reads each XR frame's head, controllers and hands (joints, the system's pinch) |
| `gestures.ts` | Hand poses, a hold-and-cool-down gate, nods and head shakes, and the gaze dwell |
| `hud.ts` | The line of text in front of the eyes (IWSDK sessions have no DOM overlay) |

## Using it in VR

| Action | Controllers | Hands |
| --- | --- | --- |
| Line the room up | A or X | Pinch, before the room is lined up (each new VR session, and a reset, ask again) |
| Move an object | Aim at it, squeeze the grip, let go to put it down | Aim the hand ray and pinch, or **look at it and pinch** |
| Throw an object | Let go of the grip while swinging | Open the pinch while swinging: it flies at your hand's speed (capped at 8 m/s) |
| Show something | — | **Point** with the index finger: its ray outlines what it is on |
| Pause in a calm view | — | Hold an **open palm** for 0.8 s: the room fades, a held object is put down, and nothing is aimed or taken; again to come back |
| Start a topic | Look at an object for 1.5 s | The same |
| Yes / no | Nod twice / shake twice | The same |

## How the gestures work

- **Pinch** is the session's own: the hand's `selectstart` and `selectend`. They settle a wavering pinch better than a distance threshold.
- **Point** and **open palm** come from the joints; a point draws its ray once held 0.2 s. A finger is straight when its tip is more than 1.4 times as far from the wrist as its knuckle. Pointing is the index straight with the others curled; an open palm is all four straight. A thumb tip within 2 cm of the index tip is a pinch, and wins over both.
- The **open palm** goes through a gate: it fires once it has been held 0.8 s, and again only after it is let go and 1.5 s have passed.
- **Nods and shakes**: two turns back of the head's tilt (yes) or turn (no), of at least 8° each, within 1.2 s. One look down, or a slow look around, is neither; facing backwards, the turn does not wrap at 180°. After one, two new turns are needed.
- **Look to start**: the head's ray resting 1.5 s on one object, furniture included but not the floor. The object is outlined from then until the gaze leaves it.
- **Lining up again**: a new VR session or a reset of the reference space has a new `local` origin, so the page clears the headset's saved alignment (`clear_alignment`). A pinch, or A, then lines the room up again.

## Still to do

- The gestures and look to start only show in the headset and on its page. Telling the phone (for example "Mum is looking at the piano") needs a new message to Python and the phone: #157. This work does not change the phone.
- Phase 1's measurements on a real Quest: the splat's frame rate here against `/`, and hands working.
- Tuning the thresholds with people other than the developer.
