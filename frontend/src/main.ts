import './style.css';
import { roomDirection, roomHeading, roomOrientation, roomPoint } from './alignment';
import { element } from './dom';
import { FloorDepth } from './floor-depth';
import { GazeCursor } from './gaze-cursor';
import { floorPoint } from './aim';
import { grabbedPosition, offsetOf, targetAlongRay } from './grab';
import { MotionStats } from './motion-stats';
import { TrackingStats } from './tracking-stats';
import { CalibrationRefused, EngineTracking, HELD_AT, engineUnavailable, trackingEngine } from './engine-tracking';
import { RoomMap, type Spot } from './room-map';
import { MovementLog, type TrackingMode } from './movement-log';
import { StepTracking, type PhoneTracking } from './phone-tracking';
import { START_EYE, headingOf, pitchOf, type RoomPose } from './phone-view';
import {
  NO_PRESENCE, type Position, type PresenceInput, type Role, type Rotation, type SessionState,
} from './protocol';
import { showsRevision } from './revision';
import { SessionClient } from './session';
import { DiagnosticScene } from './scene';
import { STEP_LENGTHS } from './step-walk';
import { floorplan, type Floorplan } from './steps';
import { XRDiagnostic, xrError, type ControllerSample } from './xr';

const phoneButton = element<HTMLButtonElement>('connect-phone');
const vrButton = element<HTMLButtonElement>('connect-vr');
const disconnectButton = element<HTMLButtonElement>('disconnect');
const alignButton = element<HTMLButtonElement>('confirm-alignment');
const startButton = element<HTMLButtonElement>('start-xr');
const endButton = element<HTMLButtonElement>('end-xr');
const roomViewHud = element('room-view-hud');
const overlay = element('xr-overlay');
let role: Role | null = null;
let connected = false;
let busy = false;
let xrActive = false;
let state: SessionState | null = null;
let view: DiagnosticScene | null = null;
let xr: XRDiagnostic | null = null;
let roomViewOpen = false;
/** The room object Python accepted as this phone's selection. It is private to the phone. */
let selected: string | null = null;
/** Whether a finger is holding the selected object; Python decides whether it is picked up. */
let holding = false;
/** The hold this phone has asked to end, so it is asked once. */
let releasing: number | null = null;
/** How motion reaches this device, for the diagnostic report. */
const motion = new MotionStats();
/** How the phone's tracking behaved, for the diagnostic report. */
const trackingStats = new TrackingStats();
/** While nothing moves, the phone's room view still redraws this often to show others' changes. */
const PHONE_REDRAW_MS = 100;
/** After anything drawn changes, it draws every frame this long, so glides and outlines stay smooth. */
const PHONE_SETTLE_MS = 300;
/** A pose as text, to tell whether the phone moved since it last drew. */
function poseKey({ position: p, orientation: o }: RoomPose): string {
  return `${p.x} ${p.y} ${p.z} ${o.x} ${o.y} ${o.z} ${o.w}`;
}
/** How long a press on the selected object lasts before it is picked up, so a tap is not. */
const PICK_UP_MS = 300;
/** While carrying, the phone tells Python where it is and faces this often, so the object follows. */
const CARRY_POSE_MS = 100;
let lastCarryPose = 0;
/** While the headset holds the box, its grip pose is sent this often. */
const GRIP_POSE_MS = 100;
let lastGripPose = 0;
/** The grip is down, and the offset that keeps the box from jumping into the hand. */
let gripDown = false;
let grabOffset: Position | null = null;
/** The headset hold already asked to end, so it is asked once. */
let headsetReleasing: number | null = null;
/** Shown in the headset after a loss or a reset, until the person lines up or grabs again. */
let headsetPauseNotice: string | null = null;
/** The floor height a carried object slides across, from where it rested when picked up. */
let carryFloor: number | null = null;
/** The floor's extent, which a carried object stays on. */
let carryBounds: Floorplan['floor'] = null;
/** Turning and counted steps, at the view's height: used when the engine cannot track. */
const steps = new StepTracking(() => viewHeight, {
  step: (pose, count) => {
    if (selected === null) element('view-status').textContent = `Walking · ${count} ${count === 1 ? 'step' : 'steps'}`;
    publishPose(pose);
  },
});
/** Measured tracking from the 8th Wall engine, made once the engine has loaded. */
let measured: EngineTracking | null = null;
/** Whether the engine has measured a pose that Python has not been told yet. */
let measuredUnsent = false;
/** Where the phone is and faces, from whichever source is tracking it. */
let tracking: PhoneTracking = steps;
/** What tracking did on this phone, sent to Python with Send log for device checks. */
const movementLog = new MovementLog();
const trackingMode = (): TrackingMode => (tracking === measured ? 'measured' : 'steps');
/**
 * Tracks with the engine when it can run on this phone, and with steps otherwise. The engine may
 * load after the first tap, so a later tap moves from steps to the engine.
 */
function chooseTracking(): void {
  const engine = trackingEngine();
  if (engine) {
    measured ??= new EngineTracking(engine, element<HTMLCanvasElement>('engine-canvas'), {
      moved: pose => {
        measuredUnsent = true;
        trackingStats.pose();
        showTilt(pitchOf(pose.orientation));
      },
      camera: status => movementLog.event('camera', status),
      tracking: (status, reason) => {
        trackingStats.engine(status, reason);
        movementLog.event('engine tracking', `${status} ${reason}`);
      },
      status: (status, hint) => {
        trackingStats.status(status);
        const pausing = status !== 'tracked' && ownHold() !== null;
        const shown = hint && pausing
          ? `${hint}. The box stays where it was. Press and hold again once tracking returns`
          : hint;
        // Only a tracking hint is replaced on recovery; other messages are left alone.
        if (shown) element('view-status').textContent = shown;
        else if (trackingHint) element('view-status').textContent = viewInstruction();
        trackingHint = shown ?? '';
        if (pausing) {
          // A lost pose must not keep sliding the box. Let go where it last was.
          view?.predict(null);
          endHold();
        } else if (connected && ownHold() === null) publishTracking();
      },
      realigned: detail => movementLog.event('realigned', detail),
      restarted: () => {
        // 8th Wall's new world has its own place and scale: the person places themselves again.
        if (!roomViewOpen) return;
        openPhoneMap(true);
        mapReply = 'Tracking restarted · tap where you are';
        showPhoneMap();
      },
      placed: (spot, heading) => {
        trackingStats.placed(spot, heading);
        movementLog.event('placed', `at ${spot.x.toFixed(2)}, ${spot.z.toFixed(2)}${heading === null ? '' : `, heading ${heading.toFixed(2)} rad`}`);
      },
      calibrated: calibration => {
        trackingStats.calibrated(calibration);
        movementLog.event('calibration', calibration ?
          `${calibration.from} to ${calibration.to}: x${calibration.scale}, turned ${calibration.turn_deg} deg` :
          'undone: 8th Wall restarted or was recentred');
        if (!calibration) {
          // A new world: the height scale is measured again too, and a calibration part done is void.
          trackingStats.rescaling();
          element('view-status').textContent = 'Calibration undone · tap where you are on the map';
          // Tracking comes back in the same frame; this message, not the usual one, stays.
          trackingHint = '';
        }
        controls();
      },
      scaled: scale => {
        trackingStats.scale(scale);
        movementLog.event('scale', `x${scale.factor}: 8th Wall height ${scale.engine_height_m} m, real ${scale.real_height_m} m${scale.clamped ? ', clamped' : ''}`);
      },
      error: message => movementLog.event('engine error', message),
    }, phoneHeight);
    if (tracking !== measured) {
      steps.stop();
      tracking = measured;
    }
  }
  const unavailable = engine ? null : engineUnavailable();
  trackingStats.mode(engine ? 'measured' : 'steps', unavailable);
  const mode = engine ? 'measured' : `steps · ${unavailable}`;
  if (mode !== loggedMode) movementLog.event('mode', mode);
  loggedMode = mode;
}
/**
 * How high the phone is really held: `?height=1.35` in the link, or the height splat rooms are
 * scaled for. 8th Wall's distances are corrected by it over the height 8th Wall reports (#112).
 */
function heldAt(): number {
  const believable = (height: number) => height >= LOWEST_HELD && height <= HIGHEST_HELD;
  const given = Number(new URLSearchParams(location.search).get('height'));
  try {
    // Given once, it is kept on the phone, so links without it still use it.
    if (believable(given)) localStorage.setItem(HEIGHT_KEY, String(given));
    const kept = Number(localStorage.getItem(HEIGHT_KEY));
    if (believable(kept)) return kept;
  } catch {
    // Storage can be off, as in private browsing: the link alone then decides.
  }
  return believable(given) ? given : HELD_AT;
}
const HEIGHT_KEY = 'escape-my-room.phone-height';
/** Heights a phone may really be held at, in metres; anything else in the link is ignored. */
const LOWEST_HELD = 0.5;
const HIGHEST_HELD = 2.5;
/** Read when the page opens, so a link that gives it is kept even before connecting. */
const phoneHeight = heldAt();
/** The mode last written to the movement log, so each change is logged once. */
let loggedMode = '';
/** What the status line says about tracking, or empty while tracking is fine. */
let trackingHint = '';
/**
 * Both losses in the walk of 27 October came with the phone 40-60° down at the floor (#129): from
 * TILT_WARN down the person is asked to raise it, until it is back above TILT_CLEAR.
 */
const TILT_WARN = -45 * Math.PI / 180;
const TILT_CLEAR = -40 * Math.PI / 180;
let tooSteep = false;
/** Shows or hides the warning for the phone's pitch now, in radians; null hides it. */
function showTilt(pitch: number | null): void {
  const steep = pitch !== null && (tooSteep ? pitch < TILT_CLEAR : pitch < TILT_WARN);
  if (steep === tooSteep) return;
  tooSteep = steep;
  element('tilt-hint').hidden = !steep;
  if (pitch !== null) movementLog.event('tilt', steep ? `too steep: ${Math.round(pitch * 180 / Math.PI)}°` : 'raised');
}
/** What to do next in the room view, given the selection. */
function viewInstruction(): string {
  if (selected === null) return 'Tap the box to select it';
  const label = entityLabel(selected);
  return `${label.charAt(0).toUpperCase()}${label.slice(1)} selected · press and hold it to pick it up`;
}
/** Tells Python the phone's tracking now: where it is, or that it has no usable position, and why. */
function publishTracking(): void {
  const status = tracking.status;
  if (status === 'tracked') publishPose(tracking.reportedPose());
  else client.sendPose({ tracking_status: status, reference_space: null, position: null, heading: null, pitch: null });
}
/**
 * Tells Python where tracking has put the phone and where its screen centre aims, so the headset
 * shows it and a carried object follows the aim. Null says the phone is no longer tracked.
 */
function publishPose(pose: RoomPose | null): void {
  client.sendPose(pose ?
    {
      tracking_status: 'tracked', reference_space: 'room', position: pose.position,
      heading: headingOf(pose.orientation), pitch: pitchOf(pose.orientation),
    } :
    { tracking_status: 'inactive', reference_space: null, position: null, heading: null, pitch: null });
}
/**
 * Tracking runs whenever the room view is open. Call from a tap: iPhone asks for motion permission
 * and only allows it during the tap that asks.
 */
function startMotion(): void {
  // Opening the room view starts tracking, so the time to the first pose counts from here.
  trackingStats.opened();
  chooseTracking();
  void tracking.start().then(() => {
    // The engine reports its own start, through its status event.
    if (tracking !== steps) return;
    trackingStats.status('tracked', 'counting steps');
    element('view-status').textContent = 'Tap the box to select it';
    publishTracking();
  }).catch(error => {
    trackingStats.status('inactive', error instanceof Error ? error.message : 'motion access could not start');
    showRoomViewError(error, 'Motion access could not start.');
  }).finally(controls);
}
/** How often a device may publish where it is. Faster frames are dropped. */
const PRESENCE_INTERVAL_MS = 50;
let lastPresenceAt = -Infinity;
let presenceSent = false;

function publishPresence(): void {
  if (!connected || !role) return;
  // While tracking is lost the phone stays quiet, so Python marks it stale at its last good place.
  if (role === 'mobile_master' && roomViewOpen && tracking.status === 'lost') return;
  const sample = currentPresence();
  if (!sample) {
    if (!presenceSent) return;
    presenceSent = !client.sendPresence({ tracking_status: 'inactive', position: null, heading: null });
    return;
  }
  const now = performance.now();
  if (now - lastPresenceAt < PRESENCE_INTERVAL_MS) return;
  if (!client.sendPresence(sample)) return;
  lastPresenceAt = now;
  presenceSent = true;
}

/** The room pose this device can publish, or null when it has no place to report. */
function currentPresence(): PresenceInput | null {
  if (role === 'mobile_master') {
    // Starting tracking, the phone has no place to report yet.
    if (!roomViewOpen || (tracking === measured && tracking.status === 'inactive')) return null;
    // Before a turn reading the view faces the desk, which is heading 0.
    const pose = tracking.pose();
    return { tracking_status: 'tracked', position: pose.position, heading: headingOf(pose.orientation) };
  }
  const viewer = xr?.viewerPose() ?? null;
  const alignment = state?.alignment.vr_solver;
  if (!xrActive || !viewer || alignment?.status !== 'aligned') return null;
  return {
    tracking_status: 'tracked',
    position: roomPoint(alignment, viewer.position),
    heading: roomHeading(alignment, viewer.orientation),
  };
}
const depthButton = element<HTMLButtonElement>('depth-toggle');
/** The measured height to show the room from, or null for the default, and the height shown now. */
let measuredHeight: number | null = null;
let viewHeight = START_EYE.y;
const depth = new FloorDepth(element<HTMLVideoElement>('depth-camera'), () => tracking.orientation(), {
  status: message => { element('view-status').textContent = message; },
  phase: () => controls(),
  height: meters => {
    measuredHeight = meters;
    controls();
  },
});
const gazeButton = element<HTMLButtonElement>('gaze-toggle');
const gazeModeButton = element<HTMLButtonElement>('gaze-mode');
const gaze = new GazeCursor({
  video: element<HTMLVideoElement>('gaze-camera'), cursor: element('gaze-cursor'), layer: element('gaze-layer'),
  dot: element('gaze-dot'), prompt: element('gaze-prompt'),
}, {
  status: message => { element('view-status').textContent = message; },
  phase: phase => {
    // However the gaze cursor stops, its front camera is free again for the engine.
    if (phase === 'off') resumeTrackingAfterGaze();
    controls();
  },
  hover: point => {
    const id = view?.pointAt(point) ?? null;
    return id && entityLabel(id);
  },
});

const GAZE_PAUSE = 'paused for the gaze cursor';
/**
 * The phone runs one camera at a time: measured tracking waits while the gaze cursor uses the front
 * camera, and starts again from the starting viewpoint once the gaze cursor stops and the page shows.
 */
function pauseTrackingForGaze(): void {
  if (tracking !== measured) return;
  // The room is recentred on resuming; a held object must not be carried along with it.
  endHold();
  trackingStats.nextReason(GAZE_PAUSE);
  measured.pause(`Tracking ${GAZE_PAUSE} · stop it to track again`);
}
function resumeTrackingAfterGaze(): void {
  if (!measured?.paused || !roomViewOpen || gaze.getPhase() !== 'off' || document.visibilityState === 'hidden') return;
  trackingStats.restarted();
  void measured.resume().catch(error => showRoomViewError(error, 'Tracking could not start again.')).finally(controls);
}
document.addEventListener('visibilitychange', () => {
  // A hidden page must not keep a hold going with no one watching it.
  if (document.visibilityState === 'hidden' && role === 'mobile_master' && ownHold()) {
    view?.predict(null);
    endHold();
  }
  resumeTrackingAfterGaze();
});

function entityLabel(id: string): string {
  return state?.room.entities.find(entity => entity.id === id)?.label ?? id;
}

function showError(message: string): void {
  element('error').textContent = message;
  element('error').hidden = false;
}

function controls(): void {
  phoneButton.disabled = connected || busy;
  vrButton.disabled = connected || busy;
  disconnectButton.disabled = !connected;
  alignButton.disabled = !connected;
  startButton.disabled = !connected || busy || xrActive || xr === null;
  endButton.disabled = !xrActive;
  element('vr-controls').hidden = role !== 'vr_solver';
  element('phone-controls').hidden = role !== 'mobile_master';
  for (const id of ['walk-reset', 'walk-length']) element(id).hidden = tracking !== steps || !steps.active;
  const engine = tracking === measured ? measured : null;
  const measuring = engine !== null;
  element('recentre').hidden = !engine?.active || engine.paused;
  if (!engine?.active || engine.paused || !roomViewOpen) showTilt(null);
  // The headset chooses where it stands on the page's map; the phone places itself on its own.
  element('page-map').classList.toggle('picking', role === 'vr_solver');
  element('tracking-mode').textContent = !engine ? 'Tracking · step counting' :
    `Tracking · 8th Wall, ${engine.paused ? GAZE_PAUSE : 'measured'}`;
  if (element('phone-map').classList.contains('expanded')) showPhoneMap();
  // Measured tracking measures the height itself; the depth model is for step counting.
  depthButton.hidden = measuring;
  element('walk-length').textContent = `Step ${steps.stepLength.toFixed(1)} m`;
  depthButton.textContent = depth.getPhase() !== 'off' ? 'Cancel measuring' :
    measuredHeight === null ? 'Measure height' : 'Measure again';
  depthButton.disabled = !connected;
  element('depth-default').hidden = measuring || measuredHeight === null || depth.getPhase() !== 'off';
  gazeButton.textContent = gaze.getPhase() === 'off' ? 'Gaze cursor' : 'Stop gaze cursor';
  gazeButton.disabled = !connected;
  const pointing = gaze.getPhase() === 'tracking';
  for (const id of ['gaze-mode', 'gaze-calibrate', 'gaze-test']) element(id).hidden = !pointing;
  element('aim-reticle').hidden = !roomViewOpen || ownHold() === null;
  gazeModeButton.textContent = gaze.getMode() === 'eyes' ? 'Switch to head' : 'Switch to eyes';
}

/** Shows the room full screen on the phone, looking from the phone's place in the room. */
function setRoomView(open: boolean): void {
  const wasOpen = roomViewOpen;
  roomViewOpen = open;
  if (open) movementLog.begin();
  else if (wasOpen) trackingStats.closed();
  // Opening the room view with 8th Wall, the person first places themselves on the map (#127).
  // Each opening starts 8th Wall again from its own start, so the person is placed afresh.
  if (open && !wasOpen && tracking === measured) openPhoneMap(true);
  if (!open) openPhoneMap(false);
  if (open !== wasOpen) movementLog.event('room view', open ? 'opened' : 'closed');
  roomViewHud.hidden = !open;
  element('scene').classList.toggle('room-view', open);
  document.documentElement.classList.toggle('room-view-open', open);
  if (!open) {
    if (ownHold()) endHold();
    if (selected !== null) requestSelection(null);
    gaze.stop();
    depth.stop();
    // Height measurement may have started step turning alongside the engine; stop both. Closing an
    // open view also cancels an engine start still waiting on its permission prompt; a closed one
    // is also "closed" while connecting, when the start must go on.
    const wasTracking = tracking.active;
    steps.stop();
    if (wasOpen) measured?.stop();
    if (wasTracking && connected) publishPose(null);
    view?.follow(null);
  }
}

function presenceLabel(who: Role, next: SessionState): string {
  const name = who === 'mobile_master' ? 'Phone' : 'Headset';
  const presence = next.participants?.[who] ?? NO_PRESENCE;
  if (presence.tracking_status === 'inactive') return `${name} · not here`;
  if (presence.tracking_status === 'lost') return `${name} · left`;
  if (!presence.position || presence.heading === null) return `${name} · ${presence.tracking_status}`;
  const place = `${presence.position.x.toFixed(2)}, ${presence.position.y.toFixed(2)}, ${presence.position.z.toFixed(2)} m`;
  const facing = `heading ${presence.heading.toFixed(2)} rad`;
  if (presence.tracking_status === 'stale') return `${name} · stale · ${place} · ${facing}`;
  return `${name} · here · ${place} · ${facing}`;
}

function alignmentLabel(next: SessionState): string {
  if (!role) return 'Not aligned';
  if (role === 'mobile_master') return 'Not placed · walking only counts steps';
  const mine = next.alignment[role];
  if (mine.status !== 'aligned') return 'Not aligned';
  const origin = mine.origin;
  return `Aligned · yaw ${mine.yaw.toFixed(2)} rad · origin ${origin.x.toFixed(2)}, ${origin.y.toFixed(2)}, ${origin.z.toFixed(2)}`;
}

function roomLabel(next: SessionState, ready: boolean): string {
  if (!next.room.available || next.room.room_version === null) return 'Room not loaded';
  if (!ready) return `Room version ${next.room.room_version} · loading`;
  const names = next.room.entities.map(entity => (
    entity.kind === 'movable' ? `${entity.id} (movable)` : entity.id
  ));
  return `Room version ${next.room.room_version} · ${names.join(', ')}`;
}

/** The hold this phone owns, if Python has one in progress. */
function ownHold(): SessionState['manipulation'] {
  const held = state?.manipulation ?? null;
  return held && held.owner === 'mobile_master' && role === 'mobile_master' ? held : null;
}

function applyState(next: SessionState): void {
  if (!showsRevision(state?.revision ?? null, next.revision)) return;
  const otherRole = role === 'vr_solver' ? 'mobile_master' : 'vr_solver';
  const otherWas = role === 'vr_solver' ? state?.mobile_connected : state?.vr_connected;
  const otherNow = role === 'vr_solver' ? next.mobile_connected : next.vr_connected;
  const otherHeld = state?.manipulation?.owner === otherRole;
  const before = ownHold();
  state = next;
  view?.setLocalRole(role);
  for (const map of [phoneMap, pageMap]) {
    map.showRoom(next.room);
    map.showPlayers(next.participants, role);
  }
  motion.state();
  const held = next.manipulation;
  view?.showControl(held?.entity ?? null);
  // Another device's hold arrives a few times a second; draw it gliding between placements.
  view?.smooth(held && role && held.owner !== role ? held.entity : null);
  if (held && role === 'mobile_master' && held.owner === role) motion.acknowledge(held.sequence);
  element('control-status').textContent = held ?
    `${held.owner === 'mobile_master' ? 'Phone' : 'Headset'} is moving ${entityLabel(held.entity)}` :
    'No object is being moved';
  const mine = ownHold();
  if (mine && !holding) {
    // The pick-up was accepted after the finger lifted, so drop it at once.
    endHold();
  } else if (mine && !before) {
    element('view-status').textContent = `Carrying ${entityLabel(mine.entity)} · turn and tilt to place it, let go to drop it`;
  } else if (!mine && before) {
    releasing = null;
    carryFloor = null;
    view?.predict(null);
    element('view-status').textContent = tracking.status === 'lost' && trackingHint
      ? trackingHint
      : `Dropped ${entityLabel(before.entity)}`;
  }
  controls();
  view?.apply(next);
  if (role) view?.applyView(next.alignment[role]);
  const plan = floorplan(next.room.available ? next.room.entities : []);
  steps.setFloorplan(plan);
  carryBounds = plan.floor;
  const roomStatus = element('room-status');
  roomStatus.dataset.available = 'false';
  roomStatus.textContent = roomLabel(next, false);
  void view?.syncRoom(next).then(result => {
    if (!result || state?.room.room_version !== result.version) return;
    if (result.acknowledge) {
      client.sendRoomLoaded(result.version);
      movementLog.event('room', `loaded version ${result.version}`);
    }
    roomStatus.dataset.available = 'true';
    roomStatus.textContent = roomLabel(state ?? next, true);
  }).catch(error => {
    const message = error instanceof Error ? error.message : 'The prepared room could not be loaded.';
    roomStatus.dataset.available = 'false';
    roomStatus.textContent = message;
    movementLog.event('room', message);
    showError(message);
  });
  const p = next.marker.position;
  element('marker-position').textContent = p ? `${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)} m` : 'No accepted position';
  const labels = { inactive: 'Inactive · no positional input', tracked: 'Tracked',
    lost: 'Lost · position unavailable' };
  element('tracking').textContent = labels[next.marker.tracking_status];
  element('presence-phone').textContent = presenceLabel('mobile_master', next);
  element('presence-headset').textContent = presenceLabel('vr_solver', next);
  element('alignment-status').textContent = alignmentLabel(next);
  element('vr-status').textContent = next.vr_connected ? 'VR device connected' : 'Waiting for VR device';
  element('vr-status').dataset.connected = String(next.vr_connected);
  const headset = headsetHold();
  if (role === 'vr_solver' && !headset && grabOffset) {
    view?.predict(null);
    grabOffset = null;
    headsetReleasing = null;
  }
  if (headset && !gripDown) endHeadsetHold();
  if (headset) element('xr-grab').textContent = '';
  element('xr-hud').textContent = role === 'vr_solver'
    ? (headset
      ? `Holding ${entityLabel(headset.entity)} · release the grip to put it down`
      : next.manipulation
        ? `Phone is holding ${entityLabel(next.manipulation.entity)}`
        : next.alignment.vr_solver.status === 'aligned'
          ? 'Put the line on the box until it turns orange, then squeeze the grip'
          : 'Press A to confirm alignment')
    : (next.mobile_connected ? 'Phone connected' : 'Waiting for phone');
  if (otherWas && !otherNow) {
    const who = otherRole === 'mobile_master' ? 'Phone' : 'Headset';
    const left = otherHeld
      ? `${who} left. The box stays where it was. It can connect again.`
      : `${who} left. The room is still here. It can connect again.`;
    if (role === 'vr_solver') {
      headsetPauseNotice = left;
      view?.showNotice(left);
    } else if (roomViewOpen && tracking.status !== 'lost') element('view-status').textContent = left;
  } else if (!otherWas && otherNow && headsetPauseNotice?.endsWith('It can connect again.')) {
    headsetPauseNotice = null;
    if (role === 'vr_solver') view?.showNotice(null);
  }
}

const client = new SessionClient({
  state: applyState,
  connection: value => {
    connected = value;
    element('connection').textContent = value
      ? `Connected · ${role === 'mobile_master' ? 'Phone' : 'VR headset'}`
      : role
        ? 'Disconnected · press Connect to rejoin the same room'
        : 'Not connected';
    if (!value) {
      state = null;
      holding = false;
      carryFloor = null;
      releasing = null;
      gripDown = false;
      grabOffset = null;
      headsetReleasing = null;
      headsetPauseNotice = null;
      view?.predict(null);
      presenceSent = false;
      lastPresenceAt = -Infinity;
      element('marker-position').textContent = 'No accepted position';
      element('presence-phone').textContent = 'Phone · not here';
      element('presence-headset').textContent = 'Headset · not here';
      element('tracking').textContent = 'Disconnected · state unavailable';
      element('vr-status').textContent = 'Connect to see VR device status';
      element('vr-status').dataset.connected = 'false';
      element('room-status').textContent = 'Room not loaded';
      element('room-status').dataset.available = 'false';
      element('alignment-status').textContent = 'Not aligned';
      if (view) {
        view.applyView({ status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } });
        view.clearRoom();
        view.apply({
          revision: 0, mobile_connected: false, vr_connected: false,
          marker: { position: null, tracking_status: 'inactive', reference_space: null, heading: null, pitch: null },
          participants: { mobile_master: NO_PRESENCE, vr_solver: NO_PRESENCE },
          alignment: {
            mobile_master: { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } },
            vr_solver: { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } },
          },
          manipulation: null,
          delivery: { simulated_delay_ms: 0 },
          room: {
            available: false, room_version: null, units: null, frame: null, quaternion_order: null, error: null,
            entities: [], splat_url: null, splat_phone_url: null, splat_placement: null, landmarks: [], map: null, loaded_by: { mobile_master: null, vr_solver: null },
          },
        });
      }
      void xr?.end().catch(error => showError(xrError(error)));
      selected = null;
      setRoomView(false);
    }
    controls();
  },
  selection: result => {
    selected = result.id;
    view?.select(result.id);
    const label = result.id ? entityLabel(result.id) : '';
    const now = result.id ? `${label.charAt(0).toUpperCase()}${label.slice(1)} selected · press and hold it to pick it up` :
      'Tap the box to select it';
    // A refusal keeps the current selection, so say what is still selected.
    element('view-status').textContent = result.rejected ?
      `${result.rejected.message}${result.id ? ` ${entityLabel(result.id)} is still selected.` : ''}` : now;
    controls();
  },
  poseSent: sequence => motion.pose(sequence),
  poseReplaced: () => motion.replaced(),
  error: message => {
    showError(message);
    // The room view covers the page's error box, so its status line says it too.
    if (roomViewOpen) element('view-status').textContent = message;
    if (role === 'vr_solver') {
      element('xr-grab').textContent = message;
      view?.showNotice(message);
      if (!headsetHold()) {
        grabOffset = null;
        gripDown = false;
        view?.predict(null);
      }
    }
    // A refused grab must not keep a local carry. An error while this phone already holds
    // leaves that hold alone, so letting go still ends it.
    if (role === 'mobile_master' && !ownHold()) {
      holding = false;
      carryFloor = null;
      view?.predict(null);
    }
  },
});

/** Asks Python to end this phone's hold, once; the object stays where it is. */
function endHold(): void {
  const mine = ownHold();
  if (!mine || releasing === mine.id) return;
  releasing = mine.id;
  // Python places it from the latest aim, so it drops exactly where the phone shows it.
  if (tracking.status === 'tracked') publishPose(tracking.pose());
  client.sendRelease(mine.id);
  // The hold has ended, so a loss can be published without dropping the object.
  if (tracking.status !== 'tracked') publishTracking();
}

/** Asks Python to select a room object, or to deselect with null; Python decides what is eligible. */
function requestSelection(id: string | null): void {
  const version = state?.room.room_version;
  if (!connected || version === null || version === undefined) return;
  client.sendSelection(version, id);
}

/** Whether an entity can be picked up: only movable, selectable ones; furniture and floor cannot. */
function pickable(id: string | null): id is string {
  const entity = id === null ? undefined : state?.room.entities.find(candidate => candidate.id === id);
  return entity !== undefined && entity.kind === 'movable' && entity.selectable;
}

/**
 * A tap selects the object under the finger, or deselects on anything else. A press held on the
 * selected object picks it up, and lifting the finger drops it.
 */
function handleRoomTouches(sceneView: DiagnosticScene): void {
  const canvas = sceneView.renderer.domElement;
  let press: { pointer: number; target: string | null; timer: number } | null = null;
  canvas.addEventListener('pointerdown', event => {
    if (!roomViewOpen || role !== 'mobile_master' || press) return;
    const target = sceneView.entityAt({ x: event.offsetX / canvas.clientWidth, y: event.offsetY / canvas.clientHeight });
    canvas.setPointerCapture(event.pointerId);
    press = { pointer: event.pointerId, target, timer: 0 };
    if (target !== null && target === selected) {
      press.timer = window.setTimeout(() => {
        const version = state?.room.room_version;
        if (!press || selected === null || version === null || version === undefined) return;
        // Python refuses a hold without a position; say why here instead.
        if (tracking.status !== 'tracked') {
          element('view-status').textContent = trackingHint || 'Wait for tracking before picking it up';
          return;
        }
        holding = true;
        const id = selected;
        carryFloor = state?.room.entities.find(entity => entity.id === id)?.position.y ?? 0;
        if (tracking.status === 'tracked') publishPose(tracking.pose());
        client.sendAcquire(version, selected);
      }, PICK_UP_MS);
    }
  });
  const finish = (event: PointerEvent, tapped: boolean) => {
    if (!press || event.pointerId !== press.pointer) return;
    const { target, timer } = press;
    press = null;
    clearTimeout(timer);
    if (holding) {
      holding = false;
      endHold();
    } else if (tapped && target === selected && target !== null) {
      element('view-status').textContent = `Press and hold ${entityLabel(target)} to pick it up`;
    } else if (tapped && pickable(target)) {
      requestSelection(target);
    } else if (tapped && selected !== null) {
      requestSelection(null);
    } else if (tapped) {
      element('view-status').textContent = 'Tap the box to select it';
    }
  };
  canvas.addEventListener('pointerup', event => finish(event, true));
  canvas.addEventListener('pointercancel', event => finish(event, false));
  canvas.addEventListener('lostpointercapture', event => finish(event, false));
}

try {
  view = new DiagnosticScene(element('scene'));
  xr = new XRDiagnostic(view, overlay, (report, active) => {
    const wasActive = xrActive;
    xrActive = active;
    overlay.hidden = !active || report.dom_overlay === 'unavailable';
    element('device-report').textContent = JSON.stringify(report, null, 2);
    element('xr-support').textContent = !report.secure_context ?
      'VR needs trusted HTTPS. Desktop diagnostics can run on localhost.' : !report.api_available ?
      'WebXR unavailable. Use the Quest browser for VR.' :
      `VR ${report.immersive_vr ? 'available' : 'unavailable'}. Enter VR to test tracking and input.`;
    if (role === 'vr_solver' && wasActive && !active) pauseHeadsetHold('ended');
    else if (
      role === 'vr_solver' && active &&
      (report.positional_tracking === 'lost' || report.positional_tracking === 'emulated')
    ) pauseHeadsetHold('lost');
    controls();
  }, () => confirmAlignment(), () => pauseHeadsetHold('reset'));
  const sceneView = view;
  handleRoomTouches(sceneView);
  // `?smoothing=` sets the glide in milliseconds for trying other settings; 0 turns it off.
  const smoothing = new URLSearchParams(location.search).get('smoothing');
  if (smoothing !== null && Number(smoothing) >= 0 && Number(smoothing) <= 1000) {
    sceneView.smoothingMs = Number(smoothing);
  }
  sceneView.onCorrection = meters => motion.correction(meters);
  let lastFrame: number | null = null;
  let lastDrawn = -Infinity;
  let drawnPose = '';
  sceneView.renderer.setAnimationLoop((time, frame) => {
    xr?.frame(frame);
    sceneView.tick(lastFrame === null ? 0 : time - lastFrame);
    lastFrame = time;
    publishPresence();
    updateHeadsetGrab(time);
    if (roomViewOpen) {
      // A new height eases in rather than jumping.
      const target = measuredHeight ?? START_EYE.y;
      viewHeight += 0.05 * (target - viewHeight);
      const pose = tracking.pose();
      sceneView.follow(pose);
      movementLog.pose(trackingMode(), tracking.status, pose);
      const mine = ownHold();
      if (mine && carryFloor !== null && tracking.status === 'tracked') {
        // Drawn where the screen centre meets the floor now; Python confirms it a moment later.
        const held = state?.room.entities.find(entity => entity.id === mine.entity);
        const margin = held ? Math.max(held.size.width, held.size.depth) / 2 : 0;
        sceneView.predict(mine.entity, floorPoint(
          pose.position, headingOf(pose.orientation), pitchOf(pose.orientation), carryFloor, carryBounds, margin));
      }
      // Carrying sends the aim on time; measured tracking sends each new pose, at the same rate.
      const newPose = tracking === measured && measuredUnsent;
      // A held pose is not sent as tracked: while tracking is lost, Python keeps the last aim.
      if ((mine || newPose) && tracking.status === 'tracked' && time - lastCarryPose >= CARRY_POSE_MS) {
        lastCarryPose = time;
        measuredUnsent = false;
        publishPose(pose);
      }
    }
    // In the room view the phone draws when it has moved, and otherwise only often enough to
    // show what others change: drawing the same picture sixty times a second takes time from
    // 8th Wall, which then tracks fewer poses (#109).
    const pose = roomViewOpen && role === 'mobile_master' ? poseKey(tracking.pose()) : '';
    const changed = performance.now() - sceneView.changedAt < PHONE_SETTLE_MS;
    if (!pose || pose !== drawnPose || changed || time - lastDrawn >= PHONE_REDRAW_MS) {
      drawnPose = pose;
      lastDrawn = time;
      sceneView.renderer.render(sceneView.scene, sceneView.camera);
      trackingStats.frame(time);
    }
  });
  void xr.inspect().catch(error => showError(xrError(error)));
} catch {
  showError('The 3D view could not start. Enable WebGL/hardware acceleration and reload.');
}

async function connect(roleToJoin: Role): Promise<void> {
  busy = true;
  role = roleToJoin;
  element('error').hidden = true;
  controls();
  try {
    await client.join(roleToJoin);
    if (roleToJoin === 'mobile_master') {
      setRoomView(true);
      // Motion may have started before the connection did; tell Python where the phone starts.
      if (tracking.active) publishTracking();
    }
  } catch (error) {
    role = null;
    showError(error instanceof Error ? error.message : 'Unable to connect. Try again.');
  } finally {
    busy = false;
    controls();
  }
}

phoneButton.addEventListener('click', () => {
  startMotion();
  void connect('mobile_master');
});
vrButton.addEventListener('click', () => { void connect('vr_solver'); });
startButton.addEventListener('click', () => {
  if (!role || !xr) return;
  busy = true;
  element('error').hidden = true;
  controls();
  void xr.start().catch(error => showError(xrError(error))).finally(() => {
    busy = false;
    controls();
  });
});
const endXR = () => { void xr?.end().catch(error => showError(xrError(error))); };
endButton.addEventListener('click', endXR);
element('overlay-end-xr').addEventListener('click', endXR);
disconnectButton.addEventListener('click', () => {
  client.leave();
  endXR();
});
/** Shows a problem on the room view's status line too, since the overlay covers the page's error box. */
function showRoomViewError(error: unknown, fallback: string): void {
  const message = error instanceof Error ? error.message : fallback;
  showError(message);
  element('view-status').textContent = message;
}
gazeButton.addEventListener('click', () => {
  if (gaze.getPhase() !== 'off') {
    gaze.stop();
    return;
  }
  element('error').hidden = true;
  // The phone runs one camera at a time: the engine's back camera too, until the gaze cursor stops.
  if (depth.getPhase() !== 'off') depth.stop('Height measurement stopped for the gaze cursor.');
  pauseTrackingForGaze();
  void gaze.start().catch(error => showRoomViewError(error, 'The gaze cursor could not start.')).finally(controls);
});
gazeModeButton.addEventListener('click', () => {
  gaze.setMode(gaze.getMode() === 'eyes' ? 'head' : 'eyes');
  controls();
});
element('walk-reset').addEventListener('click', () => {
  // Going back to the start must not carry a held object back with it.
  endHold();
  publishPose(steps.reset());
  element('view-status').textContent = 'Back at the start';
});
element('recentre').addEventListener('click', () => {
  // Recentring must not carry a held object along with the room.
  endHold();
  measured?.recenter();
  // While lost, the loss hint stays: it says what to do first.
  if (tracking.status === 'tracked') element('view-status').textContent = 'Recentred · this is now the start, facing the desk';
});
/** The room's map in a corner of the phone's room view; tapping it opens it to place the phone. */
const phoneMap = new RoomMap(element('phone-map'), 'phone-map', { pick: placeOnMap });
/** The room's map on the page, where the headset chooses where it stands. */
const pageMap = new RoomMap(element('page-map'), 'page-map', { pick: standOnMap });
const phoneMapRoot = element('phone-map');
/** What the map last said after a tap, such as why it was refused; null for its usual prompt. */
let mapReply: string | null = null;
function openPhoneMap(open: boolean): void {
  mapReply = null;
  phoneMapRoot.classList.toggle('expanded', open);
  element('phone-map-close').hidden = !open;
  element('phone-map-prompt').hidden = !open;
  if (open) showPhoneMap();
  else phoneMapRoot.classList.remove('picking');
}
/** The open map's prompt, and whether it takes taps: 8th Wall may start after it opened. */
function showPhoneMap(): void {
  const engine = tracking === measured && measured?.active ? measured : null;
  phoneMapRoot.classList.toggle('picking', engine !== null);
  element('phone-map-prompt').textContent = !engine ? 'Placing on the map needs 8th Wall tracking' :
    mapReply ?? (engine.placedOnMap ? 'Placed · walk 2 m or more and tap where you are, to set the scale' :
      'Place yourself: tap where you stand, and drag the way you face');
}
// Only a tap begun on the small map opens it: the tap that calibrates closes it, then ends here.
let mapTappedSmall = false;
phoneMapRoot.addEventListener('pointerdown', () => { mapTappedSmall = !phoneMapRoot.classList.contains('expanded'); });
phoneMapRoot.addEventListener('click', () => {
  if (mapTappedSmall && !phoneMapRoot.classList.contains('expanded')) openPhoneMap(true);
});
element('phone-map-close').addEventListener('click', event => {
  event.stopPropagation();
  // The first tap is kept: the person closes the map to walk, then opens it to tap again.
  openPhoneMap(false);
});
/** The person taps where they stand on the phone's map: the phone is placed there (#124). */
function placeOnMap(spot: Spot, heading: number | null): void {
  if (tracking !== measured || !measured.active) return;
  try {
    // A held object stays where it was; the room moves to where the person says they are.
    endHold();
    const calibration = measured.placeAt(spot, heading);
    mapReply = null;
    if (!calibration) {
      showPhoneMap();
      return;
    }
    openPhoneMap(false);
    element('view-status').textContent = `Calibrated · ×${calibration.scale.toFixed(2)} · turned ${calibration.turn_deg}°`;
  } catch (error) {
    if (!(error instanceof CalibrationRefused)) throw error;
    mapReply = error.message;
    showPhoneMap();
  }
}
/**
 * The headset player chooses where they stand in the room's copy: their alignment is turned and
 * moved so that where they are now is `spot`, facing `heading`.
 */
function standOnMap(spot: Spot, heading: number | null): void {
  if (role !== 'vr_solver' || !connected) return;
  const now = xr?.confirmedAlignment() ?? { yaw: 0, origin: { x: 0, y: 0, z: 0 } };
  // A tap without a drag keeps the way the player faces now, as the phone does.
  const aligned = state?.alignment.vr_solver;
  const turn = heading ?? (aligned?.status === 'aligned' ? aligned.yaw - now.yaw : 0);
  const cosine = Math.cos(turn);
  const sine = Math.sin(turn);
  const { x, y, z } = now.origin;
  client.sendCalibration({
    yaw: Math.atan2(Math.sin(now.yaw + turn), Math.cos(now.yaw + turn)),
    origin: { x: cosine * x + sine * z + spot.x, y, z: -sine * x + cosine * z + spot.z },
  });
}
element('walk-length').addEventListener('click', () => {
  steps.stepLength = STEP_LENGTHS[(STEP_LENGTHS.indexOf(steps.stepLength as typeof STEP_LENGTHS[number]) + 1) % STEP_LENGTHS.length];
  controls();
});
depthButton.addEventListener('click', () => {
  if (depth.getPhase() !== 'off') {
    depth.stop();
    return;
  }
  element('error').hidden = true;
  if (gaze.getPhase() !== 'off') gaze.stop('Gaze cursor stopped to measure the height.');
  // Both permission requests start inside the button press; iPhone refuses them after it.
  void Promise.all([depth.start(), steps.startTurning()]).catch(error => {
    depth.stop();
    showRoomViewError(error, 'The height could not be measured.');
  }).finally(controls);
});
element('depth-default').addEventListener('click', () => {
  measuredHeight = null;
  element('view-status').textContent = `Default height · ${START_EYE.y.toFixed(2)} m`;
  controls();
});
element('gaze-calibrate').addEventListener('click', () => gaze.calibrate());
element('gaze-test').addEventListener('click', () => gaze.test());
element('gaze-cancel').addEventListener('click', () => gaze.cancel());
element('open-room-view').addEventListener('click', () => {
  startMotion();
  setRoomView(true);
});
element('close-room-view').addEventListener('click', () => setRoomView(false));
/** The hold this headset owns, if Python has one in progress. */
function headsetHold(): SessionState['manipulation'] {
  const held = state?.manipulation ?? null;
  return held && role === 'vr_solver' && held.owner === 'vr_solver' ? held : null;
}

/** Asks Python to end the headset's hold, once. The object stays where the grip left it. */
function endHeadsetHold(): void {
  const mine = headsetHold();
  if (!mine || headsetReleasing === mine.id) return;
  headsetReleasing = mine.id;
  gripDown = false;
  client.sendRelease(mine.id);
}

/**
 * Tracking or the VR session can no longer move the object. A lost pose leaves the alignment.
 * A reset or leaving VR forgets it, because that origin is no longer the one that was saved.
 */
function pauseHeadsetHold(reason: 'lost' | 'ended' | 'reset'): void {
  const held = headsetHold() !== null;
  endHeadsetHold();
  grabOffset = null;
  gripDown = false;
  if (reason === 'lost' && !held) return;
  headsetPauseNotice = reason === 'lost'
    ? 'Tracking lost. The object stays where it was. Squeeze the grip again when the line is orange.'
    : 'Line the room up again. Press A. The object stays where it was.';
  view?.showNotice(headsetPauseNotice);
}

/** Grip and target ray in room meters, after alignment. */
function roomGrip(sample: ControllerSample): {
  position: Position;
  orientation: Rotation;
  rayOrigin: Position;
  rayDirection: Position;
} | null {
  const alignment = state?.alignment.vr_solver;
  if (
    !alignment || alignment.status !== 'aligned' ||
    !sample.position || !sample.orientation || !sample.rayOrigin || !sample.rayDirection
  ) return null;
  return {
    position: roomPoint(alignment, sample.position),
    orientation: roomOrientation(alignment, sample.orientation),
    rayOrigin: roomPoint(alignment, sample.rayOrigin),
    rayDirection: roomDirection(alignment, sample.rayDirection),
  };
}

/** Pointing rays in local space, and whether each one is on a movable object. */
function headsetRays(): {
  origin: Position; direction: Position; onTarget: boolean; blocked: boolean; hit: string | null;
}[] {
  const alignment = state?.alignment.vr_solver;
  const entities = state?.room.entities ?? [];
  const aligned = alignment?.status === 'aligned';
  const taken = state?.manipulation?.owner === 'mobile_master' ? state.manipulation.entity : null;
  return (xr?.aimRays() ?? []).map(ray => {
    const hit = aligned && alignment
      ? targetAlongRay(roomPoint(alignment, ray.origin), roomDirection(alignment, ray.direction), entities)
      : null;
    const blocked = hit !== null && hit === taken;
    return { origin: ray.origin, direction: ray.direction, onTarget: hit !== null && !blocked, blocked, hit: blocked ? null : hit };
  });
}

/**
 * Before alignment, the grip confirms it. After alignment, a grip squeeze on the box grabs it,
 * and letting go puts it down. The box keeps its offset from the grip, so it does not jump.
 */
function updateHeadsetGrab(time: number): void {
  if (role !== 'vr_solver') return;
  const sample = xr?.controller();
  const rays = xrActive ? headsetRays() : [];
  view?.showAim(rays, rays.find(ray => ray.hit)?.hit ?? null);
  const phoneHold = state?.manipulation?.owner === 'mobile_master' ? state.manipulation : null;
  const mineNow = headsetHold();
  if (headsetPauseNotice && !mineNow) view?.showNotice(headsetPauseNotice);
  else if (rays.some(ray => ray.blocked)) view?.showNotice('The other person is holding that object.');
  else if (phoneHold) view?.showNotice(`Phone is holding ${entityLabel(phoneHold.entity)}`);
  else if (mineNow) view?.showNotice(`Holding ${entityLabel(mineNow.entity)} · release the grip`);
  else if (xrActive) view?.showNotice(null);
  if (!xrActive || !sample) {
    if (headsetHold()) endHeadsetHold();
    return;
  }
  const aligned = state?.alignment.vr_solver.status === 'aligned';
  if (sample.started && !aligned) {
    headsetPauseNotice = null;
    confirmAlignment();
    return;
  }
  if (sample.started && aligned) {
    headsetPauseNotice = null;
    const posed = roomGrip(sample);
    const version = state?.room.room_version;
    const entities = state?.room.entities ?? [];
    const hit = posed ? targetAlongRay(posed.rayOrigin, posed.rayDirection, entities) : null;
    const box = hit ? entities.find(entity => entity.id === hit) : undefined;
    const taken = hit !== null && state?.manipulation?.owner === 'mobile_master' && state.manipulation.entity === hit;
    if (taken) {
      gripDown = false;
      const message = 'The other person is holding that object.';
      view?.showNotice(message);
      element('xr-hud').textContent = message;
      element('xr-grab').textContent = message;
    } else if (!posed || !hit || !box || version === null || version === undefined) {
      gripDown = false;
      element('xr-hud').textContent = 'Put the line on the box until it turns orange, then squeeze the grip';
    } else {
      gripDown = true;
      grabOffset = offsetOf(posed.position, posed.orientation, box.position);
      client.sendAcquire(version, hit, { position: posed.position, orientation: posed.orientation });
    }
  }
  if (sample.ended) {
    gripDown = false;
    endHeadsetHold();
  }
  const mine = headsetHold();
  const posed = sample.pressed ? roomGrip(sample) : null;
  if (mine && gripDown && posed && grabOffset) {
    view?.predict(mine.entity, grabbedPosition(posed.position, posed.orientation, grabOffset));
    if (time - lastGripPose >= GRIP_POSE_MS) {
      lastGripPose = time;
      client.sendGrip(mine.id, { position: posed.position, orientation: posed.orientation });
    }
  }
}

const confirmAlignment = () => {
  if (!connected) return;
  headsetPauseNotice = null;
  client.sendCalibration(xr?.confirmedAlignment() ?? { yaw: 0, origin: { x: 0, y: 0, z: 0 } });
};
alignButton.addEventListener('click', confirmAlignment);
element('overlay-confirm-alignment').addEventListener('click', confirmAlignment);

let holdEvents = 0;
const holdProbe = element<HTMLButtonElement>('hold-probe');
holdProbe.addEventListener('pointerdown', event => {
  holdProbe.setPointerCapture(event.pointerId);
  holdProbe.dataset.held = 'true';
  holdEvents++;
});
for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  holdProbe.addEventListener(event, () => { holdProbe.dataset.held = 'false'; });
}
overlay.addEventListener('beforexrselect', event => event.preventDefault());
element('send-log').addEventListener('click', () => {
  // Python saves it on the computer it runs on, so nothing has to be copied off the phone.
  void fetch('/api/movement-logs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    // With the report's tracking summary, so a device walk needs nothing downloaded on the phone.
    body: JSON.stringify({ ...movementLog.report(), tracking: trackingStats.report(view?.splatDrawn ?? null) }),
  }).then(async response => {
    // A proxy in front of a stopped Python answers with text, not JSON.
    const answer = await response.json().catch(() => ({})) as { entries?: number; detail?: string };
    if (!response.ok) throw new Error(answer.detail ?? 'The movement log could not be saved.');
    element('view-status').textContent = `Log sent · ${answer.entries} entries`;
  }).catch(error => showRoomViewError(error, 'The movement log could not be sent.'));
});
element('download-report').addEventListener('click', () => {
  const report = {
    recorded_at: new Date().toISOString(), role, xr: xr?.getReport() ?? null,
    gaze: gaze.report(), floor_height: depth.report(), user_agent: navigator.userAgent,
    dom_overlay_hold_events: holdEvents, marker: state?.marker ?? null,
    motion: {
      ...motion.report({
        smoothing_ms: view?.smoothingMs ?? null, simulated_delay_ms: state?.delivery.simulated_delay_ms ?? null,
      }),
      tracking: trackingStats.report(view?.splatDrawn ?? null),
    },
    evidence: 'Browser observations only; complete the manual device smoke-test record separately.',
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'escape-my-room-device-report.json';
  link.click();
  URL.revokeObjectURL(url);
});
window.addEventListener('pagehide', () => client.leave());
window.setInterval(() => {
  element('motion-stats').textContent = motion.summary();
  element('tracking-stats').textContent = trackingStats.summary();
}, 1000);
controls();
