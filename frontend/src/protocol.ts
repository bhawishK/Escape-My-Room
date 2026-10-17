export type Role = 'mobile_master' | 'vr_solver';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost' | 'emulated';
export type ReferenceSpace = 'local' | 'local-floor';
export interface Position { x: number; y: number; z: number }

export interface RoomEntity {
  id: string;
  node: string;
  kind: 'static' | 'movable';
  selectable: boolean;
  color: string;
  position: Position;
  size: { width: number; height: number; depth: number };
}

export interface RoomState {
  available: boolean;
  room_version: number | null;
  units: string | null;
  asset_url: string | null;
  error: string | null;
  entities: RoomEntity[];
  loaded_by: { mobile_master: number | null; vr_solver: number | null };
}

export interface AlignmentState {
  status: 'not_aligned' | 'aligned';
  yaw: number;
  origin: Position;
}

export interface SessionState {
  revision: number;
  mobile_connected: boolean;
  vr_connected: boolean;
  marker: {
    tracking_status: TrackingStatus;
    reference_space: ReferenceSpace | null;
    position: Position | null;
  };
  alignment: { mobile_master: AlignmentState; vr_solver: AlignmentState };
  room: RoomState;
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
