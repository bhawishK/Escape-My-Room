export type Role = 'mobile_master' | 'vr_solver';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost' | 'emulated';
export type ReferenceSpace = 'local' | 'local-floor';
export interface Position { x: number; y: number; z: number }

export interface SessionState {
  revision: number;
  mobile_connected: boolean;
  vr_connected: boolean;
  marker: {
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
  | { type: 'welcome'; state: SessionState }
  | { type: 'state'; state: SessionState }
  | { type: 'error'; code: string; message: string };
