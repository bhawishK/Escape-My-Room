import type { CalibrationInput } from './alignment';
import type { PoseInput, Role, SelectionResult, ServerEvent, SessionState } from './protocol';

interface SessionEvents {
  state: (state: SessionState) => void;
  connection: (connected: boolean) => void;
  selection: (result: SelectionResult) => void;
  error: (message: string) => void;
  poseSent?: (sequence: number) => void;
  poseReplaced?: () => void;
}

/** Unsent bytes above which the connection counts as congested, and how often to look again. */
const CONGESTED_BYTES = 16384;
const DRAIN_CHECK_MS = 30;

export class SessionClient {
  private socket: WebSocket | null = null;
  private sequence = 0;
  /** The newest pose not yet sent because the connection was congested. */
  private waitingPose: PoseInput | null = null;
  private drainTimer: number | null = null;

  constructor(private readonly events: SessionEvents) {}

  async join(role: Role): Promise<void> {
    this.leave();
    const url = new URL('/api/ws', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('role', role);
    const socket = new WebSocket(url);
    this.socket = socket;
    this.sequence = 0;
    this.stopWaitingPose();
    try {
      await new Promise<void>((resolve, reject) => {
        let welcomed = false;
        const timeout = window.setTimeout(() => {
          socket.close();
          reject(new Error('Connection timed out. Check the HTTPS link and try connecting again.'));
        }, 8000);
        socket.addEventListener('message', event => {
          if (this.socket !== socket) return;
          try {
            const message = JSON.parse(String(event.data)) as ServerEvent;
            if (message.type === 'welcome') {
              welcomed = true;
              clearTimeout(timeout);
              this.events.state(message.state);
              this.events.connection(true);
              resolve();
            } else if (message.type === 'state') {
              this.events.state(message.state);
            } else if (message.type === 'selection') {
              this.events.selection({ id: message.id, rejected: message.rejected });
            } else if (message.type === 'error') {
              this.events.error(message.message);
            }
          } catch {
            this.events.error('The server sent an unreadable message. Disconnect and connect again.');
          }
        });
        socket.addEventListener('close', event => {
          clearTimeout(timeout);
          if (this.socket === socket) {
            this.socket = null;
            this.events.connection(false);
            if (welcomed && event.reason) this.events.error(event.reason);
          }
          if (!welcomed) reject(new Error('Connection failed. Check the HTTPS link and try connecting again.'));
        });
        socket.addEventListener('error', () => {
          if (this.socket === socket) this.events.error('Network error. Check that this device can reach the shared URL.');
        });
      });
    } catch (error) {
      socket.close();
      if (this.socket === socket) {
        this.socket = null;
        this.events.connection(false);
      }
      throw error;
    }
  }

  /**
   * Sends the phone's pose. While the connection is congested only the newest pose waits, and it
   * goes as soon as the connection drains, so a long hold never builds a queue of old movement.
   */
  sendPose(pose: PoseInput): void {
    if (this.waitingPose) this.events.poseReplaced?.();
    this.waitingPose = pose;
    this.flushPose();
  }

  private stopWaitingPose(): void {
    this.waitingPose = null;
    if (this.drainTimer !== null) clearTimeout(this.drainTimer);
    this.drainTimer = null;
  }

  private flushPose(force = false): void {
    const pose = this.waitingPose;
    if (!pose || this.socket?.readyState !== WebSocket.OPEN) return;
    if (!force && this.socket.bufferedAmount > CONGESTED_BYTES) {
      this.drainTimer ??= window.setTimeout(() => {
        this.drainTimer = null;
        this.flushPose();
      }, DRAIN_CHECK_MS);
      return;
    }
    this.waitingPose = null;
    this.socket.send(JSON.stringify({ type: 'pose', sequence: ++this.sequence, ...pose }));
    this.events.poseSent?.(this.sequence);
  }

  sendCalibration(input: CalibrationInput): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'calibrate', ...input }));
  }

  /** Asks Python to select a room object for this phone, or to deselect with null. */
  sendSelection(roomVersion: number, id: string | null): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'select', room_version: roomVersion, id }));
  }

  /** Asks Python to start holding the selected object, so walking carries it. */
  sendAcquire(roomVersion: number, id: string): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'acquire', room_version: roomVersion, id }));
  }

  /** Lets go of a hold; the object stays where it is. */
  /** Lets go of a hold; `interrupted` when the person did not choose to, such as on the page hiding. */
  sendRelease(manipulationId: number, interrupted = false): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    // The last aim goes first even on a congested connection, so the release commits it.
    this.flushPose(true);
    this.socket.send(JSON.stringify({
      type: 'release', manipulation_id: manipulationId, reason: interrupted ? 'interrupted' : 'placed',
    }));
  }

  sendRoomLoaded(roomVersion: number): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'room_loaded', room_version: roomVersion }));
  }

  leave(): void {
    this.socket?.close();
    this.socket = null;
    this.stopWaitingPose();
    this.events.connection(false);
  }
}
