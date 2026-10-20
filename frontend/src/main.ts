import './style.css';
import { RoomPhotos } from './capture';
import { element } from './dom';
import { FloorDepth } from './floor-depth';
import { GazeCursor } from './gaze-cursor';
import { RoomPreparation } from './preparation';
import { PhoneLook, START_EYE, headingOf, phoneViewpoint } from './phone-view';
import type { Role, SessionState } from './protocol';
import { SessionClient } from './session';
import { DiagnosticScene } from './scene';
import { STEP_LENGTHS, StepWalker } from './step-walk';
import { floorplan, type Sensitivity } from './steps';
import { XRDiagnostic, xrError } from './xr';

const phoneButton = element<HTMLButtonElement>('connect-phone');
const vrButton = element<HTMLButtonElement>('connect-vr');
const disconnectButton = element<HTMLButtonElement>('disconnect');
const alignButton = element<HTMLButtonElement>('confirm-alignment');
const startButton = element<HTMLButtonElement>('start-xr');
const endButton = element<HTMLButtonElement>('end-xr');
const lookButton = element<HTMLButtonElement>('look-around');
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
const deselectButton = element<HTMLButtonElement>('deselect');
const look = new PhoneLook();
const walkButton = element<HTMLButtonElement>('walk-toggle');
const walker = new StepWalker(START_EYE, () => {
  const facing = look.orientation();
  return facing ? headingOf(facing) : 0;
}, {
  step: (position, steps) => {
    element('view-status').textContent = `Walking · ${steps} ${steps === 1 ? 'step' : 'steps'}`;
    publishWalk(position);
  },
});
/** Tells Python where walking has put the phone, so the headset shows it there. */
function publishWalk(position: { x: number; y: number; z: number } | null): void {
  client.sendPose(position ?
    { tracking_status: 'tracked', reference_space: 'room', position } :
    { tracking_status: 'inactive', reference_space: null, position: null });
}
const depthButton = element<HTMLButtonElement>('depth-toggle');
/** The measured height to show the room from, or null for the default, and the height shown now. */
let measuredHeight: number | null = null;
let viewHeight = START_EYE.y;
const depth = new FloorDepth(element<HTMLVideoElement>('depth-camera'), () => look.orientation(), {
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
  lookButton.textContent = look.active ? 'Stop turning' : 'Turn with phone';
  walkButton.textContent = walker.active ? 'Stop walking' : 'Walk with steps';
  walkButton.disabled = !connected;
  for (const id of ['walk-reset', 'walk-length', 'walk-sensitivity']) element(id).hidden = !walker.active;
  element('walk-length').textContent = `Step ${walker.stepLength.toFixed(1)} m`;
  element('walk-sensitivity').textContent = `Sensitivity: ${walker.sensitivity}`;
  depthButton.textContent = depth.getPhase() !== 'off' ? 'Cancel measuring' :
    measuredHeight === null ? 'Measure height' : 'Measure again';
  depthButton.disabled = !connected;
  element('depth-default').hidden = measuredHeight === null || depth.getPhase() !== 'off';
  gazeButton.textContent = gaze.getPhase() === 'off' ? 'Gaze cursor' : 'Stop gaze cursor';
  gazeButton.disabled = !connected;
  const pointing = gaze.getPhase() === 'tracking';
  for (const id of ['gaze-mode', 'gaze-calibrate', 'gaze-test']) element(id).hidden = !pointing;
  deselectButton.hidden = selected === null;
  gazeModeButton.textContent = gaze.getMode() === 'eyes' ? 'Switch to head' : 'Switch to eyes';
}

/** Shows the room full screen on the phone, looking from the phone's place in the room. */
function setRoomView(open: boolean): void {
  roomViewOpen = open;
  roomViewHud.hidden = !open;
  element('scene').classList.toggle('room-view', open);
  document.documentElement.classList.toggle('room-view-open', open);
  if (!open) {
    if (selected !== null) requestSelection(null);
    gaze.stop();
    depth.stop();
    if (walker.active) {
      walker.stop();
      if (connected) publishWalk(null);
    }
    view?.follow(null);
  }
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

function applyState(next: SessionState): void {
  if (state && next.revision < state.revision) return;
  state = next;
  view?.apply(next);
  if (role) view?.applyView(next.alignment[role]);
  walker.setFloorplan(floorplan(next.room.available ? next.room.entities : []));
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
      element('marker-position').textContent = 'No accepted position';
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
          marker: { position: null, tracking_status: 'inactive', reference_space: null },
          alignment: {
            mobile_master: { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } },
            vr_solver: { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } },
          },
          room: {
            available: false, room_version: null, units: null, frame: null, quaternion_order: null, error: null,
            entities: [], loaded_by: { mobile_master: null, vr_solver: null },
          },
        });
      }
      void xr?.end().catch(error => showError(xrError(error)));
      look.stop();
      selected = null;
      setRoomView(false);
    }
    controls();
  },
  selection: result => {
    selected = result.id;
    view?.select(result.id);
    const now = result.id ? `Selected ${entityLabel(result.id)}` : 'Nothing selected';
    // A refusal keeps the current selection, so say what is still selected.
    element('view-status').textContent = result.rejected ?
      `${result.rejected.message}${result.id ? ` ${entityLabel(result.id)} is still selected.` : ''}` : now;
    controls();
  },
  error: showError,
});

/** Asks Python to select a room object, or to deselect with null; Python decides what is eligible. */
function requestSelection(id: string | null): void {
  const version = state?.room.room_version;
  if (!connected || version === null || version === undefined) return;
  client.sendSelection(version, id);
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
  // A tap on the room view selects the object drawn there.
  sceneView.renderer.domElement.addEventListener('click', event => {
    if (!roomViewOpen || role !== 'mobile_master') return;
    const canvas = sceneView.renderer.domElement;
    const id = sceneView.entityAt({ x: event.offsetX / canvas.clientWidth, y: event.offsetY / canvas.clientHeight });
    if (id === null) {
      element('view-status').textContent = 'Nothing to select there';
      return;
    }
    requestSelection(id);
  });
  sceneView.renderer.setAnimationLoop((_time, frame) => {
    xr?.frame(frame);
    if (roomViewOpen) {
      // A new height eases in rather than jumping.
      const target = measuredHeight ?? START_EYE.y;
      viewHeight += 0.05 * (target - viewHeight);
      sceneView.follow(phoneViewpoint(look, { ...walker.position(), y: viewHeight }));
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
    if (roleToJoin === 'mobile_master') setRoomView(true);
  } catch (error) {
    role = null;
    showError(error instanceof Error ? error.message : 'Unable to connect. Try again.');
  } finally {
    busy = false;
    controls();
  }
}

phoneButton.addEventListener('click', () => { void connect('mobile_master'); });
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
lookButton.addEventListener('click', () => {
  if (look.active) {
    look.stop();
    element('view-status').textContent = 'Turning off';
    controls();
    return;
  }
  void look.start().then(() => {
    element('view-status').textContent = 'Turning with the phone';
  }).catch(error => showRoomViewError(error, 'Motion access could not start.')).finally(controls);
});
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
walkButton.addEventListener('click', () => {
  if (walker.active) {
    walker.stop();
    publishWalk(null);
    element('view-status').textContent = 'Walking off';
    controls();
    return;
  }
  element('error').hidden = true;
  // Both permission requests start inside the button press; iPhone refuses them after it.
  const turning = look.active ? Promise.resolve() : look.start();
  void Promise.all([walker.start(), turning]).then(() => {
    element('view-status').textContent = 'Walking · 0 steps';
    publishWalk(walker.target());
  }).catch(error => {
    walker.stop();
    showRoomViewError(error, 'Motion access could not start.');
  }).finally(controls);
});
element('walk-reset').addEventListener('click', () => {
  publishWalk(walker.reset());
  element('view-status').textContent = 'Back at the start';
});
element('walk-length').addEventListener('click', () => {
  walker.stepLength = STEP_LENGTHS[(STEP_LENGTHS.indexOf(walker.stepLength as typeof STEP_LENGTHS[number]) + 1) % STEP_LENGTHS.length];
  controls();
});
element('walk-sensitivity').addEventListener('click', () => {
  const order: Sensitivity[] = ['normal', 'high', 'low'];
  walker.setSensitivity(order[(order.indexOf(walker.sensitivity) + 1) % order.length]);
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
  const turning = look.active ? Promise.resolve() : look.start();
  void Promise.all([depth.start(), turning]).catch(error => {
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
deselectButton.addEventListener('click', () => requestSelection(null));
element('open-room-view').addEventListener('click', () => setRoomView(true));
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
element('download-report').addEventListener('click', () => {
  const report = {
    recorded_at: new Date().toISOString(), role, xr: xr?.getReport() ?? null,
    gaze: gaze.report(), floor_height: depth.report(), user_agent: navigator.userAgent,
    dom_overlay_hold_events: holdEvents, marker: state?.marker ?? null,
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
controls();

const roomPreparation = new RoomPreparation();
const roomPhotos = new RoomPhotos(capture => { void roomPreparation.showCapture(capture); });
void roomPhotos.showLatest().catch(() => undefined);
