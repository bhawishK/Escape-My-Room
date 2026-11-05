/**
 * What the headset's hands and controllers do in one XR frame (#156), read from the session IWSDK
 * started and given as plain values in the `local` reference space.
 */
import { rayForward } from '../grab';
import type { Position, Rotation } from '../protocol';
import { handPose, type HandJoints, type HandPose } from './gestures';

export interface Pose { position: Position; orientation: Rotation }
export interface Ray { origin: Position; direction: Position }

/** One controller or one tracked hand. */
export interface InputSample {
  source: XRInputSource;
  kind: 'controller' | 'hand';
  /** Holding: the grip squeezed, or the hand pinching. */
  holding: boolean;
  /** A or X, on a controller. */
  confirm: boolean;
  /** Where a held object is carried from: the grip, or the hand's palm. */
  grip: Pose | null;
  /** The pointing ray the system gives: the controller's, or the hand's. */
  ray: Ray | null;
  /** A hand's pose and, while it points, the ray along its index finger. */
  pose: HandPose;
  fingerRay: Ray | null;
}

export interface FrameSample {
  /** The head, or null while its position is lost or only estimated. */
  head: Pose | null;
  tracking: 'tracked' | 'emulated' | 'lost';
  inputs: InputSample[];
}

const JOINTS: XRHandJoint[] = [
  'wrist', 'thumb-tip',
  'index-finger-phalanx-proximal', 'index-finger-tip',
  'middle-finger-phalanx-proximal', 'middle-finger-tip',
  'ring-finger-phalanx-proximal', 'ring-finger-tip',
  'pinky-finger-phalanx-proximal', 'pinky-finger-tip',
];

function poseOf(transform: XRRigidTransform): Pose {
  const p = transform.position;
  const q = transform.orientation;
  return { position: { x: p.x, y: p.y, z: p.z }, orientation: { x: q.x, y: q.y, z: q.z, w: q.w } };
}

function rayOf(frame: XRFrame, space: XRSpace, reference: XRReferenceSpace): Ray | null {
  const pose = frame.getPose(space, reference);
  if (!pose || pose.emulatedPosition) return null;
  const { position, orientation } = poseOf(pose.transform);
  return { origin: position, direction: rayForward(orientation) };
}

/** Where a pointing index finger points: from its knuckle through its tip. */
function fingerRay(joints: HandJoints): Ray | null {
  const knuckle = joints['index-finger-phalanx-proximal'];
  const tip = joints['index-finger-tip'];
  if (!knuckle || !tip) return null;
  return { origin: tip, direction: { x: tip.x - knuckle.x, y: tip.y - knuckle.y, z: tip.z - knuckle.z } };
}

/**
 * Reads the frame. `pinching` holds the hands whose pinch the session has selected: the system's
 * own pinch, which settles a wavering pinch better than a distance here would.
 */
export function readFrame(frame: XRFrame, reference: XRReferenceSpace, pinching: ReadonlySet<XRInputSource>): FrameSample {
  const viewer = frame.getViewerPose(reference);
  const tracking = !viewer ? 'lost' : viewer.emulatedPosition ? 'emulated' : 'tracked';
  const inputs: InputSample[] = [];
  for (const source of frame.session.inputSources) {
    const grip = source.gripSpace ? frame.getPose(source.gripSpace, reference) : undefined;
    const sample: InputSample = {
      source, kind: source.hand ? 'hand' : 'controller',
      holding: false, confirm: false,
      grip: grip && !grip.emulatedPosition ? poseOf(grip.transform) : null,
      ray: rayOf(frame, source.targetRaySpace, reference),
      pose: 'none', fingerRay: null,
    };
    if (source.hand) {
      const joints: HandJoints = {};
      for (const name of JOINTS) {
        const space = source.hand.get(name);
        const joint = space && frame.getJointPose?.(space, reference);
        if (joint) joints[name] = poseOf(joint.transform).position;
      }
      sample.pose = handPose(joints);
      sample.holding = pinching.has(source);
      if (sample.pose === 'point') sample.fingerRay = fingerRay(joints);
    } else {
      const buttons = source.gamepad?.buttons;
      // On a Quest controller the grip is button 1, and A or X is button 4.
      sample.holding = Boolean(buttons?.[1]?.pressed);
      sample.confirm = Boolean(buttons?.[4]?.pressed);
    }
    inputs.push(sample);
  }
  return { head: tracking === 'tracked' && viewer ? poseOf(viewer.transform) : null, tracking, inputs };
}
