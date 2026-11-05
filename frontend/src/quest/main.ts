/**
 * The headset's page (#156): the room in Immersive Web SDK, with hands as well as controllers.
 * It joins the same session as the phone's page, as the headset, and leaves the phone's page and
 * its build alone.
 */
import '../style.css';
import './quest.css';
import { ReferenceSpaceType, VERSION, World } from '@iwsdk/core';
import type * as THREE from 'three';
import { alignmentFromPose, roomDirection, roomOrientation, roomPoint, type CalibrationInput } from '../alignment';
import { element } from '../dom';
import { grabbedPosition, offsetOf, targetAlongRay } from '../grab';
import type { AlignmentState, Position, PresenceInput, RoomEntity, SessionState } from '../protocol';
import { RoomMap, type Spot } from '../room-map';
import { SessionClient } from '../session';
import { Dwell, GestureGate, HeadNods } from './gestures';
import { readFrame, type FrameSample, type InputSample, type Pose, type Ray } from './hands';
import { Hud } from './hud';
import { QuestRoom, type DrawnRay } from './room-view';

/** How often presence and a held object's grip go to Python. */
const PRESENCE_MS = 50;
const GRIP_MS = 100;
/** Resting the gaze this long on an object starts a topic about it. */
const DWELL_MS = 1500;
/** A gesture line in the headset stays this long. */
const SAID_MS = 2000;
/** Static objects this thin are the floor, which the gaze is not starting a topic about. */
const FLOOR_METRES = 0.05;

const connectButton = element<HTMLButtonElement>('connect');
const enterButton = element<HTMLButtonElement>('enter-vr');
const disconnectButton = element<HTMLButtonElement>('disconnect');
const sceneElement = element('scene');

let connected = false;
let busy = false;
let xrSupported = false;
let xrActive = false;
let state: SessionState | null = null;
/** The head's pose mapped to the floor centre, for lining up; null before a tracked frame. */
let latest: CalibrationInput | null = null;
let head: Pose | null = null;
let tracking: FrameSample['tracking'] = 'lost';
/** The hands whose pinch the session has selected. */
const pinching = new Set<XRInputSource>();
/** The input holding an object, and the offset that keeps the object from jumping to it. */
let holder: XRInputSource | null = null;
let grabOffset: Position | null = null;
let releasing: number | null = null;
/** Each input's holding and confirm last frame, to tell a press from a hold. */
const wasHolding = new WeakMap<XRInputSource, boolean>();
const wasConfirming = new WeakMap<XRInputSource, boolean>();
/** Shown in the headset after a loss, a reset or the phone leaving, until the person acts. */
let pauseNotice: string | null = null;
/** What a gesture last said, and until when. */
let said: { text: string; until: number } | null = null;
let calm = false;
const palmGate = new GestureGate<'open-palm'>({ holdMs: 800, cooldownMs: 1500 });
const nods = new HeadNods();
const dwell = new Dwell(DWELL_MS);
let lastPresence = -Infinity;
let presenceSent = false;
let lastGrip = -Infinity;
/** XR frames in the last five seconds, for the frame rate in the report. */
const frameTimes: number[] = [];
const gestureLog: { at: string; gesture: string }[] = [];

function showError(message: string | null): void {
  element('error').textContent = message ?? '';
  element('error').hidden = message === null;
}

const entities = (): RoomEntity[] => state?.room.entities ?? [];
const label = (id: string) => entities().find(entity => entity.id === id)?.label ?? id;
const aligned = (): AlignmentState | null =>
  state?.alignment.vr_solver.status === 'aligned' ? state.alignment.vr_solver : null;

function controls(): void {
  connectButton.disabled = connected || busy;
  disconnectButton.disabled = !connected;
  enterButton.disabled = !connected || !xrSupported || xrActive || busy;
  element('quest-map').classList.toggle('picking', connected);
  element('xr-status').textContent = !isSecureContext ? 'VR needs the trusted HTTPS link'
    : !navigator.xr ? 'WebXR is unavailable here. Open this page in the Quest browser.'
      : xrActive ? `In VR · ${inputMode()}`
        : xrSupported ? 'VR available' : 'VR unavailable on this device';
}

function inputMode(): 'hands' | 'controllers' | 'none' {
  const sources = Array.from(world?.session?.inputSources ?? []);
  if (sources.some(source => source.hand)) return 'hands';
  return sources.length ? 'controllers' : 'none';
}

function report(): void {
  const now = performance.now();
  while (frameTimes.length && now - frameTimes[0] > 5000) frameTimes.shift();
  element('report').textContent = JSON.stringify({
    iwsdk_version: VERSION,
    xr_supported: xrSupported,
    xr_active: xrActive,
    input_mode: inputMode(),
    input_sources: Array.from(world?.session?.inputSources ?? []).map(source => `${source.targetRayMode}:${source.handedness}`),
    positional_tracking: xrActive ? tracking : 'not-tested',
    xr_frame_rate_hz: Number((frameTimes.length / 5).toFixed(1)),
    room_version: state?.room.room_version ?? null,
    splat: sceneElement.dataset.splat === 'shown',
    gestures: gestureLog.slice(-20),
    user_agent: navigator.userAgent,
  }, null, 2);
}

function gesture(text: string, now: number): void {
  said = { text, until: now + SAID_MS };
  element('gesture-status').textContent = text;
  gestureLog.push({ at: new Date().toISOString(), gesture: text });
}

let world: World | null = null;
let room: QuestRoom | null = null;
const hud = new Hud();

const client = new SessionClient({
  state: applyState,
  connection: value => {
    connected = value;
    element('connection').textContent = value ? 'Connected · VR headset' : 'Not connected';
    if (!value) {
      state = null;
      holder = null;
      grabOffset = null;
      releasing = null;
      room?.predict(null);
    }
    controls();
  },
  selection: () => {},
  error: message => showError(message),
});

function applyState(next: SessionState): void {
  if (state && next.revision < state.revision) return;
  const phoneWas = state?.mobile_connected ?? false;
  const phoneHeld = state?.manipulation?.owner === 'mobile_master';
  state = next;
  map.showRoom(next.room);
  map.showPlayers(next.participants, 'vr_solver');
  room?.align(next.alignment.vr_solver);
  room?.showPhone(next.participants.mobile_master);
  const held = next.manipulation;
  room?.showControl(held?.entity ?? null);
  room?.glide(held?.owner === 'mobile_master' ? held.entity : null);
  const mine = held?.owner === 'vr_solver' ? held : null;
  if (!mine && grabOffset) {
    room?.predict(null);
    grabOffset = null;
    releasing = null;
  }
  // The pinch or grip let go before Python accepted the hold: put it down at once.
  if (mine && !holder) release();
  element('phone-status').textContent = next.mobile_connected ? 'Phone connected' : 'Waiting for phone';
  element('alignment-status').textContent = next.alignment.vr_solver.status === 'aligned'
    ? 'Aligned' : 'Not aligned · in VR press A, or pinch';
  if (phoneWas && !next.mobile_connected) {
    pauseNotice = phoneHeld ? 'Phone left. The object stays where it was.' : 'Phone left. The room is still here.';
  } else if (!phoneWas && next.mobile_connected && pauseNotice?.startsWith('Phone left')) {
    pauseNotice = null;
  }
  const status = element('room-status');
  if (!next.room.available) status.textContent = next.room.error ?? 'No room yet';
  void room?.sync(next).then(result => {
    if (!result || state?.room.room_version !== result.version) return;
    if (result.loaded) client.sendRoomLoaded(result.version);
    status.textContent = `Room ready · version ${result.version}`;
  }).catch(error => {
    const message = error instanceof Error ? error.message : 'The room could not be loaded.';
    status.textContent = message;
    showError(message);
  });
}

/** The person stands on the page's map: the alignment is turned and moved so they are there. */
function standOnMap(spot: Spot, heading: number | null): void {
  if (!connected) return;
  const now = latest ?? { yaw: 0, origin: { x: 0, y: 0, z: 0 } };
  const current = aligned();
  // A tap without a drag keeps the way the person faces now.
  const turn = heading ?? (current ? current.yaw - now.yaw : 0);
  const cosine = Math.cos(turn);
  const sine = Math.sin(turn);
  const { x, y, z } = now.origin;
  client.sendCalibration({
    yaw: Math.atan2(Math.sin(now.yaw + turn), Math.cos(now.yaw + turn)),
    origin: { x: cosine * x + sine * z + spot.x, y, z: -sine * x + cosine * z + spot.z },
  });
}
const map = new RoomMap(element('quest-map'), 'quest-map', { pick: standOnMap });

function confirmAlignment(): void {
  if (!connected) return;
  pauseNotice = null;
  client.sendCalibration(latest ?? { yaw: 0, origin: { x: 0, y: 0, z: 0 } });
}

function release(): void {
  const mine = state?.manipulation?.owner === 'vr_solver' ? state.manipulation : null;
  holder = null;
  if (!mine || releasing === mine.id) return;
  releasing = mine.id;
  client.sendRelease(mine.id);
}

/**
 * Tracking, the session or the reference space can no longer move a held object. A loss keeps
 * the alignment; a reset or leaving VR does not, because that origin is not the one lined up.
 */
function pause(reason: 'lost' | 'ended' | 'reset'): void {
  const wasHolding = state?.manipulation?.owner === 'vr_solver';
  release();
  grabOffset = null;
  if (reason === 'lost' && !wasHolding) return;
  pauseNotice = reason === 'lost'
    ? 'Tracking lost. The object stays where it was. Take hold again when the line is orange.'
    : 'Line the room up again: press A, or pinch. The object stays where it was.';
}

/** A ray in room metres, after alignment. */
function inRoom(alignment: AlignmentState, ray: Ray): Ray {
  return { origin: roomPoint(alignment, ray.origin), direction: roomDirection(alignment, ray.direction) };
}

/** The movable object a ray is on, and whether the phone holds it. */
function aimedAt(ray: Ray | null): { hit: string | null; blocked: boolean } {
  const alignment = aligned();
  if (!ray || !alignment) return { hit: null, blocked: false };
  const hit = targetAlongRay(inRoom(alignment, ray).origin, inRoom(alignment, ray).direction, entities());
  const blocked = hit !== null && state?.manipulation?.owner === 'mobile_master' && state.manipulation.entity === hit;
  return { hit: blocked ? null : hit, blocked };
}

/** Any object the head looks at, for starting a topic: furniture too, but not the floor. */
function lookedAt(): string | null {
  const alignment = aligned();
  if (!head || !alignment) return null;
  const forward = roomDirection(alignment, rayDirection(head));
  const topics = entities()
    .filter(entity => entity.kind === 'movable' || entity.size.height > FLOOR_METRES)
    // Every object counts here, not only the ones that can be picked up.
    .map(entity => ({ ...entity, kind: 'movable' as const, selectable: true }));
  return targetAlongRay(roomPoint(alignment, head.position), forward, topics, 6);
}

function rayDirection(pose: Pose): Position {
  const { x, y, z, w } = pose.orientation;
  return { x: -2 * (w * y + x * z), y: 2 * (w * x - y * z), z: -1 + 2 * (x * x + y * y) };
}

/** Starts holding with `input`: before alignment it lines up; after, it takes what it aims at. */
function takeHold(input: InputSample, gazeTarget: string | null): void {
  const alignment = aligned();
  if (!alignment) {
    confirmAlignment();
    return;
  }
  pauseNotice = null;
  const { hit, blocked } = aimedAt(input.ray);
  // Look and pinch: a hand aimed at nothing takes what the head is looking at.
  const target = hit ?? (input.kind === 'hand' && !blocked && gazeTarget !== null ? movable(gazeTarget) : null);
  const version = state?.room.room_version;
  const entity = entities().find(candidate => candidate.id === target);
  const grip = input.grip ?? (input.ray ? { position: input.ray.origin, orientation: head?.orientation ?? { x: 0, y: 0, z: 0, w: 1 } } : null);
  if (blocked) {
    said = { text: 'The other person is holding that object.', until: performance.now() + SAID_MS };
    return;
  }
  if (!entity || !grip || version === null || version === undefined) return;
  const position = roomPoint(alignment, grip.position);
  const orientation = roomOrientation(alignment, grip.orientation);
  holder = input.source;
  grabOffset = offsetOf(position, orientation, entity.position);
  client.sendAcquire(version, entity.id, { position, orientation });
}

/** The gaze target when it can be picked up, else null. */
function movable(id: string): string | null {
  const entity = entities().find(candidate => candidate.id === id);
  const phoneHolds = state?.manipulation?.owner === 'mobile_master' && state.manipulation.entity === id;
  return entity?.kind === 'movable' && entity.selectable && !phoneHolds ? id : null;
}

/** Each XR frame: tracking, holding, gestures, presence and what the headset shows. */
function frame(xrFrame: XRFrame, time: number): void {
  const reference = world?.xrReferenceSpace;
  if (!reference) return;
  frameTimes.push(performance.now());
  const sample = readFrame(xrFrame, reference, pinching);
  if (sample.tracking !== tracking) {
    tracking = sample.tracking;
    if (tracking !== 'tracked') pause('lost');
  }
  head = sample.head;
  if (head) latest = alignmentFromPose(head.position, head.orientation);
  const alignment = aligned();

  // Gestures from the head and hands.
  const looking = lookedAt();
  const rest = dwell.update(looking, time);
  if (rest.started && rest.target) gesture(`Looking at ${label(rest.target)} · a topic to talk about`, time);
  if (head) {
    const answer = nods.update(head.orientation, time);
    if (answer) gesture(answer === 'yes' ? 'Yes (nod)' : 'No (shake)', time);
  }
  const palm = palmGate.update(sample.inputs.some(input => input.pose === 'open-palm') ? 'open-palm' : 'none', time);
  if (palm) {
    calm = !calm;
    room?.setCalm(calm);
    gesture(calm ? 'Paused · calm view (open palm again to come back)' : 'Back in the room', time);
  }

  // Holding: a press of the grip or a pinch takes hold; letting go puts the object down.
  for (const input of sample.inputs) {
    if (input.confirm && !wasConfirming.get(input.source)) confirmAlignment();
    wasConfirming.set(input.source, input.confirm);
    const before = wasHolding.get(input.source) ?? false;
    wasHolding.set(input.source, input.holding);
    if (input.holding && !before && !holder) takeHold(input, looking);
    if (!input.holding && before && holder === input.source) release();
  }
  const mine = state?.manipulation?.owner === 'vr_solver' ? state.manipulation : null;
  const holding = sample.inputs.find(input => input.source === holder);
  if (holder && !holding) release();
  if (mine && holding && grabOffset && alignment) {
    const grip = holding.grip ?? (holding.ray && head ? { position: holding.ray.origin, orientation: head.orientation } : null);
    if (grip) {
      const position = roomPoint(alignment, grip.position);
      const orientation = roomOrientation(alignment, grip.orientation);
      room?.predict(mine.entity, grabbedPosition(position, orientation, grabOffset));
      if (time - lastGrip >= GRIP_MS && client.sendGrip(mine.id, { position, orientation })) lastGrip = time;
    }
  }

  // Rays: each controller's and hand's, and a pointing finger's.
  const drawn: DrawnRay[] = [];
  let highlighted: string | null = null;
  for (const input of sample.inputs) {
    const ray = input.fingerRay ?? input.ray;
    if (!ray || (input.kind === 'hand' && !input.fingerRay && !input.holding)) continue;
    const { hit, blocked } = aimedAt(ray);
    highlighted ??= hit;
    drawn.push({ ...ray, look: blocked ? 'blocked' : hit ? 'target' : 'miss' });
  }
  room?.showRays(drawn);
  room?.showHighlight(mine ? null : highlighted ?? rest.target);

  publishPresence(time);
  showHud(time, drawn.some(ray => ray.look === 'blocked'));
  if (Math.floor(time / 500) !== Math.floor((time - 16) / 500)) report();
}

function publishPresence(time: number): void {
  if (!connected) return;
  const alignment = aligned();
  const presence: PresenceInput | null = xrActive && head && alignment ? {
    tracking_status: 'tracked',
    position: roomPoint(alignment, head.position),
    heading: Math.atan2(-roomDirection(alignment, rayDirection(head)).x, -roomDirection(alignment, rayDirection(head)).z),
  } : null;
  if (!presence) {
    if (presenceSent) presenceSent = !client.sendPresence({ tracking_status: 'inactive', position: null, heading: null });
    return;
  }
  if (time - lastPresence < PRESENCE_MS || !client.sendPresence(presence)) return;
  lastPresence = time;
  presenceSent = true;
}

function showHud(time: number, blocked: boolean): void {
  const held = state?.manipulation ?? null;
  if (said && time > said.until) said = null;
  const text = pauseNotice
    ?? (blocked ? 'The other person is holding that object.' : null)
    ?? (held?.owner === 'mobile_master' ? `Phone is holding ${label(held.entity)}` : null)
    ?? (held?.owner === 'vr_solver' ? `Holding ${label(held.entity)} · let go to put it down` : null)
    ?? said?.text
    ?? (aligned() ? null : 'Stand where you like, then press A or pinch to line up');
  hud.show(text, text === said?.text);
}

async function start(): Promise<void> {
  try {
    world = await World.create(sceneElement, {
      // The page offers VR from its own button, once connected.
      xr: {
        offer: 'none',
        // The alignment maths takes the `local` space, as the phone's page did for the headset.
        referenceSpace: { type: ReferenceSpaceType.Local, required: true },
        features: { handTracking: true },
      },
      render: { near: 0.01, far: 100, camera: { position: [0, 1.5, 0], lookAt: [0, 1.1, -1.2] } },
      features: { locomotion: false, grabbing: false, spatialUI: false },
    });
  } catch {
    showError('The 3D view could not start. Enable WebGL/hardware acceleration and reload.');
    return;
  }
  // One three.js copy draws everything on this page (vite.quest.config.ts); its types differ only in version.
  const scene = world.scene as unknown as THREE.Scene;
  const renderer = world.renderer as unknown as THREE.WebGLRenderer;
  room = new QuestRoom(scene, renderer, sceneElement);
  (world.camera as unknown as THREE.Camera).add(hud.sprite);
  if (state) applyState(state);
  world.onXRFrame((xrFrame, _delta, time) => frame(xrFrame, time * 1000));
  let last: number | null = null;
  // Glides need drawing time outside VR too.
  const glide = (now: number) => {
    room?.tick(last === null ? 0 : now - last);
    last = now;
    requestAnimationFrame(glide);
  };
  requestAnimationFrame(glide);
  renderer.xr.addEventListener('sessionstart', () => {
    xrActive = true;
    room?.setPresenting(true);
    const session = renderer.xr.getSession();
    session?.addEventListener('selectstart', event => { if (event.inputSource.hand) pinching.add(event.inputSource); });
    session?.addEventListener('selectend', event => { pinching.delete(event.inputSource); });
    session?.addEventListener('inputsourceschange', () => { controls(); report(); });
    world?.xrReferenceSpace?.addEventListener('reset', () => {
      latest = null;
      pause('reset');
    });
    controls();
  });
  renderer.xr.addEventListener('sessionend', () => {
    xrActive = false;
    pinching.clear();
    pause('ended');
    room?.setPresenting(false);
    room?.showRays([]);
    hud.show(null);
    controls();
    report();
  });
  xrSupported = Boolean(isSecureContext && await navigator.xr?.isSessionSupported('immersive-vr').catch(() => false));
  controls();
  report();
}

connectButton.addEventListener('click', () => {
  busy = true;
  showError(null);
  controls();
  void client.join('vr_solver').catch(error => {
    showError(error instanceof Error ? error.message : 'Unable to connect. Try again.');
  }).finally(() => {
    busy = false;
    controls();
  });
});
disconnectButton.addEventListener('click', () => {
  client.leave();
  world?.exitXR();
});
// Asked inside the button press: the browser allows VR only from a person's tap.
enterButton.addEventListener('click', () => world?.launchXR());

controls();
void start();
