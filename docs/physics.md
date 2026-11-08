# Shared physics (#159)

The server runs **one** physics simulation of the room, so the phone and the headset always see the same thing. Neither device simulates anything: they draw what the server sends. The engine is [Havok](https://www.npmjs.com/package/@babylonjs/havok) (MIT licence), the same engine Immersive Web SDK uses on the headset. It runs in a small Node.js process, the **physics worker**, beside Python.

## What works so far (#160)

- Python starts the worker with the server and stops it with the server. The worker also exits by itself when its input closes, so it never outlives Python, even when Python is killed.
- Each room that is loaded or made live is loaded into the worker:
  - the floor (static entities no thicker than 5 cm) is a static body;
  - each movable object is a dynamic box of its size;
  - furniture isn't solid yet.
- The session state carries the physics status, which both devices receive (see below).
- Nothing moves differently yet. Falling (#161), throwing (#162) and catching (#163) come next.

## The status

Every `welcome` and `state` message has `state.physics`:

| Field | Meaning |
| --- | --- |
| `status` | `starting` until the worker is ready, then `running`, or `unavailable` |
| `engine` | `havok` once the worker has started |
| `reason` | Why physics is unavailable, for example `The physics worker exited with code 1: …` with the worker's last error line; otherwise `null` |
| `room_version` | The room the worker has loaded, or `null` |
| `bodies` | How many bodies that room has, as `{"static": 1, "dynamic": 1}`, or `null` |

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

One JSON message per line, over the worker's standard input and output. The messages are listed at the top of `physics/worker.mjs`. Python reads the worker's output on background threads, because uvicorn's event loop on Windows can't run asyncio subprocesses.

## Tests

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
