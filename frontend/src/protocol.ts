export type Role = 'mobile_master' | 'vr_solver';
export type TrackingStatus = 'inactive' | 'tracked' | 'lost';
/** Phone positions arrive in room coordinates. */
export type ReferenceSpace = 'room';
export interface Position { x: number; y: number; z: number }

/** An object the room knows the place of, on the floor, with the other names Qwen gave it (#120). */
export interface RoomLandmark {
  id: string;
  label: string;
  aliases: string[];
  x: number;
  z: number;
}
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
  /** A Gaussian splat drawn as the room's look; static entities are then not drawn. */
  splat_url: string | null;
  /** A lighter copy of the splat for phones, or null when they draw the full one (#109). */
  splat_phone_url: string | null;
  /** Objects the phone can calibrate by standing at two of them (#120); none without a map. */
  landmarks: RoomLandmark[];
  /** The room seen from above, and the floor area it shows; null without a map image (#124). */
  map: { url: string; min_x: number; max_x: number; min_z: number; max_z: number } | null;
  /** Where the splat sits: scaled, rotated, then moved; it levels a splat trained tilted. */
  splat_placement: { position: Position; rotation: Rotation; scale: number } | null;
  loaded_by: { mobile_master: number | null; vr_solver: number | null };
}

export interface AlignmentState {
  status: 'not_aligned' | 'aligned';
  yaw: number;
  origin: Position;
}

export type PresenceStatus = 'inactive' | 'tracked' | 'lost' | 'stale';

/** One person in the room. Heading 0 faces the desk; positive turns left. */
export interface PresenceState {
  tracking_status: PresenceStatus;
  position: Position | null;
  heading: number | null;
}

export const NO_PRESENCE: PresenceState = {
  tracking_status: 'inactive', position: null, heading: null,
};

export interface SessionState {
  revision: number;
  mobile_connected: boolean;
  vr_connected: boolean;
  marker: {
    tracking_status: TrackingStatus;
    reference_space: ReferenceSpace | null;
    position: Position | null;
    heading: number | null;
    pitch: number | null;
  };
  participants: { mobile_master: PresenceState; vr_solver: PresenceState };
  alignment: { mobile_master: AlignmentState; vr_solver: AlignmentState };
  /** How Python is delivering: an induced delay for testing slow networks, 0 normally. */
  delivery: { simulated_delay_ms: number };
  /** The hold in progress, if any: the held object follows its owner's phone. */
  manipulation: { id: number; entity: string; owner: Role; sequence: number | null } | null;
  /** Who has a microphone open for the voice call (#13); `session` counts each time they start. */
  voice: Record<Role, { ready: boolean; session: number }>;
  room: RoomState;
}

/** One step of setting up the voice call, as this device sends it. */
export type VoiceSignalInput =
  | { kind: 'offer' | 'answer'; sdp: string }
  | { kind: 'candidate'; candidate: RTCIceCandidateInit | null };

/** A set-up message from the other person, with their voice session, as Python passes it on. */
export interface VoiceSignal {
  from: Role;
  session: number;
  kind: 'offer' | 'answer' | 'candidate';
  sdp: string | null;
  candidate: RTCIceCandidateInit | null;
}

export interface PoseInput {
  tracking_status: TrackingStatus;
  reference_space: ReferenceSpace | null;
  position: Position | null;
  /** Which way the phone faces in radians: 0 toward the desk (-Z), positive turning left. */
  heading: number | null;
  /** How far the screen centre looks above level in radians; negative looks down. */
  pitch: number | null;
}

/** Python's private answer to the phone's selection request: the selection now, and any refusal. */
export interface SelectionResult {
  id: string | null;
  rejected: { code: string; message: string } | null;
}

export interface PresenceInput {
  tracking_status: 'inactive' | 'tracked' | 'lost';
  position: Position | null;
  heading: number | null;
}

export type ServerEvent =
  | { type: 'welcome'; state: SessionState }
  | ({ type: 'selection' } & SelectionResult)
  | { type: 'state'; state: SessionState }
  | ({ type: 'voice_signal' } & VoiceSignal)
  | { type: 'error'; code: string; message: string };
