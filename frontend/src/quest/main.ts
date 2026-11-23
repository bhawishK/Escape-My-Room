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
import { errorMessage } from '../api';
import { element } from '../dom';
import { RAY_REACH_METERS, grabbedPosition, offsetOf, rayForward, targetAlongRay } from '../grab';
import type {
  AlignmentState, CatalogueItem, FurnitureJob, Position, PresenceInput, RoomEntity, Rotation, SessionState,
} from '../protocol';
import { floorPieces } from '../room';
import { RoomMap, type Spot } from '../room-map';
import { SessionClient } from '../session';
import { VoiceCall, voiceLine, voiceNote } from '../voice';
import {
  DollhouseCarry, DollhouseScaling, GripSmoother, HAND_METRES, dollhousePlacement, fromDollhouse, handInDollhouse,
  looksToTake,
  throwInRoom, yawOf, orientationFromDollhouse, scaleLabel, velocityFromDollhouse,
} from './dollhouse';
import { floorSpot } from '../guide';
import { Dictation } from './dictation';
import { drillLine, drillObjects, drillPlaying, type DrillState } from './drill';
import { Dwell, FIST_COOLDOWN_MS, FIST_HOLD_MS, GestureGate, HeadNods, fistHeldUp, unmuteHint } from './gestures';
import { readFrame, type FrameSample, type InputSample, type Pose, type Ray } from './hands';
import { Hud } from './hud';
import { PieceResize, TAP_MS, isTap, sizeLabel } from './piece-resize';
import { QuestRoom, type DrawnRay } from './room-view';
import { ThrowVelocity } from './throw';
import { PalmToggle, pageAt, wristChoice, wristMenu, type WristMenu, type WristPage } from './wrist-menu';

/** How often presence, a held object's grip and the report are sent or shown, in milliseconds. */
const PRESENCE_MS = 50;
const GRIP_MS = 100;
const REPORT_MS = 500;
/** A press waits this long for a second one, which together scale the room instead (#180). */
const PAIR_MS = 150;
/**
 * A tapped piece stays chosen for Move and Resize on the wrist menu this long (#204); resize mode
 * waits this long for two pinches (#202); a resize is sent this often.
 */
const CHOSEN_MS = 20000;
const RESIZE_WAIT_MS = 6000;
const RESIZE_MS = 100;
/** Resting the gaze this long on an object starts a topic about it. */
const DWELL_MS = 1500;
/** A pointing finger draws its ray once it has pointed this long, so a hand passing through does not. */
const POINT_MS = 200;
/** A gesture line in the headset stays this long. */
const SAID_MS = 2000;
/** How far the gaze reaches for an object at life size, in room metres. */
const GAZE_METRES = 6;
/** Static objects this thin are the floor, which the gaze is not starting a topic about. */
const FLOOR_METRES = 0.05;
/** Before a tracked head pose, lining up takes the `local` origin as the floor centre. */
const NO_CALIBRATION: CalibrationInput = { yaw: 0, origin: { x: 0, y: 0, z: 0 } };
const BLOCKED = 'The other person is holding that object.';

const connectButton = element<HTMLButtonElement>('connect');
const enterButton = element<HTMLButtonElement>('enter-vr');
const disconnectButton = element<HTMLButtonElement>('disconnect');
const voiceButton = element<HTMLButtonElement>('voice-toggle');
const muteButton = element<HTMLButtonElement>('voice-mute');
const sceneElement = element('scene');

let connected = false;
let busy = false;
let xrSupported = false;
let xrActive = false;
let state: SessionState | null = null;
/** Where the head is now, as the alignment lining up here would save; null before a tracked frame. */
let calibrationNow: CalibrationInput | null = null;
/**
 * Whether the session's reference space is `local-floor`, whose y = 0 is the real floor (#207):
 * the room's floor is then put on it. Else `local`, and the eyes are taken as 1.5 m up.
 */
let onFloor = false;
let head: Pose | null = null;
let tracking: FrameSample['tracking'] = 'lost';
/** The hands whose pinch the session has selected. */
const pinching = new Set<XRInputSource>();
/** The input holding an object, and the offset that keeps the object from jumping to it. */
let holder: XRInputSource | null = null;
let grabOffset: { x: number; y: number; z: number } | null = null;
let releasing: number | null = null;
/** The held object's recent places, for the speed it is thrown at, and the latest grip. */
const swing = new ThrowVelocity();
/** Steadies the holding hand in a small room, where its tremble is many times larger (#184). */
const smoother = new GripSmoother();
/** The catalogue, for the palette above the hand while the room is small (#184). */
let catalogueItems: CatalogueItem[] = [];
/** A piece taken from the palette, the input holding it, and where it was last held. */
let taking: { item: CatalogueItem; source: XRInputSource; last: Pose | null } | null = null;
let lastGripPose: { position: Position; orientation: Rotation } | null = null;
/** Each input's holding and confirm last frame, to tell a press from a hold. */
const wasHolding = new WeakMap<XRInputSource, boolean>();
const wasConfirming = new WeakMap<XRInputSource, boolean>();
const wasMuting = new WeakMap<XRInputSource, boolean>();
/** When each input's press began, while it waits to see whether a second pinch scales the room. */
const pressedAt = new WeakMap<XRInputSource, number>();
/** What the voice call last said in the headset, and until when (#173). */
let voiceSaid: { text: string; until: number } | null = null;
/** Since when each hand has pointed. */
const pointingSince = new WeakMap<XRInputSource, number>();
/** Shown in the headset after a loss, a reset or the phone leaving, until the person acts. */
let pauseNotice: string | null = null;
/** What a gesture last said in the headset, and until when. */
let gestureLine: { text: string; until: number } | null = null;
/** A fist held up mutes and unmutes the voice call (#175). */
const fistGate = new GestureGate<'fist'>({ holdMs: FIST_HOLD_MS, cooldownMs: FIST_COOLDOWN_MS });
/** Two pinches shrink the room into a dollhouse and grow it back (#180). Only this headset's view. */
const scaling = new DollhouseScaling();
/** One hand holding nothing carries a small room, to move and turn it (#182). */
const carry = new DollhouseCarry();
let carrier: XRInputSource | null = null;
/** The placed piece chosen by a tap on it, for Move and Resize on the wrist menu (#204), until when. */
let offer: { id: string; until: number } | null = null;
/**
 * The wrist menu above the left hand (#204): open on an open palm, its page, and the inputs
 * sliding it or holding Hold to speak.
 */
const palm = new PalmToggle();
let wristPage: WristPage = 'objects';
let sliding: XRInputSource | null = null;
let speaking: XRInputSource | null = null;
/** A piece in resize mode (#202), and when its scale was last sent. */
const resize = new PieceResize();
let lastResize = -Infinity;
/** Resize mode ends by itself if both hands haven't pinched by then. */
let resizeUntil = -Infinity;
/** The current hold, from when its press began and where the hand was, to tell a tap (#202). */
let holdStart: { since: number; at: Position; id: string } | null = null;
/** The object the last hold took, known before Python confirms the hold. */
let heldId: string | null = null;
const nods = new HeadNods();
const dwell = new Dwell(DWELL_MS);
let lastPresence = -Infinity;
let presenceSent = false;
let lastGrip = -Infinity;
let lastReport = -Infinity;
/** When the phone's held object last glided on, in `performance.now()` milliseconds. */
let lastGlide: number | null = null;
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
/** The hold this headset owns, if Python has one in progress. */
const ownHold = (): SessionState['manipulation'] =>
  state?.manipulation?.owner === 'vr_solver' ? state.manipulation : null;
const phoneHolds = (id: string | null): boolean =>
  id !== null && state?.manipulation?.owner === 'mobile_master' && state.manipulation.entity === id;

function controls(): void {
  connectButton.disabled = connected || busy;
  disconnectButton.disabled = !connected;
  voiceButton.disabled = !connected;
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
  lastReport = now;
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
    room_scale: scaleLabel(scaling.view.scale),
    floor: xrActive ? (onFloor ? 'real (local-floor)' : 'assumed: eyes 1.5 m up (local)') : 'not-tested',
    gestures: gestureLog.slice(-20),
    voice: voice.report(),
    user_agent: navigator.userAgent,
  }, null, 2);
}

/** Mutes or unmutes from inside VR, where the page's Mute button cannot be reached. */
function toggleMute(how: 'fist' | 'button', now: number): void {
  // Not while dictating: the call stays muted until the description is said (#188).
  if (!voice.on || dictationListening) return;
  const muted = !voice.status.muted;
  voice.setMuted(muted);
  // Muting is followed by the line that stays, saying how to unmute.
  gesture(muted ? `Microphone muted (${how})` : 'Microphone on', now);
}

function gesture(text: string, now: number): void {
  gestureLine = { text, until: now + SAID_MS };
  element('gesture-status').textContent = text;
  gestureLog.push({ at: new Date().toISOString(), gesture: text });
}

let world: World | null = null;
let room: QuestRoom | null = null;
const hud = new Hud();

/** The voice call with the phone user (#13). Started on the page, before Enter VR. */
/** Muted for dictation (#188): the call is unmuted when dictation ends. */
let mutedForDictation = false;
/** Whether dictation is listening; a flag, as the call's callback can run before it exists. */
let dictationListening = false;
/** While dictating, the call stays muted, whenever it connects or is unmuted. */
function keepDictationMuted(): void {
  if (!dictationListening || !voice.on || voice.status.muted || voice.status.phase === 'asking') return;
  mutedForDictation = true;
  voice.setMuted(true);
}

const voice = new VoiceCall({
  sendReady: ready => client.sendVoiceReady(ready),
  sendSignal: signal => client.sendVoiceSignal(signal),
  sendMuted: muted => client.sendVoiceMuted(muted),
  changed: status => {
    // A call that connects, or is unmuted, while dictating is muted again (#188).
    keepDictationMuted();
    muteButton.hidden = status.phase === 'off' || status.phase === 'asking';
    muteButton.textContent = status.muted ? 'Unmute' : 'Mute';
    const line = element('voice-status');
    line.textContent = voiceLine(status, 'the phone');
    line.dataset.voice = status.phase;
    line.dataset.receiving = String(status.receiving);
    line.dataset.path = status.path ? (status.path.relayed ? 'relayed' : 'direct') : '';
    voiceButton.textContent = status.phase === 'off' ? 'Start voice' : 'Stop voice';
    // In VR the page is out of sight: say each change of the call in the headset for a moment.
    const note = voiceNote(status, 'the phone', unmuteHint(inputMode()));
    if (note !== voiceSaid?.text) voiceSaid = note === null ? null : { text: note, until: performance.now() + SAID_MS };
    // The report shows how the call connected, and outside VR nothing else refreshes it.
    report();
  },
});
muteButton.addEventListener('click', () => voice.setMuted(!voice.status.muted));
// Inside the tap: the browser asks for the microphone, and plays the other person, only then.
voiceButton.addEventListener('click', () => {
  if (voice.on) voice.stop();
  else if (connected) void voice.start('vr_solver');
});

const client = new SessionClient({
  state: applyState,
  voice: signal => { void voice.signal(signal); },
  connection: value => {
    connected = value;
    element('connection').textContent = value ? 'Connected · VR headset' : 'Not connected';
    // A new connection has shown the phone no hand yet (#185).
    handShown = false;
    if (!value) {
      voice.connectionLost();
      state = null;
      holder = null;
      grabOffset = null;
      releasing = null;
      room?.predict(null);
    }
    controls();
  },
  selection: () => {},
  error: message => {
    showError(message);
    // In VR the page is out of sight, so a refusal, such as a piece let go off the floor, is
    // said in the headset too.
    if (xrActive) gesture(message, performance.now());
  },
});

function applyState(next: SessionState): void {
  if (state && next.revision < state.revision) return;
  const phoneWas = state?.mobile_connected ?? false;
  const phoneHeld = state?.manipulation?.owner === 'mobile_master';
  state = next;
  voice.applyState(next);
  map.showRoom(next.room);
  map.showPlayers(next.participants, 'vr_solver');
  room?.align(next.alignment.vr_solver);
  room?.showPhone(next.participants.mobile_master);
  showPlaced(next);
  showDrill(next);
  // A piece made from a description or a photo joined the catalogue (#187).
  if (catalogueShown !== null && next.catalogue_version !== catalogueShown) void showCatalogue();
  catalogueShown = next.catalogue_version;
  const held = next.manipulation;
  room?.showControl(held?.entity ?? null);
  room?.glide(held?.owner === 'mobile_master' ? held.entity : null);
  const mine = ownHold();
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

/** The placed pieces, each with a button to take it away unless the phone holds it (#183). */
const placedList = element('placed-list');
let placedShown = '';
// The drill (#234): choosing its object by touch, its fire being made, then Start and Stop.
/** The object chosen on the Drill menu in VR, as on the Drill card's list (#234). */
let drillChosen: string | null = null;
/** The step the drill's fire job has reached, polled while it is being made. */
let drillJob: { id: string; state: string } | null = null;
const drillForm = element<HTMLFormElement>('drill-form');
const drillObject = element<HTMLSelectElement>('drill-object');
const drillRun = element<HTMLButtonElement>('drill-run');
const drillCancel = element<HTMLButtonElement>('drill-cancel');
const drillStatus = element('drill-status');
let drillChoices = '';

/** The drill as the headset is told it, or none. */
function currentDrill(): DrillState | null {
  const drill = state?.drill;
  return drill?.entity ? (drill as DrillState) : null;
}

function drillText(): string {
  return drillLine(currentDrill(), entities(), state?.room.hazards ?? [], drillChosen, drillJob?.state ?? null);
}

/** The object the Drill menu has chosen: the one picked, else the drill's, else the first. */
function chosenObject(): string | null {
  const objects = drillObjects(entities());
  if (drillChosen && objects.some(object => object.id === drillChosen)) return drillChosen;
  return currentDrill()?.entity ?? objects[0]?.id ?? null;
}

/** Prepares a drill on a room object: the server finds or makes its fire. */
function prepareDrill(entity: string): void {
  const version = state?.room.room_version;
  if (version === null || version === undefined) return;
  drillJob = null;
  drillChosen = entity;
  drillObject.value = entity;
  client.sendPrepareDrill(version, entity);
}

/** Starts the drill's fire, or stops it while it runs. */
function runDrill(): void {
  const drill = currentDrill();
  const version = state?.room.room_version;
  if (!drill?.hazard_id || version === null || version === undefined) return;
  const running = drillPlaying(drill, state?.room.hazards ?? []);
  client.sendHazardControl(running ? 'stop_hazard' : 'start_hazard', version, drill.hazard_id);
}

function showDrill(next: SessionState): void {
  const objects = drillObjects(next.room.entities);
  const choices = objects.map(entity => entity.id + ":" + entity.label).join(',');
  if (choices !== drillChoices) {
    drillChoices = choices;
    const chosen = drillObject.value;
    drillObject.replaceChildren(...objects.map(entity => new Option(entity.label, entity.id)));
    if (objects.some(entity => entity.id === chosen)) drillObject.value = chosen;
  }
  const drill = currentDrill();
  const running = drillPlaying(drill, next.room.hazards ?? []);
  drillRun.disabled = drill?.state !== 'ready';
  drillRun.textContent = running ? 'Stop' : 'Start';
  drillCancel.disabled = drill === null;
  if (drill?.state !== 'preparing') drillJob = null;
  // The same line as in VR, where buttons are pinched; on the page they are pressed.
  drillStatus.textContent = drillLine(drill, next.room.entities, next.room.hazards ?? [], null, drillJob?.state ?? null)
    .replace('pinch ', 'press ');
}

drillForm.addEventListener('submit', event => {
  event.preventDefault();
  if (drillObject.value) prepareDrill(drillObject.value);
});
drillRun.addEventListener('click', runDrill);
drillCancel.addEventListener('click', cancelDrill);

/** Calls the drill off: its fire leaves the room. */
function cancelDrill(): void {
  const version = state?.room.room_version;
  if (version !== null && version !== undefined) client.sendCancelDrill(version);
}

// While the drill's fire is being made, its steps are read every two seconds.
window.setInterval(() => {
  const drill = currentDrill();
  if (drill?.state !== 'preparing' || !drill.job) return;
  const job = drill.job;
  void fetch("/api/hazards/jobs/" + job).then(response => response.ok ? response.json() : null).then(found => {
    if (!found || currentDrill()?.job !== job) return;
    drillJob = { id: job, state: found.state };
    if (state) showDrill(state);
  }).catch(() => undefined);
}, 2000);

function showPlaced(next: SessionState): void {
  const pieces = next.room.entities.filter(entity => entity.furniture);
  const phoneHolds = next.manipulation?.owner === 'mobile_master' ? next.manipulation.entity : null;
  // Rebuilt only when the list or what the phone holds changes, not with every move.
  const shown = JSON.stringify([pieces.map(piece => piece.id), phoneHolds]);
  if (shown === placedShown) return;
  placedShown = shown;
  placedList.replaceChildren(...pieces.map(piece => {
    const row = document.createElement('li');
    const name = document.createElement('span');
    name.textContent = piece.label;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = 'Take away';
    button.setAttribute('aria-label', `Take away ${piece.label}`);
    button.disabled = piece.id === phoneHolds;
    button.addEventListener('click', () => {
      const version = state?.room.room_version;
      if (version !== null && version !== undefined) client.sendRemoveFurniture(version, piece.id);
    });
    row.append(name, button);
    return row;
  }));
}

/** The person stands on the page's map: the alignment is turned and moved so they are there. */
function standOnMap(spot: Spot, heading: number | null): void {
  if (!connected) return;
  lifeSize();
  const now = calibrationNow ?? NO_CALIBRATION;
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

/** The catalogue piece the next press on the map places (#181), or null to stand there instead. */
let chosenPiece: CatalogueItem | null = null;
const furnitureList = element('furniture-list');
const furnitureStatus = element('furniture-status');
const FURNITURE_HINT = furnitureStatus.textContent ?? '';

function choosePiece(item: CatalogueItem | null): void {
  chosenPiece = chosenPiece?.id === item?.id ? null : item;
  for (const button of furnitureList.querySelectorAll<HTMLButtonElement>('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.item === chosenPiece?.id));
  }
  const where = chosenPiece?.generated ? 'your new piece' : `the ${chosenPiece?.name.toLowerCase()}`;
  furnitureStatus.textContent = chosenPiece
    ? `Press on the room map where ${where} goes, and drag the way it faces.`
    : FURNITURE_HINT;
}

/** Making a piece from a description (#186): the job, polled until it ends. */
const makeForm = element<HTMLFormElement>('furniture-make');
const makeInput = element<HTMLInputElement>('furniture-description');
const makeButton = element<HTMLButtonElement>('furniture-make-button');
const cancelButton = element<HTMLButtonElement>('furniture-cancel');
const preview = element<HTMLImageElement>('furniture-preview');
/** How often a job is asked about, in milliseconds. */
const JOB_POLL_MS = 1000;
let making: string | null = null;

/** The catalogue version last seen, to reload the catalogue when a piece is added (#187). */
let catalogueShown: number | null = null;

/** Shows a job's progress on the page and its picture in the hand in VR; ends it when it's done. */
function showJob(job: FurnitureJob): void {
  making = job.state === 'queued' || job.state === 'image_ready' ? job.id : null;
  makeButton.disabled = making !== null;
  cancelButton.hidden = making === null;
  preview.hidden = job.image_url === null || making === null;
  if (job.image_url && !preview.hidden && preview.getAttribute('src') !== job.image_url) preview.src = job.image_url;
  room?.showCard(making && job.image_url ? job.image_url : null);
  if (job.state === 'queued') furnitureStatus.textContent = 'Making a picture of it…';
  else if (job.state === 'image_ready') furnitureStatus.textContent = 'Here is the picture. Making it into a 3D piece, which can take a few minutes…';
  else if (job.state === 'failed') furnitureStatus.textContent = job.error ?? 'The piece could not be made.';
  else if (job.state === 'cancelled') furnitureStatus.textContent = 'Stopped. Nothing was added.';
  else if (job.item) {
    const item = job.item;
    void showCatalogue().then(() => {
      chosenPiece = null;
      choosePiece(item);
    });
  }
}

async function followJob(id: string): Promise<void> {
  while (making === id) {
    await new Promise(resolve => setTimeout(resolve, JOB_POLL_MS));
    if (making !== id) return;
    try {
      const response = await fetch(`/api/furniture/jobs/${id}`);
      if (response.ok) showJob(await response.json() as FurnitureJob);
      // Jobs live in the server's memory: after a restart this one is gone, so stop asking.
      else if (response.status === 404 && making === id) {
        showJob({ id, state: 'failed', error: 'The server lost this piece, perhaps because it restarted. Make it again.', image_url: null, item: null });
      }
    } catch {
      // A dropped request is asked again next time.
    }
  }
}

makeForm.addEventListener('submit', event => {
  event.preventDefault();
  const description = makeInput.value.trim();
  if (description.length < 3 || making) return;
  makeButton.disabled = true;
  void (async () => {
    const response = await fetch('/api/furniture/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    }).catch(() => null);
    if (!response?.ok) {
      makeButton.disabled = false;
      furnitureStatus.textContent = response
        ? await errorMessage(response, 'The piece could not be started.')
        : 'The server could not be reached. Try again.';
      return;
    }
    const job = await response.json() as FurnitureJob;
    showJob(job);
    void followJob(job.id);
  })();
});
/**
 * Holding the talk button says the description instead of typing it (#188). The call is kept
 * muted while it listens, so the phone user doesn't hear the dictation, and unmuted after if it
 * was on. A click, as from the keyboard, starts or stops listening instead of a hold.
 */
const dictateButton = element<HTMLButtonElement>('furniture-dictate');
/** Whether the button is held, and whether this hold has failed, for what the status says. */
let dictationHeld = false;
let dictationFailed = false;
const listeningLine = (): string => mutedForDictation
  ? 'Listening, with the call muted… let go when you have said it.'
  : 'Listening… let go when you have said it.';
const dictation = new Dictation({
  heard: text => {
    makeInput.value = text;
    // Late words after letting go don't say "listening" again.
    if (dictationHeld) furnitureStatus.textContent = listeningLine();
  },
  failed: message => {
    dictationFailed = true;
    furnitureStatus.textContent = message;
  },
  ended: () => {
    dictationHeld = false;
    dictationListening = false;
    dictateButton.setAttribute('aria-pressed', 'false');
    if (mutedForDictation) {
      mutedForDictation = false;
      voice.setMuted(false);
    }
    if (!dictationFailed && makeInput.value.trim()) furnitureStatus.textContent = 'Check the description, then press Make it.';
  },
});
function startDictation(): void {
  if (dictation.listening) return;
  dictationFailed = false;
  if (!dictation.start()) return;
  // Cleared only once listening has started, so a browser that can't listen keeps what was typed.
  makeInput.value = '';
  dictationHeld = true;
  dictationListening = true;
  dictateButton.setAttribute('aria-pressed', 'true');
  keepDictationMuted();
  furnitureStatus.textContent = listeningLine();
}
dictateButton.addEventListener('pointerdown', event => {
  // Held to the button, so a wobbling ray or finger doesn't end the hold early. A pointer the
  // browser doesn't know as active can't be captured, which never stops dictation.
  try {
    dictateButton.setPointerCapture(event.pointerId);
  } catch {
    // Listening goes on without the capture.
  }
  startDictation();
});
for (const name of ['pointerup', 'pointercancel'] as const) {
  dictateButton.addEventListener(name, () => {
    dictationHeld = false;
    dictation.stop();
  });
}
dictateButton.addEventListener('click', event => {
  // A pointer's hold has its own events; a keyboard's click starts or stops listening.
  if (event.detail !== 0) return;
  if (dictation.listening) {
    dictationHeld = false;
    dictation.stop();
  } else {
    startDictation();
  }
});

cancelButton.addEventListener('click', () => {
  const id = making;
  if (!id) return;
  void fetch(`/api/furniture/jobs/${id}/cancel`, { method: 'POST' })
    .then(response => response.ok ? response.json() as Promise<FurnitureJob> : null)
    .then(job => { if (job) showJob(job); });
});

/** The catalogue's pieces as buttons, each with its true size. */
async function showCatalogue(): Promise<void> {
  try {
    const response = await fetch('/api/furniture');
    if (!response.ok) throw new Error();
    const { items } = await response.json() as { items: CatalogueItem[] };
    catalogueItems = items;
    furnitureList.replaceChildren(...items.map(item => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.item = item.id;
      // A reload, when a piece joins, keeps the piece chosen before it.
      button.setAttribute('aria-pressed', String(item.id === chosenPiece?.id));
      const { width, depth, height } = item.size;
      button.textContent = `${item.name} · ${width} × ${depth} × ${height} m`;
      button.addEventListener('click', () => choosePiece(item));
      return button;
    }));
  } catch {
    furnitureStatus.textContent = 'The furniture catalogue could not be loaded. Reload to try again.';
  }
}

/** A press on the map places the chosen piece there, facing the way dragged; else the person stands there. */
function pickOnMap(spot: Spot, heading: number | null): void {
  const piece = chosenPiece;
  const version = state?.room.room_version;
  if (!piece) {
    standOnMap(spot, heading);
    return;
  }
  if (!connected || version === null || version === undefined) {
    // The piece stays chosen, for when the room is back.
    furnitureStatus.textContent = `The ${piece.name.toLowerCase()} can be placed once the headset is connected and the room has loaded.`;
    return;
  }
  // Python lifts it to the floor's top; it faces -z unless dragged another way.
  client.sendAddFurniture(version, piece.id, { x: spot.x, y: 0, z: spot.z }, heading ?? 0);
  choosePiece(null);
}
const map = new RoomMap(element('quest-map'), 'quest-map', { pick: pickOnMap });
void showCatalogue();

/** Places the piece taken from the palette where it was last held (#184); it then falls there. */
function placeTaken(): void {
  const piece = taking;
  taking = null;
  const alignment = aligned();
  const version = state?.room.room_version;
  if (!piece?.last || !alignment || version === null || version === undefined) return;
  const { position, yaw } = dollhousePlacement(scaling.view, alignment, piece.last.position, piece.last.orientation);
  // Python takes a yaw from -π to π.
  client.sendAddFurniture(version, piece.item.id, position, Math.atan2(Math.sin(yaw), Math.cos(yaw)));
}

/** Back to life size: the dollhouse is drawn from an alignment that is about to change or is gone. */
function lifeSize(): void {
  taking = null;
  carry.end();
  carrier = null;
  scaling.reset();
  room?.setDollhouse(scaling.view);
}

function confirmAlignment(): void {
  if (!connected) return;
  pauseNotice = null;
  lifeSize();
  client.sendCalibration(calibrationNow ?? NO_CALIBRATION);
}

/**
 * Let go of the held object. Opening the hand or the grip throws it at the speed it was moving
 * (#162); losing tracking, the controller or the session, or pausing, only puts it down.
 */
function release(throwing = false): void {
  const mine = ownHold();
  holder = null;
  const moving = throwing ? swing.velocity(performance.now()) : null;
  const velocity = moving ? throwInRoom(scaling.view, moving) ?? undefined : undefined;
  swing.clear();
  const finalGrip = lastGripPose;
  lastGripPose = null;
  if (!mine || releasing === mine.id) return;
  releasing = mine.id;
  // The object leaves from where the hand is now, not from the last grip sent up to 100 ms ago.
  if (finalGrip) client.sendGrip(mine.id, finalGrip);
  client.sendRelease(mine.id, velocity);
}

/**
 * Tracking, the session or the reference space can no longer move a held object. A loss keeps
 * the alignment. A reset or a new session forgets it, because that `local` origin is not the one
 * lined up; forgetting it lets a pinch line the room up again, as A does.
 */
function pause(reason: 'lost' | 'ended' | 'reset'): void {
  const wasHolding = ownHold() !== null;
  release();
  grabOffset = null;
  if (reason === 'lost' && !wasHolding) return;
  if (reason !== 'lost') {
    client.sendClearAlignment();
    lifeSize();
  }
  pauseNotice = reason === 'lost'
    ? 'Tracking lost. The object stays where it was. Take hold again when the line is orange.'
    : 'Line the room up again: press A, or pinch. The object stays where it was.';
}

/**
 * A point, a direction or a turn in the `local` space, in room metres: through the dollhouse
 * first, so a hand in a small room reaches what is drawn under it.
 */
const inRoom = (alignment: AlignmentState, point: Position) => roomPoint(alignment, fromDollhouse(scaling.view, point));
const directionInRoom = (alignment: AlignmentState, direction: Position) =>
  roomDirection(alignment, velocityFromDollhouse(scaling.view, direction));
const turnInRoom = (alignment: AlignmentState, orientation: Rotation) =>
  roomOrientation(alignment, orientationFromDollhouse(scaling.view, orientation));

/** The movable object a ray is on, and whether the phone holds it. */
function aimedAt(ray: Ray | null): { hit: string | null; blocked: boolean } {
  const alignment = aligned();
  if (!ray || !alignment) return { hit: null, blocked: false };
  // A ray reaches as far in a small room as it does at life size.
  const hit = targetAlongRay(
    inRoom(alignment, ray.origin), directionInRoom(alignment, ray.direction), entities(), RAY_REACH_METERS / scaling.view.scale);
  const blocked = phoneHolds(hit);
  return { hit: blocked ? null : hit, blocked };
}

/** Any object the head looks at, for starting a topic: furniture too, but not the floor. */
function lookedAt(): string | null {
  const alignment = aligned();
  if (!head || !alignment) return null;
  const topics = entities()
    .filter(entity => entity.kind === 'movable' || entity.size.height > FLOOR_METRES)
    // Every object counts here, not only the ones that can be picked up.
    .map(entity => ({ ...entity, kind: 'movable' as const, selectable: true }));
  return targetAlongRay(
    inRoom(alignment, head.position), directionInRoom(alignment, rayForward(head.orientation)), topics,
    GAZE_METRES / scaling.view.scale);
}

/** Where a held object is carried from: the grip, else the ray's start turned as the head is. */
function gripOf(input: InputSample): Pose | null {
  if (input.grip) return input.grip;
  return input.ray && head ? { position: input.ray.origin, orientation: head.orientation } : null;
}

/** Starts holding with `input`: before alignment it lines up; after, it takes what it aims at. */
function takeHold(input: InputSample, gazeTarget: string | null, chosen?: string): 'held' | 'refused' | 'nothing' {
  const alignment = aligned();
  if (!alignment) {
    confirmAlignment();
    return 'refused';
  }
  pauseNotice = null;
  const aimed = chosen ? { hit: chosen, blocked: phoneHolds(chosen) } : aimedAt(input.ray);
  const { hit, blocked } = aimed;
  if (blocked) {
    gestureLine = { text: BLOCKED, until: performance.now() + SAID_MS };
    return 'refused';
  }
  // Look and pinch: in a small room, a hand aimed at nothing takes what the head is looking at.
  // At life size it takes only what its ray is on (#204).
  const target = hit ?? (input.kind === 'hand' && looksToTake(scaling.view.scale) ? movable(gazeTarget) : null);
  const version = state?.room.room_version;
  const entity = entities().find(candidate => candidate.id === target);
  const grip = gripOf(input);
  if (!entity || !grip || version === null || version === undefined) return 'nothing';
  const position = inRoom(alignment, grip.position);
  const orientation = turnInRoom(alignment, grip.orientation);
  holder = input.source;
  heldId = entity.id;
  smoother.reset();
  grabOffset = offsetOf(position, orientation, entity.position);
  client.sendAcquire(version, entity.id, { position, orientation });
  return 'held';
}

/** What a tap with `input` is on: what its ray is on, else, for a hand in a small room, what the head looks at. */
function tapped(input: InputSample, gazeTarget: string | null): string | null {
  const { hit } = aimedAt(input.ray);
  return hit ?? (input.kind === 'hand' && looksToTake(scaling.view.scale) ? movable(gazeTarget) : null);
}

/**
 * Chooses `id` for Move and Resize, if it is a placed piece of furniture, and turns the wrist
 * menu to its Edit page (#204). A tap on anything else lets the chosen piece go.
 */
function offerPiece(id: string | null, time: number): void {
  const piece = entities().find(entity => entity.id === id);
  if (!piece?.furniture || phoneHolds(piece.id)) {
    offer = null;
    return;
  }
  offer = { id: piece.id, until: time + CHOSEN_MS };
  wristPage = 'edit';
  gesture(`${piece.label} chosen · open your left hand to move or resize it`, time);
}

/** The chosen piece, with its name above it, or none once it has gone or its time is up. */
function showChosen(time: number): void {
  if (offer && (time > offer.until || !entities().some(entity => entity.id === offer?.id))) offer = null;
  if (!offer || resize.piece) return;
  const piece = entities().find(entity => entity.id === offer?.id);
  if (piece) room?.showResize(piece.id, piece.scale ?? 1, `${piece.label} · chosen`);
}

/** The wrist menu's line of text for its page (#204). */
function wristLine(): string {
  if (wristPage === 'objects') {
    return catalogueItems.length ? 'Pinch a piece, carry it and let go where it goes' : 'No pieces yet: make one on the Make page';
  }
  if (wristPage === 'make') {
    const said = makeInput.value.trim();
    if (speaking) return said ? `Listening: ${said}` : 'Listening… say what to make, then let go';
    if (making) return furnitureStatus.textContent ?? '';
    return said ? `${said} · pinch Make it` : 'Hold to speak, and say the piece to make';
  }
  if (wristPage === 'drill') return drillText();
  if (wristPage === 'edit') {
    const piece = entities().find(entity => entity.id === offer?.id);
    return piece ? `${piece.label} · Move, or Resize with two hands` : 'Tap a placed piece to choose it';
  }
  return 'Leave VR';
}

/** Move or Resize on the wrist menu, for the chosen piece (#204). */
function editChosen(input: InputSample, button: 'move' | 'resize', time: number): void {
  const piece = entities().find(entity => entity.id === offer?.id);
  if (!piece) {
    gesture('Tap a placed piece first, then choose Move or Resize', time);
    return;
  }
  if (button === 'move') {
    if (takeHold(input, null, piece.id) === 'held') holdStart = null;
    offer = null;
    return;
  }
  resize.begin(piece.id, piece.scale ?? 1);
  resizeUntil = time + RESIZE_WAIT_MS;
  offer = { id: piece.id, until: time + CHOSEN_MS };
  // Both hands are the resize's now: a hand carrying the dollhouse lets go of it.
  carry.end();
  carrier = null;
  gesture('Resize: pinch with both hands, then pull apart or together', time);
}

/**
 * The piece in resize mode follows the two pinches (#202): drawn at once, sent to Python every
 * 100 ms, and sent as final when either hand lets go. Without a room, or with no two pinches
 * within six seconds, it leaves resize mode.
 */
function resizePiece(pinches: readonly Position[], lined: boolean, time: number): void {
  const id = resize.piece;
  const piece = entities().find(entity => entity.id === id);
  const version = state?.room.room_version;
  if (!id || !piece || !lined || version === null || version === undefined || phoneHolds(id)) {
    if (id) resize.cancel();
    room?.showResize(null);
    return;
  }
  const step = resize.update(pinches);
  if (step.phase === 'waiting' && time > resizeUntil) {
    resize.cancel();
    room?.showResize(null);
    return;
  }
  const catalogue = piece.scale ?? 1;
  const size = {
    width: piece.size.width / catalogue, height: piece.size.height / catalogue, depth: piece.size.depth / catalogue,
  };
  if (step.phase === 'done') {
    client.sendResizeFurniture(version, id, step.scale, true);
    room?.showResize(null);
    gesture(`${piece.label} · ${sizeLabel(size, step.scale)}`, time);
    return;
  }
  room?.showResize(id, step.scale, `${piece.label} · ${sizeLabel(size, step.scale)}`);
  if (step.phase === 'resizing' && time - lastResize >= RESIZE_MS) {
    client.sendResizeFurniture(version, id, step.scale, false);
    lastResize = time;
  }
}

/** The gaze target when it can be picked up, else null. */
function movable(id: string | null): string | null {
  const entity = entities().find(candidate => candidate.id === id);
  return entity?.kind === 'movable' && entity.selectable && !phoneHolds(id) ? entity.id : null;
}

/** Moves the phone's held object on toward where Python last put it. */
function glide(): void {
  const now = performance.now();
  room?.tick(lastGlide === null ? 0 : now - lastGlide);
  lastGlide = now;
}

/** Each XR frame: tracking, holding, gestures, presence and what the headset shows. */
function frame(xrFrame: XRFrame, time: number): void {
  const reference = world?.xrReferenceSpace;
  if (!reference) return;
  frameTimes.push(performance.now());
  // The page's own animation frames stop in VR, so the glide moves on here.
  glide();
  const sample = readFrame(xrFrame, reference, pinching);
  if (sample.tracking !== tracking) {
    tracking = sample.tracking;
    if (tracking !== 'tracked') pause('lost');
  }
  head = sample.head;
  if (head) calibrationNow = alignmentFromPose(head.position, head.orientation, onFloor);
  const alignment = aligned();

  // The wrist menu opens on an open left palm and closes on a fist (#204); with a controller, it
  // is always there.
  const leftHand = sample.inputs.find(input => input.source.handedness === 'left');
  const wristOpen = palm.update(leftHand?.kind === 'hand' ? leftHand.pose : null, time) || leftHand?.kind === 'controller';

  // A fist held up mutes and unmutes. Not by a hand that pinches, carries an object or the room,
  // takes a piece from the catalogue, or has just closed the wrist menu.
  const fist = voice.on && fistHeldUp(sample.inputs.map(input => ({
    pose: input.pose, wrist: input.wrist,
    busy: input.holding || input.source === holder || input.source === carrier || input.source === taking?.source ||
      (input.source === leftHand?.source && palm.closingFist),
  })), head?.position ?? null);
  if (fistGate.update(fist ? 'fist' : 'none', time)) toggleMute('fist', time);

  // Two pinches holding nothing scale the room, and take hold of nothing while they do (#180).
  // First, so the gaze and every hand below reach into the room as it is drawn this frame.
  // The dollhouse is drawn from the alignment: without one, back to life size, carried or not.
  if (!alignment) lifeSize();
  const pinches = sample.inputs
    .filter(input => input.holding && input.source !== holder && input.source !== taking?.source)
    .flatMap(input => input.pinchAt ? [input.pinchAt] : []);
  // A piece in resize mode takes the two pinches, not the room (#202).
  resizePiece(pinches, alignment !== null, time);
  room?.setDollhouse(scaling.update(resize.piece ? [] : pinches, alignment !== null && !holder && !ownHold()));

  // Gestures from the head and hands.
  const looking = lookedAt();
  const rest = dwell.update(looking, time);
  if (rest.started && rest.target) gesture(`Looking at ${label(rest.target)} · a topic to talk about`, time);
  if (head) {
    const answer = nods.update(head.orientation, time);
    if (answer) gesture(answer === 'yes' ? 'Yes (nod)' : 'No (shake)', time);
  }

  // The wrist menu floats above the open left hand (#204), at life size too: a slider of the
  // catalogue (#184), making a piece, Move and Resize, and Exit (#200). Not while that hand
  // pinches, or two hands scale the room or resize a piece.
  const paletteAt = leftHand?.grip?.position ?? leftHand?.pinchAt ?? null;
  const menu: WristMenu | null = wristOpen && !leftHand?.holding && !scaling.scaling && !resize.piece && head && paletteAt
    ? wristMenu(paletteAt, yawOf(head.orientation), wristPage, catalogueItems.length, drillObjects(entities()).length) : null;
  showChosen(time);
  room?.showWristMenu(catalogueItems, menu, wristLine(), {
    speaking: speaking !== null, making: making !== null,
    running: drillPlaying(currentDrill(), state?.room.hazards ?? []),
  }, drillObjects(entities()), chosenObject());

  // Holding: a press of the grip or a pinch takes hold; letting go puts the object down.
  for (const input of sample.inputs) {
    if (input.confirm && !wasConfirming.get(input.source)) confirmAlignment();
    wasConfirming.set(input.source, input.confirm);
    // B or Y mutes and unmutes: the page's Mute button cannot be reached from inside VR.
    if (input.mute && !wasMuting.get(input.source)) toggleMute('button', time);
    wasMuting.set(input.source, input.mute);
    const before = wasHolding.get(input.source) ?? false;
    wasHolding.set(input.source, input.holding);
    // A pinch on the wrist menu (#204): on its slider, slides between its pages; on a piece, takes
    // it into the hand at once (#184); on a button, does what it says.
    if (input.holding && !before && !holder && !taking && menu && input.pinchAt &&
      input.source !== leftHand?.source) {
      const choice = wristChoice(menu, input.pinchAt);
      if (choice) pressedAt.delete(input.source);
      if (choice?.kind === 'track') {
        sliding = input.source;
        wristPage = pageAt(menu, input.pinchAt);
        continue;
      }
      if (choice?.kind === 'object') {
        drillChosen = drillObjects(entities())[choice.index]?.id ?? null;
        continue;
      }
      if (choice?.kind === 'piece') {
        taking = { item: catalogueItems[choice.index], source: input.source, last: null };
        continue;
      }
      if (choice?.kind === 'button') {
        if (choice.button === 'exit') {
          void world?.session?.end();
          return;
        }
        if (choice.button === 'speak') {
          // Held like the page's talk button: listening until the pinch lets go (#188).
          speaking = input.source;
          startDictation();
        } else if (choice.button === 'make') {
          if (making) cancelButton.click();
          else makeForm.requestSubmit();
        } else if (choice.button === 'prepare') {
          const chosen = chosenObject();
          if (chosen) prepareDrill(chosen);
        } else if (choice.button === 'run') {
          runDrill();
        } else if (choice.button === 'cancel') {
          cancelDrill();
        } else {
          editChosen(input, choice.button, time);
        }
        continue;
      }
    }
    // A pinch sliding the menu follows the hand along it; one holding Hold to speak listens until
    // it lets go.
    if (sliding === input.source) {
      if (!input.holding) sliding = null;
      else if (menu && input.pinchAt) wristPage = pageAt(menu, input.pinchAt);
      continue;
    }
    if (speaking === input.source) {
      if (!input.holding) {
        speaking = null;
        dictationHeld = false;
        dictation.stop();
      }
      continue;
    }
    // Let go, the piece taken is placed at the room point under the fingertip (#184).
    if (taking?.source === input.source && !input.holding) {
      placeTaken();
      continue;
    }
    // In resize mode, pinches resize the piece and take hold of nothing (#202).
    if (resize.piece) {
      pressedAt.delete(input.source);
      continue;
    }
    // A quick pinch let go before it took hold is a tap: on placed furniture, it chooses it for
    // Move and Resize (#202, #204); on nothing, it lets the chosen piece go.
    const pressed = pressedAt.get(input.source);
    if (!input.holding && before && !holder && pressed !== undefined && alignment &&
      time - pressed < TAP_MS) {
      offerPiece(tapped(input, looking), time);
    }
    // A press while something is held, or while scaling, takes hold of nothing.
    if (input.holding && !before && !holder) pressedAt.set(input.source, time);
    if (!input.holding || holder || scaling.scaling) pressedAt.delete(input.source);
    // Lined up, a press waits a moment for the other hand, so two pinches can scale the room
    // instead of the first one taking hold. Before that, a pinch lines the room up at once.
    const since = pressedAt.get(input.source);
    if (since !== undefined && (!alignment || time - since >= PAIR_MS)) {
      pressedAt.delete(input.source);
      // A press on nothing in a small room takes hold of the dollhouse itself (#182).
      // Only a real grip turns the dollhouse: without one, the head's turn would.
      const grip = input.grip;
      const took = takeHold(input, looking);
      if (took === 'nothing' && grip && carry.begin(grip, scaling.view)) {
        carrier = input.source;
      }
      const from = took === 'held' ? gripOf(input) : null;
      holdStart = from && heldId ? { since, at: from.position, id: heldId } : null;
    }
    if (carrier === input.source && !input.holding) {
      carry.end();
      carrier = null;
    }
    // Opening the hand throws what it held: in the dollhouse as far as the toss looks, and a
    // slow drift only puts it down (#184).
    if (!input.holding && before && holder === input.source) {
      // A quick pinch on placed furniture that hardly moved it is a tap: it is put down where
      // it was, and chosen for Move and Resize (#202, #204).
      const start = holdStart;
      const here = gripOf(input)?.position;
      const tap = start !== null && here !== undefined && isTap(start.since, start.at, time, here);
      holdStart = null;
      release(!tap);
      if (tap) offerPiece(start.id, time);
    }
  }
  // A hand lost while it slides the wrist menu or holds Hold to speak lets go of it (#204).
  if (sliding && !sample.inputs.some(input => input.source === sliding)) sliding = null;
  if (speaking && !sample.inputs.some(input => input.source === speaking)) {
    speaking = null;
    dictationHeld = false;
    dictation.stop();
  }
  // The carried dollhouse follows its hand; two pinches scaling it, or the hand gone, end that.
  const carrierInput = sample.inputs.find(input => input.source === carrier);
  const carryGrip = carrierInput?.grip ?? null;
  if (carrier && (!carryGrip || scaling.scaling)) {
    carry.end();
    carrier = null;
  } else if (carryGrip) {
    scaling.view = carry.update(carryGrip);
    room?.setDollhouse(scaling.view);
  }
  const takingInput = taking ? sample.inputs.find(input => input.source === taking?.source) : undefined;
  if (taking && !takingInput) {
    taking = null;
  } else if (taking && takingInput?.pinchAt && takingInput.grip) {
    taking.last = { position: takingInput.pinchAt, orientation: takingInput.grip.orientation };
  }
  room?.showHeld(
    taking?.item ?? null,
    taking?.last ? { position: taking.last.position, yaw: yawOf(taking.last.orientation) } : null,
    scaling.view.scale,
  );
  const mine = ownHold();
  const holding = sample.inputs.find(input => input.source === holder);
  if (holder && !holding) release();
  const grip = holding && gripOf(holding);
  if (mine && grip && grabOffset && alignment) {
    // Steadied in a small room, then in room metres (#180, #184).
    const steady = smoother.smooth(grip.position, time, scaling.view.scale);
    const position = inRoom(alignment, steady);
    const orientation = turnInRoom(alignment, grip.orientation);
    const carried = grabbedPosition(position, orientation, grabOffset);
    room?.predict(mine.entity, carried);
    // A throw is the held point's own motion in room metres, wrist flick included, measured
    // without the smoothing's lag; its regression over 100 ms steadies it instead.
    const unsteadied = inRoom(alignment, grip.position);
    swing.add(grabbedPosition(unsteadied, orientation, grabOffset), performance.now());
    lastGripPose = { position, orientation };
    if (time - lastGrip >= GRIP_MS && client.sendGrip(mine.id, lastGripPose)) lastGrip = time;
  }

  // Rays: each controller's, a pinching hand's, and a pointing finger's.
  const drawn: DrawnRay[] = [];
  let aimed: string | null = null;
  // Where a pointing finger meets the floor, in room metres: the phone draws a path to it (#248).
  let pointedSpot: ReturnType<typeof floorSpot> = null;
  for (const input of sample.inputs) {
    if (input.fingerRay) {
      if (!pointingSince.has(input.source)) pointingSince.set(input.source, time);
    } else {
      pointingSince.delete(input.source);
    }
    const pointing = input.fingerRay !== null && time - (pointingSince.get(input.source) ?? time) >= POINT_MS;
    const ray = pointing ? input.fingerRay : input.ray;
    if (pointing && input.fingerRay && alignment && !pointedSpot) {
      const { origin, direction } = input.fingerRay;
      const along = { x: origin.x + direction.x * 0.1, y: origin.y + direction.y * 0.1, z: origin.z + direction.z * 0.1 };
      pointedSpot = floorSpot(inRoom(alignment, origin), inRoom(alignment, along));
    }
    if (!ray || (input.kind === 'hand' && !pointing && !input.holding)) continue;
    const { hit, blocked } = aimedAt(ray);
    aimed ??= hit;
    drawn.push({ ...ray, look: blocked ? 'blocked' : hit ? 'target' : 'miss' });
  }
  room?.showRays(drawn);
  // What a ray is on, else the object the gaze has rested on long enough to start a topic.
  const topic = rest.progress >= 1 ? rest.target : null;
  room?.showHighlight(mine ? null : aimed ?? topic);

  // The picture of a piece being made rides above the left hand, else the first one (#186).
  const carrying = sample.inputs.find(input => input.source.handedness === 'left') ?? sample.inputs[0];
  room?.placeCard(carrying?.pinchAt ?? carrying?.grip?.position ?? null, head?.position ?? null);

  // A hand inside the small room shows on the phone as a giant hand coming down (#185).
  const reaching = alignment && scaling.view.scale < 1
    ? handInDollhouse(scaling.view, alignment, handPoints(sample.inputs), floor()) : null;
  publishHand(reaching, time);
  publishGuide(pointedSpot, time);
  publishPresence(time);
  showHud(time, drawn.some(ray => ray.look === 'blocked'));
  if (performance.now() - lastReport >= REPORT_MS) report();
}

/** Where each hand or controller pinches or grips, in the `local` space. */
const handPoints = (inputs: readonly InputSample[]): Position[] =>
  inputs.flatMap(input => input.pinchAt ? [input.pinchAt] : input.grip ? [input.grip.position] : []);

/** The room's floor pieces, worked out once per room version. */
let floorCache: { version: number | null; pieces: RoomEntity[] } = { version: null, pieces: [] };
function floor(): RoomEntity[] {
  const version = state?.room.room_version ?? null;
  if (floorCache.version !== version) floorCache = { version, pieces: floorPieces(entities()) };
  return floorCache.pieces;
}

/** Sends the pointed spot at most as often as presence; once pointing has stopped a moment, says it's gone. */
let lastGuide = -Infinity;
let guideShown = false;
let guideLost: number | null = null;
const GUIDE_GRACE_MS = 500;
function publishGuide(spot: ReturnType<typeof floorSpot>, time: number): void {
  if (!connected) return;
  if (spot) {
    guideLost = null;
    if (time - lastGuide < PRESENCE_MS || !client.sendGuide(spot)) return;
    lastGuide = time;
    guideShown = true;
    room?.showGuideSpot(spot);
    return;
  }
  // A finger passing out of a pointing pose for a moment keeps the path where it is.
  guideLost ??= time;
  if (guideShown && time - guideLost >= GUIDE_GRACE_MS && client.sendGuide(null)) {
    guideShown = false;
    room?.showGuideSpot(null);
  }
}

/** Sends the hand in the dollhouse at most as often as presence, and says once when it leaves. */
let lastHand = -Infinity;
let handShown = false;
function publishHand(reaching: Position | null, time: number): void {
  if (!connected) return;
  if (reaching) {
    // As long as a real hand times how many times smaller the room is drawn.
    const length = HAND_METRES / scaling.view.scale;
    if (time - lastHand < PRESENCE_MS || !client.sendDesignerHand(reaching, length)) return;
    lastHand = time;
    handShown = true;
  } else if (handShown && client.sendDesignerHand(null, null)) {
    handShown = false;
  }
}

function publishPresence(time: number): void {
  if (!connected) return;
  const alignment = aligned();
  let presence: PresenceInput | null = null;
  if (xrActive && head && alignment) {
    presence = {
      tracking_status: 'tracked',
      position: roomPoint(alignment, head.position),
      heading: yawOf(roomOrientation(alignment, head.orientation)),
    };
  }
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
  if (gestureLine && time > gestureLine.until) gestureLine = null;
  const text = pauseNotice
    ?? (scaling.scaling ? `Room at ${scaleLabel(scaling.view.scale)} · let go to keep this size` : null)
    ?? (carrier ? 'Carrying the room · let go to leave it here' : null)
    ?? (taking ? `${taking.item.name} · let go over the dollhouse to place it` : null)
    ?? (blocked ? BLOCKED : null)
    ?? (held?.owner === 'mobile_master' ? `Phone is holding ${label(held.entity)}` : null)
    ?? (held?.owner === 'vr_solver' ? `Holding ${label(held.entity)} · let go to put it down` : null)
    ?? gestureLine?.text
    ?? (aligned() ? null : 'Stand where you like, then press A or pinch to line up')
    // A change in the call shows for a moment; being muted stays, so nobody talks to no one.
    // It names the way to unmute for what is in use now: hands, or controllers.
    ?? (voice.status.muted ? voiceNote(voice.status, 'the phone', unmuteHint(inputMode())) : null)
    ?? (voiceSaid && time <= voiceSaid.until ? voiceSaid.text : null);
  hud.show(text, text === gestureLine?.text || (text === voiceSaid?.text && voice.status.phase === 'connected' && !voice.status.muted));
}

async function start(): Promise<void> {
  try {
    world = await World.create(sceneElement, {
      // The page offers VR from its own button, once connected.
      xr: {
        offer: 'none',
        // The real floor where the headset knows it (#207); `local`, whose origin is the eyes,
        // where it doesn't.
        referenceSpace: { type: ReferenceSpaceType.LocalFloor, fallbackOrder: [ReferenceSpaceType.Local] },
        features: { handTracking: true },
      },
      render: { near: 0.01, far: 100, camera: { position: [0, 1.5, 0], lookAt: [0, 1.1, -1.2] } },
      // No locomotion: the player rig stays where the `local` space puts it, so head poses in
      // that space are where the room's alignment expects them.
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
  const onPage = () => {
    if (!xrActive) glide();
    requestAnimationFrame(onPage);
  };
  requestAnimationFrame(onPage);
  renderer.xr.addEventListener('sessionstart', () => {
    xrActive = true;
    // A new session has a new `local` origin, so an alignment saved before is in the wrong place.
    client.sendClearAlignment();
    onFloor = false;
    room?.setPresenting(true);
    const session = renderer.xr.getSession();
    // IWSDK takes `local-floor` whenever the session supports it, so asking tells which it took.
    void session?.requestReferenceSpace('local-floor').then(() => {
      onFloor = true;
      room?.setPresenting(xrActive, true);
      report();
    }, () => undefined);
    session?.addEventListener('selectstart', event => { if (event.inputSource.hand) pinching.add(event.inputSource); });
    session?.addEventListener('selectend', event => { pinching.delete(event.inputSource); });
    session?.addEventListener('inputsourceschange', () => { controls(); report(); });
    // three.js has the reference space before it says the session started.
    world?.xrReferenceSpace?.addEventListener('reset', () => {
      calibrationNow = null;
      pause('reset');
    });
    controls();
  });
  renderer.xr.addEventListener('sessionend', () => {
    xrActive = false;
    // Out of VR the hand is no longer in the dollhouse (#185).
    if (handShown && client.sendDesignerHand(null, null)) handShown = false;
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
  void client.join('vr_solver').then(() => {
    // Voice was on in this tab before a reload or a disconnect: bring it back with the connection.
    if (voice.wanted) void voice.start('vr_solver');
  }).catch(error => {
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
