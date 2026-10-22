import './style.css';
import { roomHeading, roomPoint } from './alignment';
import { RoomPhotos } from './capture';
import { element } from './dom';
import { FloorDepth } from './floor-depth';
import { GazeCursor } from './gaze-cursor';
import { RoomPreparation } from './preparation';
import { floorPoint } from './aim';
import { MotionStats } from './motion-stats';
import { CameraSwitch } from './camera-switch';
import { EngineTracking, engineUnavailable, trackingEngine } from './engine-tracking';
import { MovementLog, type TrackingMode } from './movement-log';
import { StepTracking, type PhoneTracking } from './phone-tracking';
import { START_EYE, headingOf, pitchOf, type RoomPose } from './phone-view';
import { NO_PRESENCE, type PresenceInput, type Role, type SessionState } from './protocol';
import { SessionClient } from './session';
import { DiagnosticScene } from './scene';
import { STEP_LENGTHS } from './step-walk';
import { floorplan, type Floorplan } from './steps';
import { XRDiagnostic, xrError } from './xr';

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
/** How long a press on the selected object lasts before it is picked up, so a tap is not. */
const PICK_UP_MS = 300;
/** While carrying, the phone tells Python where it is and faces this often, so the object follows. */
const CARRY_POSE_MS = 100;
let lastCarryPose = 0;
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
      moved: () => { measuredUnsent = true; },
      camera: status => {
        movementLog.event('camera', status);
        cameraSwitch.cameraStatus(status);
      },
      frame: (status, reason, raw) => {
        // Only a pose the engine trusts is a fair `before` for measuring a switch.
        if (status === 'NORMAL') lastRawPose = raw;
        cameraSwitch.engineFrame(status, reason, raw);
      },
      tracking: (status, reason) => movementLog.event('engine tracking', `${status} ${reason}`),
      status: (_, hint) => {
        // Only a tracking hint is replaced on recovery; other messages are left alone. A camera
        // switch reports its own stages and result instead.
        if (cameraSwitch.running) { /* the switch says what is happening */ } else if (hint) element('view-status').textContent = hint;
        else if (trackingHint) element('view-status').textContent = viewInstruction();
        trackingHint = hint;
        // A loss during a hold is kept from Python, which would drop the object; the aim holds.
        if (connected && ownHold() === null) publishTracking();
      },
      realigned: detail => movementLog.event('realigned', detail),
      error: message => movementLog.event('engine error', message),
    });
    if (tracking !== measured) {
      steps.stop();
      tracking = measured;
    }
  }
  const mode = engine ? 'measured' : `steps · ${engineUnavailable()}`;
  if (mode !== loggedMode) movementLog.event('mode', mode);
  loggedMode = mode;
}
/** The held, sensor-turned view last sent to Python, so an unchanged one is not sent again. */
let lastHeldKey = '';
const poseKey = (pose: RoomPose) => [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w].map(v => v.toFixed(3)).join();
/** The engine's last pose as it gave it, for measuring a camera switch. */
let lastRawPose: RoomPose | null = null;
// `?switch-timeout-ms=` shortens the wait for tracking after a switch, for tests.
const switchTimeout = Number(new URLSearchParams(location.search).get('switch-timeout-ms')) || undefined;
/** The camera-switch experiment (#74): pause the engine, use the front camera, resume. */
const cameraSwitch = new CameraSwitch({
  pauseEngine: () => measured?.pause(),
  resumeEngine: () => measured?.resume(),
  openFrontCamera: () => navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false }),
  rawPose: () => lastRawPose,
  status: message => {
    // A switch cancelled by closing the room view has nowhere to show its result.
    if (roomViewOpen) element('view-status').textContent = message;
    controls();
  },
  log: (name, detail, data) => movementLog.event(name, detail, data),
}, switchTimeout);
/** The mode last written to the movement log, so each change is logged once. */
let loggedMode = '';
/** What the status line says about tracking, or empty while tracking is fine. */
let trackingHint = '';
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
  chooseTracking();
  void tracking.start().then(() => {
    // The engine reports its own start, through its status event.
    if (tracking !== steps) return;
    element('view-status').textContent = 'Tap the box to select it';
    publishTracking();
  }).catch(error => {
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
  phase: () => controls(),
  hover: point => {
    const id = view?.pointAt(point) ?? null;
    return id && entityLabel(id);
  },
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
  element('recentre').hidden = tracking !== measured || !measured.active;
  element('switch-cameras').hidden = tracking !== measured || !measured.active;
  element<HTMLButtonElement>('switch-cameras').disabled = cameraSwitch.running;
  element('tracking-mode').textContent = tracking === measured ? 'Tracking · 8th Wall, measured' : 'Tracking · step counting';
  element('walk-length').textContent = `Step ${steps.stepLength.toFixed(1)} m`;
  depthButton.textContent = depth.getPhase() !== 'off' ? 'Cancel measuring' :
    measuredHeight === null ? 'Measure height' : 'Measure again';
  depthButton.disabled = !connected;
  element('depth-default').hidden = measuredHeight === null || depth.getPhase() !== 'off';
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
  if (open !== wasOpen) movementLog.event('room view', open ? 'opened' : 'closed');
  roomViewHud.hidden = !open;
  element('scene').classList.toggle('room-view', open);
  document.documentElement.classList.toggle('room-view-open', open);
  if (!open) {
    if (selected !== null) requestSelection(null);
    cameraSwitch.cancel();
    lastRawPose = null;
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
  if (state && next.revision < state.revision) return;
  const before = ownHold();
  state = next;
  view?.setLocalRole(role);
  motion.state();
  const held = next.manipulation;
  view?.showControl(held?.entity ?? null);
  // Another device's hold arrives a few times a second; draw it gliding between placements.
  view?.smooth(held && role && held.owner !== role ? held.entity : null);
  if (held && held.owner === role) motion.acknowledge(held.sequence);
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
    element('view-status').textContent = `Dropped ${entityLabel(before.entity)}`;
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
    if (result.acknowledge) client.sendRoomLoaded(result.version);
    roomStatus.dataset.available = 'true';
    roomStatus.textContent = roomLabel(state ?? next, true);
  }).catch(error => {
    const message = error instanceof Error ? error.message : 'The prepared room could not be loaded.';
    roomStatus.dataset.available = 'false';
    roomStatus.textContent = message;
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
  element('xr-hud').textContent = next.mobile_connected ? 'Phone connected' : 'Waiting for phone';
}

const client = new SessionClient({
  state: applyState,
  connection: value => {
    connected = value;
    element('connection').textContent = value ? `Connected · ${role === 'mobile_master' ? 'Phone' : 'VR headset'}` : 'Not connected';
    if (!value) {
      state = null;
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
            entities: [], loaded_by: { mobile_master: null, vr_solver: null },
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
  // A loss during the hold was kept from Python so the hold went on; say it now.
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
        if (cameraSwitch.running) {
          element('view-status').textContent = 'Wait for the camera switch to finish before picking it up';
          return;
        }
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
    xrActive = active;
    overlay.hidden = !active || report.dom_overlay === 'unavailable';
    element('device-report').textContent = JSON.stringify(report, null, 2);
    element('xr-support').textContent = !report.secure_context ?
      'VR needs trusted HTTPS. Desktop diagnostics can run on localhost.' : !report.api_available ?
      'WebXR unavailable. Use the Quest browser for VR.' :
      `VR ${report.immersive_vr ? 'available' : 'unavailable'}. Enter VR to test tracking and input.`;
    controls();
  }, () => confirmAlignment());
  const sceneView = view;
  handleRoomTouches(sceneView);
  // `?smoothing=` sets the glide in milliseconds for trying other settings; 0 turns it off.
  const smoothing = new URLSearchParams(location.search).get('smoothing');
  if (smoothing !== null && Number(smoothing) >= 0 && Number(smoothing) <= 1000) {
    sceneView.smoothingMs = Number(smoothing);
  }
  sceneView.onCorrection = meters => motion.correction(meters);
  let lastFrame: number | null = null;
  sceneView.renderer.setAnimationLoop((time, frame) => {
    xr?.frame(frame);
    sceneView.tick(lastFrame === null ? 0 : time - lastFrame);
    lastFrame = time;
    publishPresence();
    if (roomViewOpen) {
      // A new height eases in rather than jumping.
      const target = measuredHeight ?? START_EYE.y;
      viewHeight += 0.05 * (target - viewHeight);
      const pose = tracking.pose();
      sceneView.follow(pose);
      movementLog.pose(trackingMode(), tracking.status, pose);
      const mine = ownHold();
      if (mine && carryFloor !== null) {
        // Drawn where the screen centre meets the floor now; Python confirms it a moment later.
        const held = state?.room.entities.find(entity => entity.id === mine.entity);
        const margin = held ? Math.max(held.size.width, held.size.depth) / 2 : 0;
        sceneView.predict(mine.entity, floorPoint(
          pose.position, headingOf(pose.orientation), pitchOf(pose.orientation), carryFloor, carryBounds, margin));
      }
      // Carrying sends the aim on time; measured tracking sends each new pose, at the same rate.
      // While the engine is away the view turns with the sensor; each new turn is sent at the same rate.
      const heldTurned = tracking === measured && measured.viewHeld && poseKey(pose) !== lastHeldKey;
      const newPose = tracking === measured && (measuredUnsent || heldTurned);
      if (heldTurned) lastHeldKey = poseKey(pose);
      // A held pose is not sent as tracked: while tracking is lost, Python keeps the last aim.
      if ((mine || newPose) && tracking.status === 'tracked' && time - lastCarryPose >= CARRY_POSE_MS) {
        lastCarryPose = time;
        measuredUnsent = false;
        publishPose(pose);
      }
    }
    sceneView.renderer.render(sceneView.scene, sceneView.camera);
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
  // The phone runs one camera at a time.
  if (depth.getPhase() !== 'off') depth.stop('Height measurement stopped for the gaze cursor.');
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
element('switch-cameras').addEventListener('click', () => {
  // Switching while carrying, or picking up, would leave the box with no aim to follow.
  if (ownHold() !== null || holding) {
    element('view-status').textContent = 'Let go of the box before switching cameras';
    return;
  }
  void cameraSwitch.run().finally(controls);
});
element('recentre').addEventListener('click', () => {
  // Recentring must not carry a held object along with the room.
  endHold();
  measured?.recenter();
  // While lost, the loss hint stays: it says what to do first.
  if (tracking.status === 'tracked') element('view-status').textContent = 'Recentred · this is now the start, facing the desk';
});
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
const confirmAlignment = () => {
  if (!connected) return;
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
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(movementLog.report()),
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
    motion: motion.report({
      smoothing_ms: view?.smoothingMs ?? null, simulated_delay_ms: state?.delivery.simulated_delay_ms ?? null,
    }),
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
window.setInterval(() => { element('motion-stats').textContent = motion.summary(); }, 1000);
controls();

const roomPreparation = new RoomPreparation();
const roomPhotos = new RoomPhotos(capture => { void roomPreparation.showCapture(capture); });
void roomPhotos.showLatest().catch(() => undefined);
