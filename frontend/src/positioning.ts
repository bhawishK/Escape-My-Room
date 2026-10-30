/**
 * Visual positioning (#133): the phone sends a camera frame to Python about once a second, Python
 * answers where the camera stood in the room, and these fixes line 8th Wall's world up with the
 * room. 8th Wall still gives smooth motion between fixes; a fix after a loss or restart puts the
 * person back in place without tapping on the map.
 *
 * - `FrameGrabber` copies 8th Wall's camera image off the GPU only when a frame is wanted, as its
 *   own `CameraPixelArray` module does every frame, and pairs it with 8th Wall's pose and lens.
 * - `Positioner` encodes it as a JPEG and posts it to `/api/localize`, one at a time.
 * - `FixFusion` fits the turn, scale and shift from 8th Wall's world to the room over the recent
 *   fixes, rejects a fix that disagrees, and blends each change in.
 */
import * as THREE from 'three';
import type { RoomPose } from './phone-view';
import type { Position, Rotation } from './protocol';

/** One camera frame to locate, and 8th Wall's own pose when it was taken. */
export interface CameraFrame {
  /** RGBA, top row first. */
  pixels: Uint8Array;
  width: number;
  height: number;
  /** The lens's focal length in this frame's pixels; the centre is the frame's middle. */
  focal: number;
  /** 8th Wall's pose of this frame, before any lining up with the room. */
  engine: RoomPose;
  /** Whether 8th Wall was tracking normally, so its pose can be paired with the fix. */
  tracked: boolean;
  at: number;
}

/** Where Python located a frame, in the room. */
export interface LocatedFrame {
  located: boolean;
  room_version: number | null;
  position: Position | null;
  orientation: Rotation | null;
  inliers: number;
  matches: number;
  reason: string | null;
  seconds: Record<string, number>;
}

/** The turn about the vertical, 0 facing the desk and positive to the left. */
export function yawOf(orientation: Rotation): number {
  const q = new THREE.Quaternion(orientation.x, orientation.y, orientation.z, orientation.w);
  return new THREE.Euler().setFromQuaternion(q, 'YXZ').y;
}

/** An angle brought into -pi to pi. */
function wrap(angle: number): number {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

// The long side of a frame sent to Python: the map's frames were described at this size.
const FRAME_SIDE = 640;

interface TextureRenderer {
  render(args: { renderTexture: WebGLTexture; viewport: { offsetX: number; offsetY: number; width: number; height: number } }): unknown;
  framebuffer(): WebGLFramebuffer;
  destroy(): void;
}

/** The parts of 8th Wall's `XR8.GlTextureRenderer` the grabber uses. */
export interface TextureRenderers {
  create(options: { GLctx: WebGL2RenderingContext | WebGLRenderingContext; toTexture: { width: number; height: number }; flipY: boolean }): TextureRenderer;
}

/** What 8th Wall hands its camera modules for each frame on the GPU. */
export interface GpuFrameStart {
  computeTexture?: WebGLTexture;
  computeCtx?: WebGL2RenderingContext | WebGLRenderingContext;
  textureWidth: number;
  textureHeight: number;
}

/** 8th Wall's tracking result for a frame: its pose, status and the canvas's projection. */
export interface EngineReality {
  position: Position;
  rotation: Rotation;
  trackingStatus?: string;
  /** The camera's projection matrix for the canvas, column-major. */
  intrinsics?: number[];
}

/**
 * The focal length in pixels of a `width` x `height` camera frame, from 8th Wall's projection for
 * its canvas. The frame covers the canvas, so the canvas sees the frame's full extent on one side
 * and a crop on the other: the smaller of the two focal lengths is the frame's.
 */
export function focalLength(intrinsics: readonly number[], width: number, height: number): number | null {
  const [p00, p11] = [intrinsics[0], intrinsics[5]];
  if (!(p00 > 0) || !(p11 > 0)) return null;
  return Math.min(p00 * width / 2, p11 * height / 2);
}

/**
 * Copies a camera frame off the GPU when one is wanted. The frame is drawn into a small texture
 * on one frame and read back on the next, so the read does not wait on that frame's drawing.
 */
export class FrameGrabber {
  private renderer: TextureRenderer | null = null;
  private size = { width: 0, height: 0 };
  private context: WebGL2RenderingContext | WebGLRenderingContext | null = null;
  private wanted = false;
  /** A frame drawn and waiting to be read, with 8th Wall's result for it once it has come. */
  private drawn: { width: number; height: number; reality: EngineReality | null } | null = null;

  constructor(
    private readonly renderers: TextureRenderers,
    private readonly take: (frame: CameraFrame) => void,
  ) {}

  /** Grab the next frame. */
  request(): void { this.wanted = true; }

  /** A frame is wanted, or drawn and not read yet. */
  get busy(): boolean { return this.wanted || this.drawn !== null; }

  /** 8th Wall's GPU step for a frame: reads the last frame drawn, then draws this one if wanted. */
  gpu(start: GpuFrameStart): void {
    this.read();
    const { computeTexture, computeCtx, textureWidth, textureHeight } = start;
    if (!this.wanted || !computeTexture || !computeCtx || !(textureWidth > 0) || !(textureHeight > 0)) return;
    const shrink = FRAME_SIDE / Math.max(textureWidth, textureHeight);
    const width = Math.max(1, Math.round(textureWidth * Math.min(1, shrink)));
    const height = Math.max(1, Math.round(textureHeight * Math.min(1, shrink)));
    if (!this.renderer || this.context !== computeCtx || width !== this.size.width || height !== this.size.height) {
      this.renderer?.destroy();
      this.renderer = this.renderers.create({ GLctx: computeCtx, toTexture: { width, height }, flipY: true });
      this.context = computeCtx;
      this.size = { width, height };
    }
    this.renderer.render({ renderTexture: computeTexture, viewport: { offsetX: 0, offsetY: 0, width, height } });
    this.wanted = false;
    this.drawn = { width, height, reality: null };
  }

  /** 8th Wall's tracking result for the frame just drawn. */
  cpu(reality: EngineReality): void {
    if (this.drawn && !this.drawn.reality) this.drawn.reality = reality;
  }

  stop(): void {
    this.renderer?.destroy();
    this.renderer = null;
    this.context = null;
    this.drawn = null;
    this.wanted = false;
  }

  private read(): void {
    const drawn = this.drawn;
    const { renderer, context: gl } = this;
    this.drawn = null;
    if (!drawn?.reality || !renderer || !gl) return;
    const focal = drawn.reality.intrinsics ? focalLength(drawn.reality.intrinsics, drawn.width, drawn.height) : null;
    if (focal === null) return;
    const pixels = new Uint8Array(drawn.width * drawn.height * 4);
    const bound = gl.getParameter(gl.FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
    gl.bindFramebuffer(gl.FRAMEBUFFER, renderer.framebuffer());
    gl.readPixels(0, 0, drawn.width, drawn.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    gl.bindFramebuffer(gl.FRAMEBUFFER, bound);
    const { position: p, rotation: r } = drawn.reality;
    this.take({
      pixels, width: drawn.width, height: drawn.height, focal,
      engine: { position: { x: p.x, y: p.y, z: p.z }, orientation: { x: r.x, y: r.y, z: r.z, w: r.w } },
      tracked: drawn.reality.trackingStatus !== 'LIMITED',
      at: performance.now(),
    });
  }
}

// How often a frame is sent: once a second while tracked, twice while lost, to get back sooner.
const TRACKED_EVERY_MS = 1000;
const LOST_EVERY_MS = 500;
const JPEG_QUALITY = 0.8;

/** Why the server cannot locate frames for the live room; frames are not sent again for it. */
export class PositioningOff extends Error {}

/** Sends frames to Python to locate, one at a time. */
export class Positioner {
  private inFlight = false;
  private lastSent = -Infinity;
  /** Why positioning is off for this room, until the room changes; null while it is on. */
  private off: string | null = null;
  private readonly canvas = document.createElement('canvas');

  constructor(private readonly post: (form: FormData) => Promise<Response> = form => fetch('/api/localize', { method: 'POST', body: form })) {}

  /** Whether a frame should be grabbed now. */
  due(now: number, tracked: boolean): boolean {
    return this.off === null && !this.inFlight && now - this.lastSent >= (tracked ? TRACKED_EVERY_MS : LOST_EVERY_MS);
  }

  /** The room changed: try again, its map may differ. */
  roomChanged(): void { this.off = null; }

  get offReason(): string | null { return this.off; }

  /**
   * Locates `frame`. Throws `PositioningOff` when the server has no map or models for this room,
   * and other errors when the request fails.
   */
  async locate(frame: CameraFrame): Promise<LocatedFrame> {
    this.inFlight = true;
    this.lastSent = frame.at;
    try {
      const form = new FormData();
      form.append('image', await this.jpeg(frame), 'frame.jpg');
      const lens = { fx: frame.focal, fy: frame.focal, cx: frame.width / 2, cy: frame.height / 2 };
      for (const [name, value] of Object.entries({ ...lens, width: frame.width, height: frame.height })) {
        form.append(name, String(value));
      }
      const response = await this.post(form);
      if (response.status === 404 || response.status === 503) {
        const detail = ((await response.json().catch(() => ({}))) as { detail?: string }).detail;
        this.off = detail ?? `positioning unavailable (${response.status})`;
        throw new PositioningOff(this.off);
      }
      if (!response.ok) throw new Error(`positioning failed (${response.status})`);
      return await response.json() as LocatedFrame;
    } finally {
      this.inFlight = false;
    }
  }

  private jpeg(frame: CameraFrame): Promise<Blob> {
    this.canvas.width = frame.width;
    this.canvas.height = frame.height;
    const context = this.canvas.getContext('2d');
    if (!context) return Promise.reject(new Error('no 2D canvas to encode the frame'));
    context.putImageData(new ImageData(new Uint8ClampedArray(frame.pixels), frame.width, frame.height), 0, 0);
    return new Promise((resolve, reject) => this.canvas.toBlob(
      blob => blob ? resolve(blob) : reject(new Error('the frame could not be encoded')), 'image/jpeg', JPEG_QUALITY,
    ));
  }
}

/** 8th Wall's world to the room: turned `yaw` about the vertical, scaled, then shifted. */
export interface EngineToRoom {
  yaw: number;
  scale: number;
  shift: Position;
}

interface Sample { engine: Position; room: Position; turn: number }

// A fix this far from where the current line-up puts the phone, or turned this far, disagrees.
const AGREE_M = 0.5;
const AGREE_RAD = 20 * Math.PI / 180;
// Fixes in a row that disagree with the line-up but agree with each other replace it.
const REPLACE_AFTER = 3;
// The line-up is fitted to this many recent fixes.
const WINDOW = 8;
// Scale is fitted only once the fixes are spread this far apart in 8th Wall's metres.
const SCALE_SPREAD_M = 1;
const MIN_SCALE = 0.5;
const MAX_SCALE = 2;
// A new line-up is blended in over this long, so the view never jumps.
const BLEND_MS = 500;

/** Why a fix was not used, or null when it was. */
export type FixVerdict = { accepted: true; replaced: boolean } | { accepted: false; reason: string };

/**
 * The line-up from 8th Wall's world to the room, from fixes paired with 8th Wall's pose of the same
 * frame. Up is shared, so it is a turn about the vertical, a scale and a shift.
 */
export class FixFusion {
  private samples: Sample[] = [];
  private disagreeing: Sample[] = [];
  private current: EngineToRoom | null = null;
  private previous: EngineToRoom | null = null;
  private changedAt = -Infinity;

  /** The line-up in force, or null before the first fix of this 8th Wall world. */
  get lineUp(): EngineToRoom | null { return this.current; }

  /** 8th Wall started a new world, or the person placed themselves: fixes start again. */
  reset(): void {
    this.samples = [];
    this.disagreeing = [];
    this.current = null;
    this.previous = null;
  }

  /**
   * Takes a fix: `room` is where Python put the camera, `engine` 8th Wall's pose of the same frame.
   * `fallbackScale` is used until the fixes are spread enough to measure the scale.
   */
  add(engine: RoomPose, room: RoomPose, fallbackScale: number, now = performance.now()): FixVerdict {
    const sample = { engine: { ...engine.position }, room: { ...room.position }, turn: wrap(yawOf(room.orientation) - yawOf(engine.orientation)) };
    if (this.current) {
      const off = this.disagreement(this.current, sample);
      if (off) {
        this.disagreeing.push(sample);
        if (this.disagreeing.length > REPLACE_AFTER) this.disagreeing.shift();
        const together = this.disagreeing.length === REPLACE_AFTER && this.agreeAmongThemselves(this.disagreeing, fallbackScale);
        if (!together) return { accepted: false, reason: off };
        this.samples = this.disagreeing;
        this.disagreeing = [];
        this.refit(fallbackScale, now);
        return { accepted: true, replaced: true };
      }
    }
    this.disagreeing = [];
    this.samples.push(sample);
    if (this.samples.length > WINDOW) this.samples.shift();
    this.refit(fallbackScale, now);
    return { accepted: true, replaced: false };
  }

  /** 8th Wall's pose `engine` in the room, blending from the last line-up after a change. */
  toRoom(engine: RoomPose, now = performance.now()): RoomPose | null {
    if (!this.current) return null;
    const target = apply(this.current, engine);
    const blend = Math.min(1, (now - this.changedAt) / BLEND_MS);
    if (!this.previous || blend >= 1) return target;
    const from = apply(this.previous, engine);
    const p = (a: number, b: number) => a + (b - a) * blend;
    const orientation = new THREE.Quaternion(from.orientation.x, from.orientation.y, from.orientation.z, from.orientation.w)
      .slerp(new THREE.Quaternion(target.orientation.x, target.orientation.y, target.orientation.z, target.orientation.w), blend);
    return {
      position: { x: p(from.position.x, target.position.x), y: p(from.position.y, target.position.y), z: p(from.position.z, target.position.z) },
      orientation: { x: orientation.x, y: orientation.y, z: orientation.z, w: orientation.w },
    };
  }

  private refit(fallbackScale: number, now: number): void {
    this.previous = this.current ? this.toRoomLineUp(now) : null;
    this.current = fit(this.samples, fallbackScale);
    this.changedAt = now;
  }

  /** The line-up as seen now, part way through a blend, to blend on from. */
  private toRoomLineUp(now: number): EngineToRoom | null {
    const blend = Math.min(1, (now - this.changedAt) / BLEND_MS);
    if (!this.previous || !this.current || blend >= 1) return this.current;
    const p = (a: number, b: number) => a + (b - a) * blend;
    return {
      yaw: this.previous.yaw + wrap(this.current.yaw - this.previous.yaw) * blend,
      scale: p(this.previous.scale, this.current.scale),
      shift: {
        x: p(this.previous.shift.x, this.current.shift.x),
        y: p(this.previous.shift.y, this.current.shift.y),
        z: p(this.previous.shift.z, this.current.shift.z),
      },
    };
  }

  private disagreement(lineUp: EngineToRoom, sample: Sample): string | null {
    const at = applyPosition(lineUp, sample.engine);
    const away = Math.hypot(at.x - sample.room.x, at.y - sample.room.y, at.z - sample.room.z);
    const turned = Math.abs(wrap(sample.turn - lineUp.yaw));
    if (away > AGREE_M) return `${away.toFixed(2)} m from where tracking has the phone`;
    if (turned > AGREE_RAD) return `turned ${(turned * 180 / Math.PI).toFixed(0)}° from how tracking has the phone`;
    return null;
  }

  private agreeAmongThemselves(samples: Sample[], fallbackScale: number): boolean {
    const lineUp = fit(samples, fallbackScale);
    return samples.every(sample => this.disagreement(lineUp, sample) === null);
  }
}

/** The line-up that best fits `samples`: the mean turn, a scale once they spread, the mean shift. */
function fit(samples: Sample[], fallbackScale: number): EngineToRoom {
  const yaw = Math.atan2(
    samples.reduce((sum, s) => sum + Math.sin(s.turn), 0),
    samples.reduce((sum, s) => sum + Math.cos(s.turn), 0),
  );
  const mean = (points: Position[]) => ({
    x: points.reduce((sum, p) => sum + p.x, 0) / points.length,
    y: points.reduce((sum, p) => sum + p.y, 0) / points.length,
    z: points.reduce((sum, p) => sum + p.z, 0) / points.length,
  });
  const engineMean = mean(samples.map(s => s.engine));
  const roomMean = mean(samples.map(s => s.room));
  // Across the floor only: 8th Wall's heights wander more than its walking.
  const [cos, sin] = [Math.cos(yaw), Math.sin(yaw)];
  let along = 0;
  let squared = 0;
  let spread = 0;
  for (const s of samples) {
    const ex = s.engine.x - engineMean.x;
    const ez = s.engine.z - engineMean.z;
    // The turn about +y, as three.js turns: x' = cos x + sin z, z' = -sin x + cos z.
    const tx = cos * ex + sin * ez;
    const tz = -sin * ex + cos * ez;
    along += tx * (s.room.x - roomMean.x) + tz * (s.room.z - roomMean.z);
    squared += ex * ex + ez * ez;
    spread = Math.max(spread, Math.hypot(ex, ez));
  }
  const measured = squared > 0 ? along / squared : fallbackScale;
  const scale = spread * 2 >= SCALE_SPREAD_M ? Math.min(MAX_SCALE, Math.max(MIN_SCALE, measured)) : fallbackScale;
  const lineUp = { yaw, scale, shift: { x: 0, y: 0, z: 0 } };
  const moved = applyPosition(lineUp, engineMean);
  lineUp.shift = { x: roomMean.x - moved.x, y: roomMean.y - moved.y, z: roomMean.z - moved.z };
  return lineUp;
}

function applyPosition(lineUp: EngineToRoom, p: Position): Position {
  const [cos, sin] = [Math.cos(lineUp.yaw), Math.sin(lineUp.yaw)];
  return {
    x: lineUp.shift.x + lineUp.scale * (cos * p.x + sin * p.z),
    y: lineUp.shift.y + lineUp.scale * p.y,
    z: lineUp.shift.z + lineUp.scale * (-sin * p.x + cos * p.z),
  };
}

function apply(lineUp: EngineToRoom, engine: RoomPose): RoomPose {
  const turn = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), lineUp.yaw);
  const o = turn.multiply(new THREE.Quaternion(engine.orientation.x, engine.orientation.y, engine.orientation.z, engine.orientation.w));
  return { position: applyPosition(lineUp, engine.position), orientation: { x: o.x, y: o.y, z: o.z, w: o.w } };
}
