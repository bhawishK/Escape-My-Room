/**
 * The voice call between the phone and the headset (#13), used unchanged by both pages. The two
 * browsers send audio straight to each other with WebRTC; Python only passes the set-up messages
 * (`voice_ready` and `voice_signal`, see docs/diagnostic-protocol.md) and never hears anything.
 */
import type { Role, SessionState, VoiceSignal, VoiceSignalInput } from './protocol';

/** Where the call stands, for the status line. */
export type VoicePhase = 'off' | 'asking' | 'waiting' | 'connecting' | 'connected' | 'failed';

export interface VoiceStatus {
  phase: VoicePhase;
  /** Why voice is off or failed, in words for the person; null otherwise. */
  problem: string | null;
  /** Whether the other person's audio is arriving. */
  receiving: boolean;
  /** Whether this device's microphone is muted, and whether the other person's is. */
  muted: boolean;
  peerMuted: boolean;
  /** How the connected call reaches the other person; null until it is known. */
  path: VoicePath | null;
}

/**
 * The pair of addresses the call settled on. Each end is `host` (its own address), `srflx` or
 * `prflx` (its public address, found with STUN or by the other end), or `relay` (a TURN server).
 */
export interface VoicePath {
  local: string;
  remote: string;
  /** Whether the audio goes through a TURN relay rather than straight between the devices. */
  relayed: boolean;
  protocol: string | null;
}

interface VoiceOptions {
  /** Tells Python this device has its microphone open, or has stopped. */
  sendReady: (ready: boolean) => void;
  /** Passes one set-up message to the other person through Python. */
  sendSignal: (signal: VoiceSignalInput) => void;
  /** Tells Python, and so the other person, that this microphone is muted or not. */
  sendMuted: (muted: boolean) => void;
  /** Called whenever the status changes. */
  changed: (status: VoiceStatus) => void;
}

/** Used if the server's voice settings cannot be read: finds each device's public address. */
const FALLBACK: RTCConfiguration = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };

/** The STUN and TURN servers from the server's settings (`GET /api/voice/config`, #172). */
async function loadConfiguration(): Promise<RTCConfiguration> {
  try {
    const response = await fetch('/api/voice/config');
    if (!response.ok) return FALLBACK;
    const config = await response.json() as { ice_servers: RTCIceServer[]; relay_only: boolean };
    return { iceServers: config.ice_servers, iceTransportPolicy: config.relay_only ? 'relay' : 'all' };
  } catch {
    return FALLBACK;
  }
}
/** How often the call checks that audio is arriving, in milliseconds. */
const STATS_MS = 1000;
/**
 * A call that has not connected this long after it was set up, or after it dropped, is tried once
 * more over a fresh path. If that takes this long too, the call has failed.
 */
const CONNECT_MS = 12_000;
const NO_PATH = 'The two devices found no way to reach each other. Stop voice and start it again, or try another network.';
/** Kept for this tab, so pressing Connect after a reload brings voice back. */
const WANTED_KEY = 'escape-my-room-voice';

/** One connection to the other person, for one of their voice sessions. */
interface Call {
  peer: RTCPeerConnection;
  /** The other person's voice session this call was set up with. */
  peerSession: number;
  /** Candidates that arrived before the description they belong to. */
  early: RTCIceCandidateInit[];
  described: boolean;
  /** Whether the one retry over a fresh path has been used. */
  retried: boolean;
  /** Runs out when the call takes too long to connect. */
  deadline: number | null;
}

const other = (role: Role): Role => (role === 'mobile_master' ? 'vr_solver' : 'mobile_master');

/** Why the microphone could not be opened, in words for the person. */
function microphoneProblem(error: unknown): string {
  const name = error instanceof DOMException ? error.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'The microphone was not allowed. Allow it for this site in the browser, then press Start voice again.';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found on this device.';
  if (name === 'NotReadableError') return 'The microphone is in use by something else. Close that, then press Start voice again.';
  return 'The microphone could not be opened. Press Start voice to try again.';
}

export class VoiceCall {
  private role: Role | null = null;
  private microphone: MediaStream | null = null;
  private call: Call | null = null;
  /** Whether Python has been told, on this connection, that this device is ready. */
  private announced = false;
  private phase: VoicePhase = 'off';
  private problem: string | null = null;
  private receiving = false;
  private muted = false;
  private peerMuted = false;
  private path: VoicePath | null = null;
  private configuration: RTCConfiguration = FALLBACK;
  /** How often a call has needed its one retry, and failed, since the page loaded. */
  private retries = 0;
  private failures = 0;
  private received = 0;
  private statsTimer: number | null = null;
  /** Start and stop requests are counted, so a slow microphone prompt cannot undo a later stop. */
  private attempt = 0;
  /** Plays the other person. In the page, because iPhone only plays audio elements that are. */
  private readonly speaker = document.createElement('audio');

  constructor(private readonly options: VoiceOptions) {
    this.speaker.autoplay = true;
    this.speaker.setAttribute('playsinline', '');
    this.speaker.hidden = true;
    this.speaker.dataset.testid = 'voice-speaker';
    document.body.append(this.speaker);
    // Leaving the page lets the microphone go at once, without waiting for the browser to tidy up.
    window.addEventListener('pagehide', () => this.connectionLost());
  }

  get status(): VoiceStatus {
    return {
      phase: this.phase, problem: this.problem, receiving: this.receiving,
      muted: this.muted, peerMuted: this.peerMuted, path: this.path,
    };
  }

  /** For the diagnostic report. Addresses and TURN logins are left out. */
  report(): Record<string, unknown> {
    return {
      phase: this.phase,
      problem: this.problem,
      receiving: this.receiving,
      muted: this.muted,
      peer_muted: this.peerMuted,
      path: this.path,
      ice_servers: (this.configuration.iceServers ?? []).flatMap(server => server.urls),
      relay_only: this.configuration.iceTransportPolicy === 'relay',
      retries: this.retries,
      failures: this.failures,
    };
  }

  /** Mutes or unmutes this microphone. The call stays up, and the other person is told. */
  setMuted(muted: boolean): void {
    if (!this.microphone || muted === this.muted) return;
    this.muted = muted;
    for (const track of this.microphone.getAudioTracks()) track.enabled = !muted;
    this.options.sendMuted(muted);
    this.options.changed(this.status);
  }

  /** Whether voice is on: the microphone is open or being asked for. */
  get on(): boolean {
    return this.phase !== 'off';
  }

  /** Whether voice was on in this tab before a reload. */
  get wanted(): boolean {
    try {
      return sessionStorage.getItem(WANTED_KEY) === 'on';
    } catch {
      return false;
    }
  }

  /**
   * Opens the microphone and tells Python this device is ready. Call it from a tap: iPhone only
   * asks for the microphone, and only plays the other person, after one.
   */
  async start(role: Role): Promise<void> {
    if (this.on) return;
    this.role = role;
    const attempt = ++this.attempt;
    this.set('asking', null);
    // Started inside the tap, so the browser lets the other person's audio play when it arrives.
    void this.speaker.play().catch(() => undefined);
    if (!navigator.mediaDevices?.getUserMedia) {
      this.set('off', isSecureContext ? 'This browser has no microphone access.' : 'Voice needs the trusted HTTPS link.');
      return;
    }
    // Asked for first, still inside the tap; the settings are read while the browser asks.
    const settings = loadConfiguration();
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      if (attempt === this.attempt) this.set('off', microphoneProblem(error));
      return;
    }
    this.configuration = await settings;
    if (attempt !== this.attempt) {
      // Stopped while the browser was asking.
      for (const track of stream.getTracks()) track.stop();
      return;
    }
    this.microphone = stream;
    this.remember(true);
    this.announce();
    this.set('waiting', null);
  }

  /** Ends this device's part of the call and lets the microphone go. */
  stop(): void {
    this.attempt += 1;
    this.remember(false);
    this.end(null);
  }

  /** The session's connection dropped: the call ends and the microphone is let go. */
  connectionLost(): void {
    this.attempt += 1;
    this.end(null, false);
  }

  /** Follows who is ready to talk, setting the call up or taking it down. */
  applyState(state: SessionState): void {
    if (!this.microphone || !this.role) return;
    const mine = state.voice[this.role];
    const theirs = state.voice[other(this.role)];
    if (theirs.muted !== this.peerMuted) {
      this.peerMuted = theirs.muted;
      this.options.changed(this.status);
    }
    // A rejoin starts not ready on the server; say so again.
    if (!mine.ready && !this.announced) this.announce();
    const call = this.call;
    // The call is over when they stopped, or started again as a newer session than it was made
    // for. A call made for a newer session than this state shows is ahead of the state: keep it.
    if (call && (call.peerSession < theirs.session || (call.peerSession === theirs.session && !theirs.ready))) {
      this.hangUp();
    }
    if (mine.ready && theirs.ready && !this.call) {
      const made = this.connect(theirs.session);
      // The phone always offers, so the two never offer at once.
      if (this.role === 'mobile_master') void this.offer(made);
    }
    if (!this.call && this.phase !== 'waiting') this.set('waiting', null);
  }

  /** One set-up message from the other person, passed on by Python. */
  async signal(message: VoiceSignal): Promise<void> {
    if (!this.microphone || !this.role || message.from === this.role) return;
    let call = this.call;
    if (call && message.session < call.peerSession) return;
    if (message.kind === 'offer') {
      if (this.role === 'mobile_master') return;
      // An offer can arrive before the state that says they are ready, and one from a newer
      // session replaces the call.
      if (!call || call.peerSession !== message.session) {
        this.hangUp();
        call = this.connect(message.session);
      }
    }
    if (!call || call.peerSession !== message.session) return;
    try {
      if (message.kind === 'candidate') {
        if (!message.candidate) return;
        if (call.described) await call.peer.addIceCandidate(message.candidate);
        else call.early.push(message.candidate);
        return;
      }
      await call.peer.setRemoteDescription({ type: message.kind, sdp: message.sdp ?? '' });
      call.described = true;
      for (const candidate of call.early.splice(0)) await call.peer.addIceCandidate(candidate);
      if (message.kind === 'offer') {
        await call.peer.setLocalDescription(await call.peer.createAnswer());
        if (this.call === call) this.options.sendSignal({ kind: 'answer', sdp: call.peer.localDescription?.sdp ?? '' });
      }
    } catch {
      if (this.call === call) this.set('failed', 'The call could not be set up. Stop voice and start it again.');
    }
  }

  private announce(): void {
    this.announced = true;
    this.options.sendReady(true);
  }

  private remember(wanted: boolean): void {
    try {
      if (wanted) sessionStorage.setItem(WANTED_KEY, 'on');
      else sessionStorage.removeItem(WANTED_KEY);
    } catch {
      // Private browsing: voice still works, it just is not brought back after a reload.
    }
  }

  private connect(peerSession: number): Call {
    const peer = new RTCPeerConnection(this.configuration);
    const call: Call = { peer, peerSession, early: [], described: false, retried: false, deadline: null };
    this.call = call;
    for (const track of this.microphone?.getTracks() ?? []) peer.addTrack(track, this.microphone!);
    peer.addEventListener('icecandidate', event => {
      if (this.call !== call) return;
      this.options.sendSignal({ kind: 'candidate', candidate: event.candidate ? event.candidate.toJSON() : null });
    });
    peer.addEventListener('track', event => {
      if (this.call !== call) return;
      this.speaker.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      void this.speaker.play().catch(() => undefined);
    });
    peer.addEventListener('connectionstatechange', () => {
      if (this.call !== call) return;
      const state = peer.connectionState;
      if (state === 'connected') {
        this.await(call, false);
        this.set('connected', null);
        void this.measure(call);
      } else if (state === 'failed') {
        this.struggling(call);
      } else if (state === 'disconnected') {
        // A dropped path often comes back by itself; give it the same time as a new call.
        this.set('connecting', null);
        this.await(call, true);
      }
    });
    this.received = 0;
    this.statsTimer = window.setInterval(() => void this.measure(call), STATS_MS);
    this.set('connecting', null);
    this.await(call, true);
    return call;
  }

  /** Starts, or with `false` stops, the wait for this call to connect. */
  private await(call: Call, waiting: boolean): void {
    if (call.deadline !== null) clearTimeout(call.deadline);
    call.deadline = waiting ? window.setTimeout(() => {
      call.deadline = null;
      if (this.call === call && call.peer.connectionState !== 'connected') this.struggling(call);
    }, CONNECT_MS) : null;
  }

  /**
   * The call could not connect, or dropped and did not come back. The first time, it is tried
   * once more over a fresh path: the phone, which makes the offers, restarts it, and the headset
   * waits for that. The second time, the call has failed, and both pages say so.
   */
  private struggling(call: Call): void {
    if (this.call !== call) return;
    if (call.retried) {
      this.await(call, false);
      this.failures += 1;
      this.set('failed', NO_PATH);
      return;
    }
    call.retried = true;
    this.retries += 1;
    this.set('connecting', null);
    this.await(call, true);
    if (this.role === 'mobile_master') void this.offer(call, true);
  }

  private async offer(call: Call, restart = false): Promise<void> {
    try {
      await call.peer.setLocalDescription(await call.peer.createOffer({ iceRestart: restart }));
      if (this.call === call) this.options.sendSignal({ kind: 'offer', sdp: call.peer.localDescription?.sdp ?? '' });
    } catch {
      if (this.call === call) this.set('failed', 'The call could not be set up. Stop voice and start it again.');
    }
  }

  /** Whether the other person's audio has arrived since the last look. */
  private async measure(call: Call): Promise<void> {
    let bytes = 0;
    let path: VoicePath | null = null;
    try {
      const stats = await call.peer.getStats();
      for (const report of stats.values()) {
        if (report.type === 'inbound-rtp' && report.kind === 'audio') bytes += report.bytesReceived ?? 0;
        // The pair of addresses in use: named by the transport, or, in Firefox, marked selected.
        const pair = report.type === 'transport' ? stats.get(report.selectedCandidatePairId)
          : report.type === 'candidate-pair' && report.selected ? report : null;
        const local = pair ? stats.get(pair.localCandidateId) : null;
        const remote = pair ? stats.get(pair.remoteCandidateId) : null;
        if (local && remote) {
          path = {
            local: local.candidateType, remote: remote.candidateType,
            relayed: local.candidateType === 'relay' || remote.candidateType === 'relay',
            protocol: local.relayProtocol ?? local.protocol ?? null,
          };
        }
      }
    } catch {
      return;
    }
    if (this.call !== call) return;
    const receiving = bytes > this.received;
    this.received = bytes;
    const moved = JSON.stringify(path) !== JSON.stringify(this.path);
    if (receiving !== this.receiving || (path && moved)) {
      this.receiving = receiving;
      if (path) this.path = path;
      this.options.changed(this.status);
    }
  }

  private hangUp(): void {
    if (this.statsTimer !== null) clearInterval(this.statsTimer);
    this.statsTimer = null;
    if (this.call) this.await(this.call, false);
    this.call?.peer.close();
    this.call = null;
    this.speaker.srcObject = null;
    this.receiving = false;
    this.path = null;
  }

  private end(problem: string | null, tell = true): void {
    this.hangUp();
    for (const track of this.microphone?.getTracks() ?? []) track.stop();
    const was = this.microphone !== null;
    this.microphone = null;
    if (was && tell && this.announced) this.options.sendReady(false);
    this.announced = false;
    this.muted = false;
    this.peerMuted = false;
    this.set('off', problem);
  }

  private set(phase: VoicePhase, problem: string | null): void {
    this.phase = phase;
    this.problem = problem;
    this.options.changed(this.status);
  }
}

/** The status line both pages show. `them` names the other device, such as "the headset". */
export function voiceLine(status: VoiceStatus, them: string): string {
  switch (status.phase) {
    case 'off': return status.problem ? `Voice off · ${status.problem}` : 'Voice off';
    case 'asking': return 'Allow the microphone to talk';
    case 'waiting': return `Voice on · waiting for ${them} to start voice`;
    case 'connecting': return 'Voice connecting…';
    case 'connected': {
      const notes = [
        status.path ? (status.path.relayed ? 'relayed' : 'direct') : null,
        status.muted ? 'you are muted' : null,
        status.peerMuted ? `${them} is muted` : null,
      ].filter(Boolean);
      return ['Voice connected', ...notes].join(' · ');
    }
    case 'failed': return `Voice failed · ${status.problem ?? NO_PATH}`;
  }
}

/**
 * A short line for inside VR, where the page and its buttons are out of sight (#173): what the
 * person needs to know about the call now, or null when there is nothing to say. `them` names
 * the other device, and `unmute` says how to unmute from here, such as "press B or Y".
 */
export function voiceNote(status: VoiceStatus, them: string, unmute: string): string | null {
  switch (status.phase) {
    case 'off': return status.problem ? 'Voice is off' : null;
    case 'asking': return null;
    case 'waiting': return `Voice · waiting for ${them}`;
    case 'connecting': return 'Voice connecting…';
    case 'failed': return 'Voice failed · leave VR to start it again';
    case 'connected':
      if (status.muted) return `You are muted · ${unmute} to unmute`;
      return status.peerMuted ? `Voice connected · ${them} is muted` : 'Voice connected';
  }
}
