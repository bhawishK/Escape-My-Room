export type Role = 'mobile_master' | 'vr_solver';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost';
/** Phone positions are measured against room markers, so they arrive in room coordinates. */
export type ReferenceSpace = 'room';
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

/**
 * A printed AprilTag (36h11) fixed in the room. Position is the black square's center; in the tag's
 * frame +X is the printed tag's right, +Y its top and +Z out of its face. Size is the square's edge.
 */
export interface TrackingMarker {
  id: number;
  label: string;
  size: number;
  position: Position;
  rotation: Rotation;
}

/** Pinhole intrinsics in pixels of a `width` x `height` image, with OpenCV k1, k2, p1, p2, k3. */
export interface CameraIntrinsics {
  width: number;
  height: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  distortion: number[];
}

export interface CameraCalibration extends CameraIntrinsics {
  rms_px: number;
  views: number;
  user_agent: string;
  recorded_at: string;
}

export interface RoomState {
  available: boolean;
  room_version: number | null;
  units: 'meters' | null;
  frame: 'y_up_right_handed' | null;
  quaternion_order: 'xyzw' | null;
  error: string | null;
  entities: RoomEntity[];
  markers: TrackingMarker[];
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
