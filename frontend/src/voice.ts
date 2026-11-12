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
}

interface VoiceOptions {
  /** Tells Python this device has its microphone open, or has stopped. */
  sendReady: (ready: boolean) => void;
  /** Passes one set-up message to the other person through Python. */
  sendSignal: (signal: VoiceSignalInput) => void;
  /** Called whenever the status changes. */
  changed: (status: VoiceStatus) => void;
}

/** Finds each device's public address. Issue #172 makes this a server setting. */
const ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];
/** How often the call checks that audio is arriving, in milliseconds. */
const STATS_MS = 1000;
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
}

const other = (role: Role): Role => (role === 'mobile_master' ? 'vr_solver' : 'mobile_master');

/** Why the microphone could not be opened, in words for the person. */
function microphoneProblem(error: unknown): string {
  const name = error instanceof DOMException ? error.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'The microphone was not allowed.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.';
  if (name === 'NotReadableError') return 'The microphone is in use by something else.';
  return 'The microphone could not be opened.';
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
  }

  get status(): VoiceStatus {
    return { phase: this.phase, problem: this.problem, receiving: this.receiving };
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
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      if (attempt === this.attempt) this.set('off', microphoneProblem(error));
      return;
    }
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
      if (this.call === call) this.set('failed', 'The call could not be set up.');
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
    const peer = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    const call: Call = { peer, peerSession, early: [], described: false };
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
      if (state === 'connected') this.set('connected', null);
      else if (state === 'failed') this.set('failed', 'The call could not connect.');
      else if (state === 'disconnected' || state === 'connecting') this.set('connecting', null);
    });
    this.received = 0;
    this.statsTimer = window.setInterval(() => void this.measure(call), STATS_MS);
    this.set('connecting', null);
    return call;
  }

  private async offer(call: Call): Promise<void> {
    try {
      await call.peer.setLocalDescription(await call.peer.createOffer());
      if (this.call === call) this.options.sendSignal({ kind: 'offer', sdp: call.peer.localDescription?.sdp ?? '' });
    } catch {
      if (this.call === call) this.set('failed', 'The call could not be set up.');
    }
  }

  /** Whether the other person's audio has arrived since the last look. */
  private async measure(call: Call): Promise<void> {
    let bytes = 0;
    try {
      for (const report of (await call.peer.getStats()).values()) {
        if (report.type === 'inbound-rtp' && report.kind === 'audio') bytes += report.bytesReceived ?? 0;
      }
    } catch {
      return;
    }
    if (this.call !== call) return;
    const receiving = bytes > this.received;
    this.received = bytes;
    if (receiving !== this.receiving) {
      this.receiving = receiving;
      this.options.changed(this.status);
    }
  }

  private hangUp(): void {
    if (this.statsTimer !== null) clearInterval(this.statsTimer);
    this.statsTimer = null;
    this.call?.peer.close();
    this.call = null;
    this.speaker.srcObject = null;
    this.receiving = false;
  }

  private end(problem: string | null, tell = true): void {
    this.hangUp();
    for (const track of this.microphone?.getTracks() ?? []) track.stop();
    const was = this.microphone !== null;
    this.microphone = null;
    if (was && tell && this.announced) this.options.sendReady(false);
    this.announced = false;
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
    case 'connected': return 'Voice connected';
    case 'failed': return `Voice failed · ${status.problem ?? 'The call could not connect.'}`;
  }
}
