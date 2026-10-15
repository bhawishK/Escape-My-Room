export type Role = 'mobile_master' | 'vr_solver';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost' | 'emulated';
export type ReferenceSpace = 'local' | 'local-floor';
export interface Position { x: number; y: number; z: number }
/** A unit quaternion in (x, y, z, w) order. */
export interface Rotation { x: number; y: number; z: number; w: number }

/** Room frame: meters, right-handed, +Y up; position and rotation place the bottom-face center. */
export interface RoomEntity {
  id: string;
  label: string;
  asset_url: string;
  node: string;
  kind: 'static' | 'movable';
  selectable: boolean;
  position: Position;
  rotation: Rotation;
  size: { width: number; height: number; depth: number };
}

export interface RoomState {
  available: boolean;
  room_version: number | null;
  units: 'meters' | null;
  frame: 'y_up_right_handed' | null;
  quaternion_order: 'xyzw' | null;
  error: string | null;
  entities: RoomEntity[];
  loaded_by: { mobile_master: number | null; vr_solver: number | null };
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
