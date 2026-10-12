import './style.css';
import type { Role, SessionState, TrackingSource } from './protocol';
import { SessionClient } from './session';
import { DiagnosticScene } from './scene';
import { XRDiagnostic, xrError } from './xr';

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing interface element: ${id}`);
  return found as T;
}

const createButton = element<HTMLButtonElement>('create-session');
const joinButton = element<HTMLButtonElement>('join-session');
const leaveButton = element<HTMLButtonElement>('leave-session');
const startButton = element<HTMLButtonElement>('start-xr');
const endButton = element<HTMLButtonElement>('end-xr');
const sourceInput = element<HTMLSelectElement>('pose-input');
const sessionInput = element<HTMLInputElement>('session-id');
const overlay = element('xr-overlay');
let role: Role | null = null;
let connected = false;
let busy = false;
let xrActive = false;
let state: SessionState | null = null;
let view: DiagnosticScene | null = null;
let xr: XRDiagnostic | null = null;

function showError(message: string): void {
  element('error').textContent = message;
  element('error').hidden = false;
}

function controls(): void {
  createButton.disabled = connected || busy;
  joinButton.disabled = connected || busy;
  sourceInput.disabled = connected || busy;
  sessionInput.disabled = connected || busy;
  leaveButton.disabled = !connected;
  startButton.disabled = !connected || busy || xrActive || xr === null ||
    (role === 'mobile_master' && sourceInput.value === 'simulator');
  endButton.disabled = !xrActive;
  element('simulator').hidden = !(connected && role === 'mobile_master' && sourceInput.value === 'simulator');
  startButton.textContent = role === 'vr_solver' ? 'Enter VR' : 'Enter AR';
}

function applyState(next: SessionState): void {
  if (state && next.session_id === state.session_id && next.revision < state.revision) return;
  state = next;
  view?.apply(next);
  const p = next.marker.position;
  element('marker-position').textContent = p ? `${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)} m` : 'No accepted position';
  const labels = { inactive: 'Inactive · no positional input', tracked: 'Tracked · WebXR',
    lost: 'Lost · marker unavailable', emulated: 'Emulated · not positional tracking',
    simulated: 'SIMULATED · synthetic input' };
  element('tracking').textContent = labels[next.marker.tracking_status];
  element('participants').textContent = next.participants.map(
    p => `${p.role === 'mobile_master' ? 'Master' : 'Solver'}: ${p.connected ? 'connected' : 'joining'}`,
  ).join(' · ');
  element('xr-hud').textContent = `${element('tracking').textContent} · ${element('marker-position').textContent}`;
}

const client = new SessionClient({
  state: applyState,
  connection: value => {
    connected = value;
    element('connection').textContent = value ? `Connected · ${role === 'mobile_master' ? 'Mobile master' : 'VR solver'}` : 'Disconnected · rejoin or create a new session';
    if (!value) {
      state = null;
      element('marker-position').textContent = 'No accepted position';
      element('tracking').textContent = 'Disconnected · state unavailable';
      if (view) view.apply({ session_id: '', revision: 0, participants: [], marker: {
        participant_id: null, source: null, position: null, tracking_status: 'inactive', reference_space: null,
      } });
      void xr?.end().catch(error => showError(xrError(error)));
    }
    controls();
  },
  error: showError,
});

try {
  view = new DiagnosticScene(element('scene'));
  xr = new XRDiagnostic(view, overlay, pose => client.sendPose(pose), (report, active) => {
    xrActive = active;
    overlay.hidden = !active || report.dom_overlay === 'unavailable';
    element('device-report').textContent = JSON.stringify(report, null, 2);
    element('xr-support').textContent = !report.secure_context ?
      'XR needs trusted HTTPS. Desktop diagnostics can run on localhost.' : !report.api_available ?
      'WebXR unavailable. Mobile view works; physical phone tracking is pending on iPhone Chrome.' :
      `AR ${report.immersive_ar ? 'available' : 'unavailable'} · VR ${report.immersive_vr ? 'available' : 'unavailable'}. Enter XR to test tracking and input.`;
    controls();
  });
  const sceneView = view;
  sceneView.renderer.setAnimationLoop((time, frame) => {
    xr?.frame(time, frame);
    sceneView.renderer.render(sceneView.scene, sceneView.camera);
  });
  void xr.inspect().catch(error => showError(xrError(error)));
} catch {
  showError('The 3D view could not start. Enable WebGL/hardware acceleration and reload.');
}

const initialSession = new URL(location.href).searchParams.get('session');
if (initialSession) sessionInput.value = initialSession;

async function connect(roleToJoin: Role, create: boolean): Promise<void> {
  busy = true;
  role = roleToJoin;
  element('error').hidden = true;
  controls();
  try {
    const id = create ? await client.create() : sessionInput.value.trim();
    if (!id) throw new Error('Paste the session ID or open the master’s solver invite link.');
    sessionInput.value = id;
    await client.join(id, roleToJoin, sourceInput.value as TrackingSource);
    const invite = new URL(location.href);
    invite.searchParams.set('session', id);
    element<HTMLInputElement>('invite-link').value = invite.href;
  } catch (error) {
    role = null;
    showError(error instanceof Error ? error.message : 'Unable to join this session.');
  } finally {
    busy = false;
    controls();
  }
}

createButton.addEventListener('click', () => { void connect('mobile_master', true); });
joinButton.addEventListener('click', () => { void connect('vr_solver', false); });
startButton.addEventListener('click', () => {
  if (!role || !xr) return;
  busy = true;
  element('error').hidden = true;
  controls();
  void xr.start(role).catch(error => showError(xrError(error))).finally(() => {
    busy = false;
    controls();
  });
});
const endXR = () => { void xr?.end().catch(error => showError(xrError(error))); };
endButton.addEventListener('click', endXR);
element('overlay-end-xr').addEventListener('click', endXR);
leaveButton.addEventListener('click', () => { client.leave(); endXR(); });
element('send-simulated').addEventListener('click', () => {
  const position = {
    x: element<HTMLInputElement>('sim-x').valueAsNumber,
    y: element<HTMLInputElement>('sim-y').valueAsNumber,
    z: element<HTMLInputElement>('sim-z').valueAsNumber,
  };
  if (Object.values(position).some(value => !Number.isFinite(value) || Math.abs(value) > 100)) {
    showError('Enter finite simulator coordinates between −100 and 100 meters.');
    return;
  }
  client.sendPose({ tracking_status: 'simulated', reference_space: 'local', position });
});

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
