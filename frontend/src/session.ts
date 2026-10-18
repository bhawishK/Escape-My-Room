import type { CalibrationInput } from './alignment';
import type { PoseInput, Role, ServerEvent, SessionState } from './protocol';

interface SessionEvents {
  state: (state: SessionState) => void;
  connection: (connected: boolean) => void;
  error: (message: string) => void;
}

export class SessionClient {
  private socket: WebSocket | null = null;
  private sequence = 0;

  constructor(private readonly events: SessionEvents) {}

  async join(role: Role): Promise<void> {
    this.leave();
    const url = new URL('/api/ws', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('role', role);
    const socket = new WebSocket(url);
    this.socket = socket;
    this.sequence = 0;
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

  sendPose(pose: PoseInput): void {
    if (this.socket?.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > 16384) return;
    this.socket.send(JSON.stringify({ type: 'pose', sequence: ++this.sequence, ...pose }));
  }

  sendCalibration(input: CalibrationInput): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'calibrate', ...input }));
  }

  sendRoomLoaded(roomVersion: number): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ type: 'room_loaded', room_version: roomVersion }));
  }

  leave(): void {
    this.socket?.close();
    this.socket = null;
    this.events.connection(false);
  }
}
