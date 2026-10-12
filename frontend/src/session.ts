import type { PoseInput, Role, ServerEvent, SessionState, TrackingSource } from './protocol';

interface SessionEvents {
  state: (state: SessionState) => void;
  connection: (connected: boolean) => void;
  error: (message: string) => void;
}

interface ParticipantGrant { participant_id: string; connection_token: string }

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof problem?.detail === 'string' ? problem.detail : `Request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export class SessionClient {
  private socket: WebSocket | null = null;
  private generation = 0;
  private sequence = 0;

  constructor(private readonly events: SessionEvents) {}

  async create(): Promise<string> {
    return (await post<{ session_id: string }>('/api/sessions')).session_id;
  }

  async join(sessionId: string, role: Role, source: TrackingSource): Promise<void> {
    const identity = await post<ParticipantGrant>(
      `/api/sessions/${encodeURIComponent(sessionId)}/participants`,
      { role, tracking_source: source },
    );
    try {
      await this.openSocket(sessionId, identity);
    } catch (error) {
      this.socket?.close();
      this.socket = null;
      // HTTP can succeed even when WSS is blocked. Release this grant before allowing a retry.
      try {
        await post<void>(
          `/api/sessions/${encodeURIComponent(sessionId)}/participants/${identity.participant_id}/release`,
          { connection_token: identity.connection_token },
        );
      } catch {
        throw new Error('Connection failed and its role could not be released. Restore network access and ask the master to create a new session.');
      }
      throw error;
    }
  }

  private async openSocket(sessionId: string, identity: ParticipantGrant): Promise<void> {
    const url = new URL(`/api/sessions/${encodeURIComponent(sessionId)}/ws`, location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('participant_id', identity.participant_id);
    // Credentials travel in the handshake, not a URL that access logs expose.
    const socket = new WebSocket(url, ['escape-my-room', identity.connection_token]);
    this.socket = socket;
    this.sequence = 0;
    await new Promise<void>((resolve, reject) => {
      let welcomed = false;
      const timeout = window.setTimeout(() => {
        socket.close();
        reject(new Error('Connection timed out. Check the server URL, certificate trust, and WSS access.'));
      }, 8000);
      socket.addEventListener('message', event => {
        if (this.socket !== socket) return;
        try {
          const message = JSON.parse(String(event.data)) as ServerEvent;
          if (message.type === 'welcome') {
            this.generation = message.connection_generation;
            welcomed = true;
            clearTimeout(timeout);
            this.events.state(message.state);
            this.events.connection(true);
            resolve();
          } else if (message.type === 'state') {
            this.events.state(message.state);
          } else if (message.type === 'error') {
            this.events.error(`${message.code}: ${message.message}`);
          }
        } catch {
          this.events.error('The server sent an unreadable diagnostic message. Reload and rejoin.');
        }
      });
      socket.addEventListener('close', () => {
        clearTimeout(timeout);
        if (this.socket === socket) {
          this.socket = null;
          this.events.connection(false);
        }
        if (!welcomed) reject(new Error('Connection failed. Check the server URL, certificate trust, and WSS access.'));
      });
      socket.addEventListener('error', () => {
        if (this.socket === socket) this.events.error('Network error. Check that both devices can reach the same HTTPS server.');
      });
    });
  }

  sendPose(pose: PoseInput): void {
    if (this.socket?.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > 16384) return;
    this.socket.send(JSON.stringify({
      type: 'pose', connection_generation: this.generation, sequence: ++this.sequence, ...pose,
    }));
  }

  leave(): void {
    this.socket?.close();
    this.socket = null;
    this.events.connection(false);
  }
}
