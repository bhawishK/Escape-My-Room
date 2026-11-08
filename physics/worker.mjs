// The server's one physics simulation (#159): Havok, driven by Python over JSON lines.
//
// Python starts this process with the server and writes one JSON message per line to its standard
// input; the worker answers one JSON message per line on its standard output. It exits when its
// standard input closes, so it never outlives Python, however Python stops.
//
// Poses are the room's: position is the bottom face's centre, rotation an (x, y, z, w) quaternion.
// Every command about one body carries Python's `epoch` for it, which the worker echoes in that
// body's poses, so Python can tell poses from before its latest command and ignore them.
//
// Python → worker:
//   {"type": "load", "room_version": 1, "bodies": [{"id", "motion": "static" | "dynamic",
//     "size": {"width", "height", "depth"}, "position", "rotation", "epoch",
//     "material": {"mass"?, "friction"?, "restitution"?} | null}]}
//   {"type": "hold", "id", "epoch"}: someone holds it; it leaves the simulation.
//   {"type": "release", "id", "epoch", "position", "rotation"}: let go here; it falls from rest.
//   {"type": "place", "id", "epoch", "position", "rotation"}: put here, at rest.
// Worker → Python:
//   {"type": "ready", "engine": "havok", "version": "1.3.14"} once Havok has loaded;
//   {"type": "loaded", "room_version": 1, "bodies": {"static": 1, "dynamic": 1}};
//   {"type": "poses", "bodies": [{"id", "epoch", "position", "rotation"}], "moving": ["box"]}
//     about 30 times a second while anything moves, a body knocked by another included; the
//     last one has "moving": [] and gives where each body came to rest;
//   {"type": "error", "message": "..."} for a message it can't act on. If Havok can't load it
//   writes its reason to standard error and exits with code 1.

import HavokPhysics from '@babylonjs/havok';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const GRAVITY = [0, -9.81, 0];
const STEP = 1 / 60;
// Poses go to Python every this many steps: 30 a second.
const STEPS_PER_POSE = 2;
// A body is at rest once it has moved slower than this for REST_STEPS steps in a row.
const REST_SPEED = 0.05; // m/s
const REST_SPIN = 0.2; // rad/s
const REST_STEPS = 15;
// What a body is made of when the room doesn't say.
const DEFAULT_MATERIAL = { mass: 1, friction: 0.5, restitution: 0.3 };
const FLOOR_MATERIAL = { friction: 0.6, restitution: 0 };

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

const length = ([x, y, z]) => Math.hypot(x, y, z);

/** One simulated body and what Python last told the worker about it. */
class Body {
  constructor(world, { id, motion, size, position, rotation, material, epoch }) {
    this.id = id;
    this.world = world;
    this.size = size;
    this.dynamic = motion === 'dynamic';
    this.epoch = epoch ?? 0;
    this.held = false;
    this.still = 0;
    [, this.shape] = havok.HP_Shape_CreateBox(
      [0, 0, 0], [0, 0, 0, 1], [size.width, size.height, size.depth]);
    // The room's values where it gives them, the defaults otherwise.
    const made = { ...(this.dynamic ? DEFAULT_MATERIAL : FLOOR_MATERIAL) };
    for (const [key, value] of Object.entries(material ?? {})) if (value != null) made[key] = value;
    // A bouncy object bounces on any floor, and friction meets the floor's halfway.
    havok.HP_Shape_SetMaterial(this.shape, [
      made.friction, made.friction, made.restitution,
      havok.MaterialCombine.GEOMETRIC_MEAN, havok.MaterialCombine.MAXIMUM,
    ]);
    [, this.body] = havok.HP_Body_Create();
    havok.HP_Body_SetShape(this.body, this.shape);
    if (this.dynamic) {
      // Havok gives the inertia for a mass of 1, so only the mass changes.
      const [, [centre, , inertia, orientation]] = havok.HP_Shape_BuildMassProperties(this.shape);
      havok.HP_Body_SetMassProperties(this.body, [centre, made.mass, inertia, orientation]);
    }
    havok.HP_Body_SetMotionType(
      this.body, this.dynamic ? havok.MotionType.DYNAMIC : havok.MotionType.STATIC);
    this.put(position, rotation);
    havok.HP_World_AddBody(world, this.body, this.dynamic);
  }

  /** Place it by its bottom face's centre, still. */
  put(position, rotation) {
    const up = rotate(rotation, [0, this.size.height / 2, 0]);
    havok.HP_Body_SetQTransform(this.body, [
      [position.x + up[0], position.y + up[1], position.z + up[2]],
      [rotation.x, rotation.y, rotation.z, rotation.w],
    ]);
    if (this.dynamic) {
      havok.HP_Body_SetLinearVelocity(this.body, [0, 0, 0]);
      havok.HP_Body_SetAngularVelocity(this.body, [0, 0, 0]);
    }
    this.still = 0;
  }

  setMotion(motionType, active) {
    havok.HP_Body_SetMotionType(this.body, motionType);
    havok.HP_Body_SetActivationState(
      this.body, active ? havok.ActivationState.ACTIVE : havok.ActivationState.INACTIVE);
  }

  pose() {
    const [, [centre, [x, y, z, w]]] = havok.HP_Body_GetQTransform(this.body);
    const rotation = { x, y, z, w };
    const up = rotate(rotation, [0, this.size.height / 2, 0]);
    return {
      id: this.id,
      epoch: this.epoch,
      position: { x: centre[0] - up[0], y: centre[1] - up[1], z: centre[2] - up[2] },
      rotation,
    };
  }

  /** True when it moves slower than a body at rest does. */
  slow() {
    const [, velocity] = havok.HP_Body_GetLinearVelocity(this.body);
    const [, spin] = havok.HP_Body_GetAngularVelocity(this.body);
    return length(velocity) < REST_SPEED && length(spin) < REST_SPIN;
  }

  /** True once it has been still for long enough; then it is put to sleep. */
  settled() {
    this.still = this.slow() ? this.still + 1 : 0;
    if (this.still < REST_STEPS) return false;
    havok.HP_Body_SetLinearVelocity(this.body, [0, 0, 0]);
    havok.HP_Body_SetAngularVelocity(this.body, [0, 0, 0]);
    havok.HP_Body_SetActivationState(this.body, havok.ActivationState.INACTIVE);
    return true;
  }

  /** Free its Havok handles. */
  dispose() {
    havok.HP_World_RemoveBody(this.world, this.body);
    havok.HP_Body_Release(this.body);
    havok.HP_Shape_Release(this.shape);
  }
}

/** The room's simulated bodies, replaced whole each time a room loads. */
class Room {
  constructor(bodies) {
    [, this.world] = havok.HP_World_Create();
    havok.HP_World_SetGravity(this.world, GRAVITY);
    havok.HP_World_SetIdealStepTime(this.world, STEP);
    this.bodies = new Map(bodies.map(body => [body.id, new Body(this.world, body)]));
    // Bodies falling, sliding or tumbling: only they are reported.
    this.moving = new Set();
    this.timer = null;
    this.steps = 0;
  }

  counts() {
    let dynamic = 0;
    for (const body of this.bodies.values()) if (body.dynamic) dynamic += 1;
    return { static: this.bodies.size - dynamic, dynamic };
  }

  body({ id, epoch }) {
    const body = this.bodies.get(id);
    if (!body?.dynamic) throw new Error(`No moving body ${id}.`);
    body.epoch = epoch;
    return body;
  }

  hold(message) {
    const body = this.body(message);
    // Python moves it while it is held; nothing pushes it, and it isn't reported.
    body.held = true;
    body.setMotion(havok.MotionType.KINEMATIC, false);
    this.moving.delete(body);
    this.report();
  }

  letGo(message) {
    const body = this.body(message);
    body.held = false;
    body.setMotion(havok.MotionType.DYNAMIC, true);
    body.put(message.position, message.rotation);
    this.moving.add(body);
    this.run();
  }

  place(message) {
    const body = this.body(message);
    body.held = false;
    body.setMotion(havok.MotionType.DYNAMIC, false);
    body.put(message.position, message.rotation);
    this.moving.delete(body);
    this.report();
  }

  /** Step in real time while anything moves. */
  run() {
    if (this.timer !== null) return;
    let last = performance.now();
    let owed = 0;
    this.timer = setInterval(() => {
      const now = performance.now();
      // Catch up after a late tick, but never more than a quarter of a second at once.
      owed = Math.min(owed + (now - last) / 1000, 0.25);
      last = now;
      while (owed >= STEP && this.moving.size > 0) {
        owed -= STEP;
        havok.HP_World_Step(this.world, STEP);
        this.steps += 1;
        // A body knocked by a moving one starts moving too.
        for (const body of this.bodies.values()) {
          if (body.dynamic && !body.held && !this.moving.has(body) && !body.slow()) {
            this.moving.add(body);
          }
        }
        const settled = [...this.moving].filter(body => body.settled());
        for (const body of settled) this.moving.delete(body);
        if (settled.length > 0 || this.steps % STEPS_PER_POSE === 0) this.report(settled);
      }
      if (this.moving.size === 0) this.stop();
    }, STEP * 1000);
  }

  /** Send the moving bodies' poses, and those of any that just came to rest. */
  report(settled = []) {
    const bodies = [...new Set([...this.moving, ...settled])].map(body => body.pose());
    send({ type: 'poses', bodies, moving: [...this.moving].map(body => body.id) });
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  /** Free its Havok handles. */
  dispose() {
    this.stop();
    for (const body of this.bodies.values()) body.dispose();
    havok.HP_World_Release(this.world);
  }
}

let room = null;

function handle(message) {
  if (message.type === 'load') {
    room?.dispose();
    room = new Room(message.bodies);
    send({ type: 'loaded', room_version: message.room_version, bodies: room.counts() });
    return;
  }
  if (room === null) throw new Error('No room is loaded.');
  if (message.type === 'hold') room.hold(message);
  else if (message.type === 'release') room.letGo(message);
  else if (message.type === 'place') room.place(message);
  else throw new Error(`Unknown message type: ${message.type}`);
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
