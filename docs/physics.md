# Shared physics (#159)

The server runs **one** physics simulation of the room, so the phone and the headset always see the same thing. Neither device simulates anything: they draw what the server sends. The engine is [Havok](https://www.npmjs.com/package/@babylonjs/havok) (MIT licence), the same engine Immersive Web SDK uses on the headset. It runs in a small Node.js process, the **physics worker**, beside Python.

## What works so far

- **The worker (#160):** Python starts it with the server and stops it with the server. It also exits by itself when its input closes, so it never outlives Python, even when Python is killed. Each room that is loaded or made live is loaded into it:
  - the floor (static entities no thicker than 5 cm) is a static body;
  - each movable object is a dynamic box of its size;
  - furniture isn't solid yet.
- **Falling (#161):**
  - When the headset lets go of an object, it falls from where it was let go, bounces a little and settles. While it moves, both devices get its position and rotation about 30 times a second. Once it is at rest (slower than 5 cm/s for a quarter of a second), they get its final place, and then nothing more until something changes.
  - A rejoining device sees where it rests.
  - The phone's let-go works exactly as before: the object lands at its floor height, at rest. A direct move (`entity_transform`) also puts it down at rest.
  - Taking hold of a moving object stops it. While it is held, the session moves it and physics leaves it alone.
- **Next:** throwing (#162) and catching (#163).

## What objects are made of

A movable entity in a room's `manifest.json` can say what it is made of. Any value left out uses the default.

```json
"physics": {"mass": 1.0, "friction": 0.5, "restitution": 0.3}
```

| Value | Default | Meaning |
| --- | --- | --- |
| `mass` | 1 kg | Up to 1000 kg |
| `friction` | 0.5 | 0 is ice; it meets the floor's friction (0.6) halfway |
| `restitution` | 0.3 | 0 thuds, 1 bounces back as high as it fell. A bouncy object bounces on any floor |

## The status

Every `welcome` and `state` message has `state.physics`:

| Field | Meaning |
| --- | --- |
| `status` | `starting` until the worker is ready, then `running`, or `unavailable` |
| `engine` | `havok` once the worker has started |
| `reason` | Why physics is unavailable, for example `The physics worker exited with code 1: …` with the worker's last error line; otherwise `null` |
| `room_version` | The room the worker has loaded, or `null` |
| `bodies` | How many bodies that room has, as `{"static": 1, "dynamic": 1}`, or `null` |
| `moving` | The objects physics is moving now, such as `["box"]`; `[]` once everything is at rest |

If the worker can't start, or exits, the status says `unavailable` with its reason. Holds, grips, carries and releases then work exactly as they did before physics. A physics failure never stops the session.

## Running it

- Install the worker's packages once: `npm ci` in `physics/`. The GPU desktop's `update.sh` and setup wizard do this.
- Python finds Node on its `PATH`.
- Two settings change this, mainly for tests:
  - `ESCAPE_ROOM_NODE`: the Node executable to use.
  - `ESCAPE_ROOM_PHYSICS_WORKER`: another worker script to run.
- To try the worker by hand, send it JSON lines:

  ```sh
  cd physics
  echo '{"type":"load","room_version":1,"bodies":[]}' | node worker.mjs
  ```

## How Python and the worker talk

One JSON message per line, over the worker's standard input and output. The messages are listed at the top of `physics/worker.mjs`.
- **Python → worker:** `load` a room, then, for one object, `hold`, `release` (let go here; it falls) or `place` (put here, at rest).
- **Worker → Python:** `poses` while anything moves.
- **Out-of-date poses:** each command counts up an `epoch` for its object, and the worker echoes it in that object's poses. Python ignores poses from before its latest command, such as the last ones of a fall someone has since caught.

Python writes to and reads from the worker on background threads. Its event loop never waits on the worker, and uvicorn's event loop on Windows can't run asyncio subprocesses anyway.

## Tests

`tests/test_physics_fall.py` checks that:
- a box let go 1 m up reaches the floor within 0.8 s, rests on it, and is reported about 30 times a second, then not at all;
- a rejoin sees where it rests;
- without physics, a let-go box stays where it was;
- a room can make its box bouncier.

`tests/test_physics.py` checks over the session WebSocket that:
- physics runs with the room's floor and box;
- it reloads when a room is made live;
- a worker that can't start, or that dies, leaves physics unavailable with its reason while the phone can still carry the box.

`tests/fake_physics_worker.mjs` is a worker that dies on purpose.

## Why the server, and why Havok

- **One authority:** two engines, one on each device, would drift apart. A low-end phone shouldn't spend anything on physics.
- **Same engine as the headset:** later, the headset can predict a throw locally with Immersive Web SDK's Havok and match the server.
- **Room meshes:** Havok can use a triangle mesh, such as the room's scan, as a static collider.
- **The fallback was MuJoCo** inside Python. Havok ran in Node at the first check, a box let go at 1 m coming to rest on the floor, so the fallback wasn't needed.
