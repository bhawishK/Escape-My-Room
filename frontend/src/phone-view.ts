/**
 * The phone's full-screen room view: where it looks from and which way it faces. Turning the phone
 * turns the view through the phone's orientation sensor; walking steps move it (see step-walk.ts).
 */
import * as THREE from 'three';
import { STANDING_EYE_HEIGHT } from './alignment';
import type { Position, Rotation } from './protocol';

/** Where a view is in the room and which way it faces, as a Three.js camera would. */
export interface RoomPose {
  position: Position;
  /** Unit quaternion (x, y, z, w); the camera looks along its local -Z with +Y up. */
  orientation: Rotation;
}

/** The view starts back from the desk at standing eye height, so the room fits. */
export const START_EYE: Position = { x: 0, y: STANDING_EYE_HEIGHT, z: 1.6 };
// Facing the desk and tilted 20° down toward it, as a phone is held when looking at it.
const FACING_DESK: Rotation = { x: Math.sin(-20 * Math.PI / 360), y: 0, z: 0, w: Math.cos(-20 * Math.PI / 360) };

const UP = new THREE.Vector3(0, 1, 0);
const SCREEN_NORMAL = new THREE.Vector3(0, 0, 1);
// Turns the device frame so the camera looks out of the back of the phone, not out of its top edge.
const BACK_CAMERA = new THREE.Quaternion(-Math.SQRT1_2, 0, 0, Math.SQRT1_2);

/**
 * The camera orientation for a `deviceorientation` reading, in degrees, with the screen turned by
 * `screenAngle` degrees. Its heading is relative to wherever the sensor's alpha is zero.
 */
export function cameraFromDevice(alpha: number, beta: number, gamma: number, screenAngle: number): THREE.Quaternion {
  const toRadians = Math.PI / 180;
  const euler = new THREE.Euler(beta * toRadians, alpha * toRadians, -gamma * toRadians, 'YXZ');
  return new THREE.Quaternion().setFromEuler(euler)
    .multiply(BACK_CAMERA)
    .multiply(new THREE.Quaternion().setFromAxisAngle(SCREEN_NORMAL, -screenAngle * toRadians));
}

/** The heading of a camera orientation: 0 when it faces the desk (-Z), positive turning left. */
export function headingOf(orientation: THREE.Quaternion | Rotation): number {
  const q = orientation instanceof THREE.Quaternion ? orientation :
    new THREE.Quaternion(orientation.x, orientation.y, orientation.z, orientation.w);
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
  return Math.atan2(-forward.x, -forward.z);
}

/** How far a camera orientation looks above level, in radians: negative when it looks down. */
export function pitchOf(orientation: Rotation): number {
  const q = new THREE.Quaternion(orientation.x, orientation.y, orientation.z, orientation.w);
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
  return Math.asin(Math.max(-1, Math.min(1, forward.y)));
}

interface Reading { alpha: number; beta: number; gamma: number }

/** Turns the view as the phone turns, using the browser's `deviceorientation` events. */
export class PhoneLook {
  private reading: Reading | null = null;
  private heading = 0;
  private anchored = false;
  private listening = false;
  private readonly listener = (event: DeviceOrientationEvent) => {
    if (event.alpha === null || event.beta === null || event.gamma === null) return;
    this.reading = { alpha: event.alpha, beta: event.beta, gamma: event.gamma };
  };

  get active(): boolean { return this.listening; }

  /** Call from a button press: iPhone asks for motion permission and only allows it during a gesture. */
  async start(): Promise<void> {
    const request = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> })
      .requestPermission;
    if (typeof request === 'function') {
      const answer = await request.call(DeviceOrientationEvent).catch(() => 'denied');
      if (answer !== 'granted') {
        throw new Error('Motion permission was denied. Allow motion access for this site, then try again.');
      }
    }
    this.reading = null;
    this.anchored = false;
    window.addEventListener('deviceorientation', this.listener);
    this.listening = true;
  }

  stop(): void {
    window.removeEventListener('deviceorientation', this.listener);
    this.listening = false;
    this.reading = null;
  }

  /** The view's room orientation, or null without a reading. The first reading faces the desk. */
  orientation(): THREE.Quaternion | null {
    const raw = this.raw();
    if (!raw) return null;
    if (!this.anchored) {
      this.heading = -headingOf(raw);
      this.anchored = true;
    }
    return new THREE.Quaternion().setFromAxisAngle(UP, this.heading).multiply(raw);
  }

  private raw(): THREE.Quaternion | null {
    if (!this.reading) return null;
    const angle = screen.orientation?.angle ?? 0;
    return cameraFromDevice(this.reading.alpha, this.reading.beta, this.reading.gamma, angle);
  }
}

/** The pose the room view shows: the eye at `position`, turned by the phone's sensor when it is on. */
export function phoneViewpoint(look: PhoneLook, position: Position = START_EYE): RoomPose {
  const turned = look.orientation();
  const orientation = turned ? { x: turned.x, y: turned.y, z: turned.z, w: turned.w } : FACING_DESK;
  return { position, orientation };
}
