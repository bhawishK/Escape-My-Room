export type Role = 'mobile_master' | 'vr_solver';
export type TrackingSource = 'webxr' | 'simulator';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost' | 'emulated' | 'simulated';
export type ReferenceSpace = 'local' | 'local-floor';
export interface Position { x: number; y: number; z: number }

export interface SessionState {
  session_id: string;
  revision: number;
  participants: Array<{
    participant_id: string;
    role: Role;
    tracking_source: TrackingSource;
    connected: boolean;
    connection_generation: number;
  }>;
  marker: {
    participant_id: string | null;
    source: TrackingSource | null;
    tracking_status: TrackingStatus;
    reference_space: ReferenceSpace | null;
    position: Position | null;
  };
}

export interface PoseInput {
  tracking_status: TrackingStatus;
  reference_space: ReferenceSpace | null;
  position: Position | null;
}

export type ServerEvent =
  | { type: 'welcome'; participant_id: string; connection_generation: number; state: SessionState }
  | { type: 'state'; state: SessionState }
  | { type: 'error'; code: string; message: string };
