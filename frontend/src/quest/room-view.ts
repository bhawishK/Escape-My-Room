import type { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { STANDING_EYE_HEIGHT } from '../alignment';
import type { AlignmentState, Position, PresenceState, SessionState } from '../protocol';
import { applyPlacement, placeEntities } from '../room';

/** A ray drawn from a controller, a hand or a fingertip, in the `local` reference space. */
export interface DrawnRay {
  origin: Position;
  direction: Position;
  /** The colour says what it is on: cyan nothing, orange a movable object, red one the phone holds. */
  look: 'miss' | 'target' | 'blocked';
}

const RAY_COLOURS = { miss: 0x30b0c7, target: 0xff9500, blocked: 0xff3b30 } as const;
const REACH_METRES = 4;
/** The calm view (#156): the room fades to this while an open palm pauses the visit. */
const CALM_COLOUR = new THREE.Color('#203040');
const ROOM_BACKGROUND = new THREE.Color('#f5f5f7');

/**
 * The live room in the headset's IWSDK scene: the prepared room's objects and its splat, the
 * phone user's marker, and the rays. Like the phone page's `DiagnosticScene`, but drawing into
 * IWSDK's scene and renderer, and only what the headset needs.
 */
export class QuestRoom {
  /** Holds the room in room metres; turned and moved by the headset's alignment. */
  readonly anchor = new THREE.Group();
  private readonly loader = new GLTFLoader();
  private readonly phone: THREE.Group;
  private readonly highlight = new THREE.BoxHelper(new THREE.Object3D(), 0xffcc00);
  private readonly control = new THREE.BoxHelper(new THREE.Object3D(), 0xff9500);
  private readonly rays: THREE.Mesh[] = [];
  private roomGroup: THREE.Group | null = null;
  private splat: SplatMesh | null = null;
  private sparkReady: Promise<typeof import('@sparkjsdev/spark')> | null = null;
  private entityRoots = new Map<string, THREE.Object3D>();
  private loadedVersion: number | null = null;
  private loadingVersion: number | null = null;
  private loadToken = 0;
  private presenting = false;
  private alignment: AlignmentState = { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } };
  private predicted: { id: string; position: THREE.Vector3 } | null = null;
  /** An object the phone holds glides to each placement Python sends, over about this long. */
  private readonly glideMs = 120;
  private gliding: { id: string; target: THREE.Vector3 } | null = null;
  private calm = false;

  constructor(
    private readonly scene: THREE.Scene,
    private readonly renderer: THREE.WebGLRenderer,
    private readonly container: HTMLElement,
  ) {
    this.anchor.name = 'room-anchor';
    scene.add(this.anchor);
    scene.background = ROOM_BACKGROUND;
    scene.add(new THREE.HemisphereLight(0xdff7ff, 0x344156, 2));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 4, 1);
    scene.add(light);
    this.phone = person(0x30b0c7);
    this.anchor.add(this.phone);
    this.highlight.visible = false;
    this.control.visible = false;
    scene.add(this.highlight, this.control);
    this.align(this.alignment);
  }

  /** Draws the phone user where Python last placed them; faded while their tracking is stale. */
  showPhone(presence: PresenceState | undefined): void {
    const shown = (presence?.tracking_status === 'tracked' || presence?.tracking_status === 'stale') &&
      presence.position !== null && presence.heading !== null;
    this.phone.visible = shown;
    this.container.dataset.phoneShown = String(shown);
    if (!shown || !presence?.position || presence.heading === null) return;
    this.phone.position.set(presence.position.x, presence.position.y, presence.position.z);
    this.phone.rotation.y = presence.heading;
    const stale = presence.tracking_status === 'stale';
    this.phone.traverse(child => {
      const material = (child as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
      if (!material) return;
      material.transparent = true;
      material.opacity = stale ? 0.35 : 1;
    });
  }

  /** Puts the room where the headset's alignment says it is; before alignment, the floor under the eyes. */
  setPresenting(active: boolean): void {
    this.presenting = active;
    this.align(this.alignment);
  }

  align(alignment: AlignmentState): void {
    this.alignment = alignment;
    if (this.presenting && alignment.status === 'aligned') {
      const { yaw, origin: { x, y, z } } = alignment;
      const cosine = Math.cos(yaw);
      const sine = Math.sin(yaw);
      // The inverse of `roomPoint`: room metres back into the `local` reference space.
      this.anchor.rotation.y = -yaw;
      this.anchor.position.set(-cosine * x + sine * z, -y, -sine * x - cosine * z);
    } else {
      this.anchor.rotation.y = 0;
      // The `local` space starts at the eyes, so in VR the room's floor is standing eye height
      // below. On the page the preview camera stands on the room's own floor.
      this.anchor.position.set(0, this.presenting ? -STANDING_EYE_HEIGHT : 0, 0);
    }
    this.container.dataset.view = alignment.status === 'aligned' ? 'calibrated' : 'overview';
  }

  /** The calm view: the room fades away until it is called again with false. */
  setCalm(calm: boolean): void {
    this.calm = calm;
    if (this.roomGroup) this.roomGroup.visible = !calm;
    this.scene.background = calm ? CALM_COLOUR : ROOM_BACKGROUND;
    this.container.dataset.calm = String(calm);
  }

  /** Each ray, in the `local` reference space. */
  showRays(rays: readonly DrawnRay[]): void {
    while (this.rays.length < rays.length) {
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 1, 6), new THREE.MeshBasicMaterial());
      beam.frustumCulled = false;
      this.scene.add(beam);
      this.rays.push(beam);
    }
    const up = new THREE.Vector3(0, 1, 0);
    this.rays.forEach((beam, index) => {
      const ray = rays[index];
      const direction = ray && new THREE.Vector3(ray.direction.x, ray.direction.y, ray.direction.z);
      beam.visible = Boolean(ray && direction && direction.lengthSq() > 1e-8);
      if (!ray || !direction || !beam.visible) return;
      direction.normalize();
      beam.scale.set(1, REACH_METRES, 1);
      beam.position.set(
        ray.origin.x + direction.x * REACH_METRES / 2,
        ray.origin.y + direction.y * REACH_METRES / 2,
        ray.origin.z + direction.z * REACH_METRES / 2,
      );
      beam.quaternion.setFromUnitVectors(up, direction);
      (beam.material as THREE.MeshBasicMaterial).color.setHex(RAY_COLOURS[ray.look]);
    });
  }

  /** Outlines an object: what a ray, a point or the gaze is on; none for null. */
  showHighlight(id: string | null): void {
    this.container.dataset.highlighted = this.outline(this.highlight, id) ? id! : '';
  }

  /** Outlines the object someone holds, or none for null. */
  showControl(id: string | null): void {
    this.outline(this.control, id);
  }

  /** Puts `box` around an object, or hides it; whether the object is here to outline. */
  private outline(box: THREE.BoxHelper, id: string | null): boolean {
    const root = id ? this.entityRoots.get(id) : undefined;
    if (root) box.setFromObject(root);
    box.visible = root !== undefined;
    return box.visible;
  }

  /** Draws a held object where the headset's grip puts it, ahead of Python's answer; null stops. */
  predict(id: string | null, position: Position | null = null): void {
    this.predicted = id && position ? { id, position: new THREE.Vector3(position.x, position.y, position.z) } : null;
    if (this.predicted) this.entityRoots.get(this.predicted.id)?.position.copy(this.predicted.position);
  }

  /** Glides the object the phone holds toward its placements; null ends the glide. */
  glide(id: string | null): void {
    if ((this.gliding?.id ?? null) === id) return;
    const root = id ? this.entityRoots.get(id) : undefined;
    this.gliding = id && root ? { id, target: root.position.clone() } : null;
  }

  /** Moves the glide on by `ms` milliseconds. */
  tick(ms: number): void {
    const root = this.gliding ? this.entityRoots.get(this.gliding.id) : undefined;
    if (!this.gliding || !root) return;
    root.position.lerp(this.gliding.target, 1 - Math.exp(-ms / this.glideMs));
  }

  /**
   * Loads a new room version, or places the objects of the one loaded. Resolves with the version
   * and whether it was just loaded, so the page tells Python once.
   */
  async sync(state: SessionState): Promise<{ version: number; loaded: boolean } | null> {
    const room = state.room;
    if (!room.available || room.room_version === null) {
      this.clear();
      if (room.error) throw new Error(room.error);
      return null;
    }
    if (this.loadedVersion === room.room_version) {
      const glidingFrom = this.gliding ? this.entityRoots.get(this.gliding.id)?.position.clone() : undefined;
      applyPlacement(this.entityRoots, room.entities);
      const root = this.gliding ? this.entityRoots.get(this.gliding.id) : undefined;
      if (this.gliding && root && glidingFrom) {
        this.gliding.target.copy(root.position);
        root.position.copy(glidingFrom);
      }
      if (this.predicted) this.entityRoots.get(this.predicted.id)?.position.copy(this.predicted.position);
      return { version: room.room_version, loaded: false };
    }
    if (this.loadingVersion === room.room_version) return null;
    const token = ++this.loadToken;
    const version = room.room_version;
    this.loadingVersion = version;
    try {
      // Every asset loads before any shows, so a failure never leaves half a room.
      const urls = [...new Set(room.entities.map(entity => entity.asset_url))];
      const [scenes, splat] = await Promise.all([
        Promise.all(urls.map(url => this.loader.loadAsync(url).then(
          gltf => [url, gltf.scene] as const,
          () => { throw new Error(`The prepared room asset ${fileName(url)} could not be loaded.`); },
        ))),
        room.splat_url ? this.loadSplat(room.splat_url) : null,
      ]);
      if (token !== this.loadToken) {
        splat?.dispose();
        return null;
      }
      const roots = placeEntities(new Map(scenes), room.entities);
      if (splat && room.splat_placement) {
        const { position, rotation, scale } = room.splat_placement;
        splat.position.set(position.x, position.y, position.z);
        splat.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
        splat.scale.setScalar(scale);
      }
      this.attach(roots, splat, room);
      this.loadedVersion = version;
      return { version, loaded: true };
    } catch (error) {
      if (token === this.loadToken) this.clear();
      throw error;
    } finally {
      if (token === this.loadToken) this.loadingVersion = null;
    }
  }

  private attach(roots: Map<string, THREE.Object3D>, splat: SplatMesh | null, room: SessionState['room']): void {
    this.roomGroup?.removeFromParent();
    this.splat?.dispose();
    const group = new THREE.Group();
    group.name = 'prepared-room';
    group.add(...roots.values());
    if (splat) {
      // The splat is the room's look. Static objects stay, unseen, so rays still stop at them.
      group.add(splat);
      for (const entity of room.entities) {
        const root = roots.get(entity.id);
        if (root && entity.kind === 'static') root.visible = false;
      }
    }
    group.visible = !this.calm;
    this.anchor.add(group);
    this.roomGroup = group;
    this.splat = splat;
    this.entityRoots = roots;
    this.container.dataset.roomVersion = String(room.room_version);
    // Shown only once the splat is really in this scene: a second copy of three.js would refuse it.
    this.container.dataset.splat = splat && splat.parent === group ? 'shown' : '';
  }

  private clear(): void {
    this.loadToken += 1;
    this.loadedVersion = null;
    this.loadingVersion = null;
    this.roomGroup?.removeFromParent();
    this.roomGroup = null;
    this.splat?.dispose();
    this.splat = null;
    this.entityRoots = new Map();
    this.predicted = null;
    this.gliding = null;
    this.showHighlight(null);
    this.showControl(null);
    this.container.dataset.roomVersion = '';
    this.container.dataset.splat = '';
  }

  /** Downloads a room splat, loading Spark the first time one is needed. */
  private async loadSplat(url: string): Promise<SplatMesh> {
    const failed = new Error(`The prepared room splat ${fileName(url)} could not be loaded.`);
    this.sparkReady ??= import('@sparkjsdev/spark').then(spark => {
      this.scene.add(new spark.SparkRenderer({ renderer: this.renderer }));
      return spark;
    });
    try {
      const [spark, response] = await Promise.all([this.sparkReady, fetch(url)]);
      if (!response.ok) throw failed;
      const mesh = new spark.SplatMesh({
        fileBytes: await response.arrayBuffer(),
        fileName: fileName(url),
        // Rays stop at the room's objects, not at hundreds of thousands of splats.
        raycastable: false,
      });
      await mesh.initialized;
      return mesh;
    } catch {
      throw failed;
    }
  }
}

const fileName = (url: string) => url.split('/').pop() ?? url;

/** A standing figure facing -z: a body, a head and a nose for the way they face. */
function person(colour: number): THREE.Group {
  const group = new THREE.Group();
  group.name = 'presence-phone';
  const material = new THREE.MeshStandardMaterial({ color: colour });
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 1.2, 16), material);
  body.position.y = 0.6;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 12), material.clone());
  head.position.y = 1.4;
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.14, 12), material.clone());
  nose.rotation.x = -Math.PI / 2;
  nose.position.set(0, 1.4, -0.16);
  group.add(body, head, nose);
  group.visible = false;
  return group;
}
