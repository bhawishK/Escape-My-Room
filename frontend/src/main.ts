import './style.css';
import { RoomPhotos } from './capture';
import { element } from './dom';
import { RoomPreparation } from './preparation';
import { PhoneTracker } from './phone-tracking';
import { PhoneLook, PhoneViewpoint } from './phone-view';
import type { Role, SessionState } from './protocol';
import { SessionClient } from './session';
import { DiagnosticScene } from './scene';
import { XRDiagnostic, xrError } from './xr';

const phoneButton = element<HTMLButtonElement>('connect-phone');
const vrButton = element<HTMLButtonElement>('connect-vr');
const disconnectButton = element<HTMLButtonElement>('disconnect');
const alignButton = element<HTMLButtonElement>('confirm-alignment');
const startButton = element<HTMLButtonElement>('start-xr');
const endButton = element<HTMLButtonElement>('end-xr');
const trackButton = element<HTMLButtonElement>('start-tracking');
const stopTrackingButton = element<HTMLButtonElement>('stop-tracking');
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
let tracker: PhoneTracker | null = null;
let roomViewOpen = false;
const look = new PhoneLook();
const viewpoint = new PhoneViewpoint(look);

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
  const cameraIdle = tracker?.getMode() === 'off';
  trackButton.hidden = !cameraIdle;
  trackButton.disabled = !connected;
  stopTrackingButton.hidden = cameraIdle;
  lookButton.textContent = look.active ? 'Stop turning' : 'Turn with phone';
}

/** Shows the room full screen on the phone, looking from the phone's place in the room. */
function setRoomView(open: boolean): void {
  roomViewOpen = open;
  roomViewHud.hidden = !open;
  element('scene').classList.toggle('room-view', open);
  document.documentElement.classList.toggle('room-view-open', open);
  if (!open) view?.follow(null);
}

function alignmentLabel(next: SessionState): string {
  if (!role) return 'Not aligned';
  if (role === 'mobile_master') {
    return next.marker.tracking_status === 'tracked' ? 'Placed by the room markers' : 'Not placed · track a room marker';
  }
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
  tracker?.setMarkers(next.room.available ? next.room.markers : []);
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
  const labels = { inactive: 'Inactive · no positional input', tracked: 'Tracked · room markers',
    lost: 'Lost · marker unavailable' };
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
            entities: [], markers: [], loaded_by: { mobile_master: null, vr_solver: null },
          },
        });
      }
      void xr?.end().catch(error => showError(xrError(error)));
      if (tracker?.getMode() !== 'off') tracker?.stop('Tracking stopped because the phone disconnected.');
      look.stop();
      setRoomView(false);
    }
    controls();
  },
  error: showError,
});

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
  sceneView.renderer.setAnimationLoop((_time, frame) => {
    xr?.frame(frame);
    if (roomViewOpen) sceneView.follow(viewpoint.current());
    sceneView.renderer.render(sceneView.scene, sceneView.camera);
  });
  void xr.inspect().catch(error => showError(xrError(error)));
} catch {
  showError('The 3D view could not start. Enable WebGL/hardware acceleration and reload.');
}
tracker = new PhoneTracker(element<HTMLVideoElement>('camera-feed'), {
  publish: pose => client.sendPose(pose),
  measured: pose => viewpoint.measured(pose),
  status: status => {
    const line = element('tracking-status');
    line.textContent = status.message;
    line.dataset.mode = status.mode;
    line.dataset.tracked = String(status.tracked);
    controls();
  },
});

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
  if (tracker?.getMode() !== 'off') tracker?.stop();
  client.leave();
  endXR();
});
/** Shows a problem on the room view's status line too, since the overlay covers the page's error box. */
function showRoomViewError(error: unknown, fallback: string): void {
  const message = error instanceof Error ? error.message : fallback;
  showError(message);
  element('tracking-status').textContent = message;
}
trackButton.addEventListener('click', () => {
  element('error').hidden = true;
  void tracker?.start().catch(error => showRoomViewError(error, 'The camera could not start.')).finally(controls);
});
stopTrackingButton.addEventListener('click', () => tracker?.stop());
lookButton.addEventListener('click', () => {
  if (look.active) {
    look.stop();
    controls();
    return;
  }
  void look.start().catch(error => showRoomViewError(error, 'Motion access could not start.')).finally(controls);
});
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
    tracking: tracker?.report() ?? null, user_agent: navigator.userAgent,
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
