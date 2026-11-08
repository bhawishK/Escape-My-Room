// The server's one physics simulation (#159): Havok, driven by Python over JSON lines.
//
// Python starts this process with the server and writes one JSON message per line to its standard
// input; the worker answers one JSON message per line on its standard output. It exits when its
// standard input closes, so it never outlives Python, however Python stops.
//
// Python → worker:
//   {"type": "load", "room_version": 1, "bodies": [{"id", "motion": "static" | "dynamic",
//     "size": {"width", "height", "depth"}, "position": {x, y, z}, "rotation": {x, y, z, w}}]}
//     Position is the bottom face's centre, as in the room's entities.
// Worker → Python:
//   {"type": "ready", "engine": "havok", "version": "1.3.14"} once Havok has loaded;
//   {"type": "loaded", "room_version": 1, "bodies": {"static": 1, "dynamic": 1}};
//   {"type": "error", "message": "..."} for a message it can't act on. If Havok can't load it
//   writes its reason to standard error and exits with code 1.

import HavokPhysics from '@babylonjs/havok';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const GRAVITY = [0, -9.81, 0];

const require = createRequire(import.meta.url);
const wasmPath = require.resolve('@babylonjs/havok/lib/esm/HavokPhysics.wasm');
// The package doesn't export its package.json; it is three folders up from the wasm.
const { version } = JSON.parse(readFileSync(join(wasmPath, '..', '..', '..', 'package.json'), 'utf8'));

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

let havok;
try {
  havok = await HavokPhysics({ wasmBinary: readFileSync(wasmPath) });
} catch (error) {
  process.stderr.write(`Havok failed to load: ${error instanceof Error ? error.message : error}\n`);
  process.exit(1);
}

/** Rotate `v` by the unit quaternion `q`: v' = v + 2w(u × v) + 2u × (u × v). */
function rotate(q, [x, y, z]) {
  const tx = 2 * (q.y * z - q.z * y);
  const ty = 2 * (q.z * x - q.x * z);
  const tz = 2 * (q.x * y - q.y * x);
  return [
    x + q.w * tx + (q.y * tz - q.z * ty),
    y + q.w * ty + (q.z * tx - q.x * tz),
    z + q.w * tz + (q.x * ty - q.y * tx),
  ];
}

/** The room's simulated bodies, replaced whole each time a room loads. */
class Room {
  constructor(bodies) {
    [, this.world] = havok.HP_World_Create();
    havok.HP_World_SetGravity(this.world, GRAVITY);
    this.bodies = new Map();
    this.shapes = [];
    for (const body of bodies) this.add(body);
  }

  add({ id, motion, size, position, rotation }) {
    const [, shape] = havok.HP_Shape_CreateBox(
      [0, 0, 0], [0, 0, 0, 1], [size.width, size.height, size.depth]);
    const [, body] = havok.HP_Body_Create();
    havok.HP_Body_SetShape(body, shape);
    havok.HP_Body_SetMotionType(
      body, motion === 'dynamic' ? havok.MotionType.DYNAMIC : havok.MotionType.STATIC);
    if (motion === 'dynamic') {
      const [, mass] = havok.HP_Shape_BuildMassProperties(shape);
      havok.HP_Body_SetMassProperties(body, mass);
    }
    // Havok places a body by its centre; the room places it by its bottom face's centre.
    const up = rotate(rotation, [0, size.height / 2, 0]);
    const centre = [position.x + up[0], position.y + up[1], position.z + up[2]];
    havok.HP_Body_SetQTransform(body, [centre, [rotation.x, rotation.y, rotation.z, rotation.w]]);
    havok.HP_World_AddBody(this.world, body, false);
    this.bodies.set(id, { body, motion });
    this.shapes.push(shape);
  }

  counts() {
    let dynamic = 0;
    for (const { motion } of this.bodies.values()) if (motion === 'dynamic') dynamic += 1;
    return { static: this.bodies.size - dynamic, dynamic };
  }

  release() {
    for (const { body } of this.bodies.values()) {
      havok.HP_World_RemoveBody(this.world, body);
      havok.HP_Body_Release(body);
    }
    for (const shape of this.shapes) havok.HP_Shape_Release(shape);
    havok.HP_World_Release(this.world);
  }
}

let room = null;

function handle(message) {
  if (message.type === 'load') {
    room?.release();
    room = new Room(message.bodies);
    send({ type: 'loaded', room_version: message.room_version, bodies: room.counts() });
  } else {
    send({ type: 'error', message: `Unknown message type: ${message.type}` });
  }
}

const lines = createInterface({ input: process.stdin });
lines.on('line', line => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    send({ type: 'error', message: 'A message was not JSON.' });
    return;
  }
  try {
    handle(message);
  } catch (error) {
    send({ type: 'error', message: error instanceof Error ? error.message : String(error) });
  }
});
// Python has gone, however it stopped.
lines.on('close', () => process.exit(0));

send({ type: 'ready', engine: 'havok', version });
