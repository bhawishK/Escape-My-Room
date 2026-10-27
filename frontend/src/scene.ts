import type { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { STANDING_EYE_HEIGHT } from './alignment';
import type { RoomPose } from './phone-view';
import type { SplatDrawn } from './tracking-stats';
import type {
  AlignmentState, Position, PresenceState, Role, RoomEntity, SessionState,
} from './protocol';
import { applyPlacement, placeEntities } from './room';

const emptyRoom = (): SessionState['room'] => ({
  available: false, room_version: null, units: null, frame: null, quaternion_order: null, error: null,
  entities: [], splat_url: null, splat_phone_url: null, splat_placement: null, landmarks: [], map: null, loaded_by: { mobile_master: null, vr_solver: null },
});

const OVERVIEW_FOV = 60;
const PHONE_VIEW_FOV = 70;

export class DiagnosticScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(OVERVIEW_FOV, 1, 0.01, 100);
  private readonly marker: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;
  private readonly people = new Map<Role, THREE.Group>();
  private localRole: Role | null = null;
  private readonly grid: THREE.GridHelper;
  private readonly loader = new GLTFLoader();
  private readonly container: HTMLElement;
  private readonly roomAnchor = new THREE.Group();
  private roomGroup: THREE.Group | null = null;
  /** The room's splat, when it has one; Spark is loaded only for such rooms. */
  private splat: SplatMesh | null = null;
  /** The splat file drawn and how many splats it holds, for the diagnostic report. */
  splatDrawn: SplatDrawn | null = null;
  /**
   * When something drawn last changed other than the camera: state, a glide, a selection, a
   * loaded room. The phone draws on demand (#109), so it draws fully for a moment after this.
   */
  changedAt = -Infinity;
  /** What `apply` and the room's placements last drew, to tell a change from a repeat. */
  private drawnState = '';
  private drawnPlacement = '';
  private resize: () => void = () => undefined;
  private sparkReady: Promise<typeof import('@sparkjsdev/spark')> | null = null;
  private presenting = false;
  /** The pose this phone's full-screen room view looks from. */
  private following: RoomPose | null = null;
  private alignment: AlignmentState = { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } };
  private entityRoots = new Map<string, THREE.Object3D>();
  private loadedVersion: number | null = null;
  private loadingVersion: number | null = null;
  private loadToken = 0;
  private readonly statusCanvas = document.createElement('canvas');
  private readonly statusTexture: THREE.CanvasTexture;
  private readonly statusLabel: THREE.Sprite;
  private statusText = '';
  /** A message in front of the headset, instead of Press A or Aligned, until cleared. */
  private notice: string | null = null;
  private readonly raycaster = new THREE.Raycaster();
  /** Outlines the object the phone's gaze cursor is over. */
  private readonly highlight = new THREE.BoxHelper(new THREE.Object3D(), 0xffcc00);
  private highlighted: string | null = null;
  /** Outlines the object this phone has selected, in a colour apart from the gaze outline. */
  private readonly selection = new THREE.BoxHelper(new THREE.Object3D(), 0xff2d55);
  /** A halo around the selected object: only its far faces are drawn, so the object keeps its colour. */
  private readonly selectionShell = new THREE.Mesh(
    new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshBasicMaterial({
      color: 0xff2d55, transparent: true, opacity: 0.6, depthWrite: false, side: THREE.BackSide,
    }),
  );
  private selected: string | null = null;
  /** Outlines the object someone is holding, on both devices. */
  private readonly control = new THREE.BoxHelper(new THREE.Object3D(), 0xff9500);
  /** Beams from the headset controllers. Cyan misses; orange is on a movable object. */
  private readonly aimBeams: THREE.Mesh[] = [];
  private controlled: string | null = null;
  private predicted: { id: string; position: THREE.Vector3 } | null = null;
  /**
   * An object another device holds glides toward each accepted placement over about this many
   * milliseconds, rather than stepping at each network update; 0 draws each placement at once.
   * Only the drawing is smoothed: Python's placement is unchanged.
   */
  smoothingMs = 120;
  private smoothed: { id: string; target: THREE.Vector3 } | null = null;
  /** Where an object was drawn when its hold ended, to measure the jump to Python's final placement. */
  private settling: { id: string; from: THREE.Vector3 } | null = null;
  /** Called with how far an object jumped, in meters, to reach its final placement after a hold. */
  onCorrection: ((meters: number) => void) | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.xr.enabled = true;
    this.camera.position.set(0, 1.6, 2.4);
    this.camera.lookAt(0, 0.6, -1.2);
    this.scene.background = new THREE.Color('#f5f5f7');
    this.scene.add(new THREE.HemisphereLight(0xdff7ff, 0x344156, 2));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 4, 1);
    this.scene.add(light);
    this.grid = new THREE.GridHelper(10, 20, 0xaeaeb2, 0xd8d8dc);
    this.scene.add(this.grid);
    this.roomAnchor.name = 'room-anchor';
    this.scene.add(this.roomAnchor);
    // The phone's accepted position, in room meters like the furniture.
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.08, 24, 16),
      new THREE.MeshStandardMaterial({ color: 0x30b0c7, emissive: 0x0b3a42 }),
    );
    this.marker.name = 'phone-marker';
    this.marker.visible = false;
    this.roomAnchor.add(this.marker);
    this.people.set('mobile_master', this.person(0x30b0c7, 'presence-phone'));
    this.people.set('vr_solver', this.person(0xff9500, 'presence-headset'));
    this.statusCanvas.width = 512;
    this.statusCanvas.height = 160;
    this.statusTexture = new THREE.CanvasTexture(this.statusCanvas);
    this.statusTexture.colorSpace = THREE.SRGBColorSpace;
    this.statusLabel = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.statusTexture, transparent: true, depthTest: false,
    }));
    this.statusLabel.scale.set(1.4, 0.44, 1);
    this.statusLabel.position.set(0, 1.45, -0.8);
    this.statusLabel.visible = false;
    this.roomAnchor.add(this.statusLabel);
    this.highlight.visible = false;
    this.scene.add(this.highlight);
    this.selection.visible = false;
    this.selectionShell.visible = false;
    this.scene.add(this.selection, this.selectionShell);
    this.control.visible = false;
    this.scene.add(this.control);
    container.append(this.renderer.domElement);
    container.dataset.view = 'overview';
    this.resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      this.renderer.setSize(width, height);
      this.camera.aspect = width / Math.max(height, 1);
      this.camera.updateProjectionMatrix();
    };
    new ResizeObserver(this.resize).observe(container);
    this.resize();
  }

  /** This page's role, so its own presence marker stays hidden. */
  setLocalRole(role: Role | null): void {
    // Called with every state: resizing redraws nothing until the next frame, and the
    // headset may not resize while presenting, so only a new role changes anything.
    if (role === this.localRole) return;
    this.localRole = role;
    // The phone draws one pixel per screen pixel: up to four times fewer than at two, which
    // leaves 8th Wall the time to track (#109). Its splat is small on a phone's screen anyway.
    this.renderer.setPixelRatio(role === 'mobile_master' ? 1 : Math.min(devicePixelRatio, 2));
    this.resize();
  }

  apply(state: SessionState): void {
    // Every state message comes here, the phone's own presence included: only what this view
    // draws, the marker and the other person, counts as a change.
    const drawn = JSON.stringify([
      state.marker.position,
      (['mobile_master', 'vr_solver'] as const).filter(who => who !== this.localRole).map(who => state.participants?.[who] ?? null),
    ]);
    if (drawn !== this.drawnState) {
      this.drawnState = drawn;
      this.changedAt = performance.now();
    }
    const position = state.marker.position;
    const phone = state.participants?.mobile_master;
    const phoneShown = phone?.tracking_status === 'tracked' || phone?.tracking_status === 'stale';
    // A phone looking out from its own view does not draw itself. A live presence marker replaces it.
    this.marker.visible = position !== null && this.following === null && !phoneShown;
    if (position) this.marker.position.set(position.x, position.y, position.z);
    for (const who of ['mobile_master', 'vr_solver'] as const) {
      this.showPerson(who, state.participants?.[who]);
    }
  }

  private person(color: number, name: string): THREE.Group {
    const group = new THREE.Group();
    group.name = name;
    group.visible = false;
    const material = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25 });
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.08, 24, 16), material);
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.2, 12), material.clone());
    arrow.rotation.x = Math.PI / 2;
    arrow.position.z = -0.18;
    group.add(head, arrow);
    this.roomAnchor.add(group);
    return group;
  }

  private showPerson(role: Role, presence: PresenceState | undefined): void {
    const group = this.people.get(role);
    if (!group) return;
    const visible = role !== this.localRole &&
      (presence?.tracking_status === 'tracked' || presence?.tracking_status === 'stale') &&
      presence.position !== null && presence.heading !== null;
    group.visible = visible;
    if (!presence?.position || presence.heading === null) return;
    group.position.set(presence.position.x, presence.position.y, presence.position.z);
    group.rotation.y = presence.heading;
    const stale = presence.tracking_status === 'stale';
    group.traverse(child => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.transparent = true;
      material.opacity = stale ? 0.35 : 1;
    });
  }

  /** Moves this device's view to the phone's room pose, or back to the default view with null. */
  follow(pose: RoomPose | null): void {
    this.following = pose;
    // The phone's view spans about what its camera sees along the screen's long side.
    const fov = pose ? PHONE_VIEW_FOV : OVERVIEW_FOV;
    if (this.camera.fov !== fov) {
      this.camera.fov = fov;
      this.camera.updateProjectionMatrix();
    }
    if (pose) {
      this.marker.visible = false;
      this.camera.position.set(pose.position.x, pose.position.y, pose.position.z);
      this.camera.quaternion.set(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w);
      this.container.dataset.view = 'phone';
    } else {
      this.applyView(this.alignment);
    }
  }

  /** The room entity drawn at a point on the view, 0–1 across and down, or null where there is none. */
  entityAt(point: { x: number; y: number }): string | null {
    if (!this.roomGroup) return null;
    this.raycaster.setFromCamera(new THREE.Vector2(point.x * 2 - 1, 1 - point.y * 2), this.camera);
    // The nearest surface wins, so furniture in front hides what is behind it.
    const hit = this.raycaster.intersectObject(this.roomGroup, true)[0];
    for (let object: THREE.Object3D | null = hit?.object ?? null; object; object = object.parent) {
      for (const [id, root] of this.entityRoots) if (root === object) return id;
    }
    return null;
  }

  /**
   * The room entity at a point on the view, outlined until another is pointed at; null, and no
   * outline, where there is none or for a null point.
   */
  pointAt(point: { x: number; y: number } | null): string | null {
    const found = point ? this.entityAt(point) : null;
    if (found !== this.highlighted) {
      this.highlighted = found;
      const root = found ? this.entityRoots.get(found) : undefined;
      if (root) this.highlight.setFromObject(root);
      this.highlight.visible = root !== undefined;
    }
    return found;
  }

  /** Outlines the entity Python accepted as this phone's selection, or none for null. */
  select(id: string | null): void {
    if (id !== this.selected) this.changedAt = performance.now();
    this.selected = id;
    this.outlineSelection();
  }

  /**
   * Draws an entity where this device expects Python to put it, ahead of Python's answer; null
   * returns it to Python's placement at the next state.
   */
  predict(id: string | null, position: Position | null = null): void {
    if (!(id && position) && this.predicted) this.settling = { id: this.predicted.id, from: this.predicted.position.clone() };
    this.predicted = id && position ? { id, position: new THREE.Vector3(position.x, position.y, position.z) } : null;
    if (!this.predicted) return;
    this.entityRoots.get(this.predicted.id)?.position.copy(this.predicted.position);
    this.outlineSelection();
  }

  /**
   * Glides an object another device holds toward its accepted placements; null ends the glide,
   * and the next placement, the final one, is drawn exactly.
   */
  smooth(id: string | null): void {
    if ((this.smoothed?.id ?? null) === id) return;
    const ending = this.smoothed;
    this.smoothed = null;
    const endingRoot = ending ? this.entityRoots.get(ending.id) : undefined;
    if (ending && endingRoot) this.settling = { id: ending.id, from: endingRoot.position.clone() };
    const root = id ? this.entityRoots.get(id) : undefined;
    if (id && root) this.smoothed = { id, target: root.position.clone() };
  }

  /** Moves any glide on by `ms` milliseconds of drawing. */
  tick(ms: number): void {
    const root = this.smoothed ? this.entityRoots.get(this.smoothed.id) : undefined;
    if (!this.smoothed || !root) return;
    this.changedAt = performance.now();
    const blend = this.smoothingMs <= 0 ? 1 : 1 - Math.exp(-ms / this.smoothingMs);
    root.position.lerp(this.smoothed.target, blend);
    this.outlineSelection();
  }

  /**
   * Draws each controller's pointing ray in the local reference space. `targetId` is the movable
   * object one of them is on, outlined until the ray leaves it.
   */
  showAim(
    rays: readonly { origin: Position; direction: Position; onTarget: boolean; blocked?: boolean }[],
    targetId: string | null,
  ): void {
    while (this.aimBeams.length < rays.length) {
      const beam = new THREE.Mesh(
        new THREE.CylinderGeometry(0.006, 0.006, 1, 6),
        new THREE.MeshBasicMaterial({ color: 0x30b0c7 }),
      );
      beam.frustumCulled = false;
      beam.visible = false;
      this.scene.add(beam);
      this.aimBeams.push(beam);
    }
    const up = new THREE.Vector3(0, 1, 0);
    this.aimBeams.forEach((beam, index) => {
      const ray = this.presenting ? rays[index] : undefined;
      if (!ray) {
        beam.visible = false;
        return;
      }
      const dir = new THREE.Vector3(ray.direction.x, ray.direction.y, ray.direction.z);
      if (dir.lengthSq() < 1e-8) {
        beam.visible = false;
        return;
      }
      dir.normalize();
      const reach = 4;
      beam.visible = true;
      beam.scale.set(1, reach, 1);
      beam.position.set(
        ray.origin.x + dir.x * reach / 2,
        ray.origin.y + dir.y * reach / 2,
        ray.origin.z + dir.z * reach / 2,
      );
      beam.quaternion.setFromUnitVectors(up, dir);
      const material = beam.material;
      if (material instanceof THREE.MeshBasicMaterial) {
        material.color.setHex(ray.blocked ? 0xff3b30 : ray.onTarget ? 0xff9500 : 0x30b0c7);
      }
    });
    const root = targetId ? this.entityRoots.get(targetId) : undefined;
    if (root) this.highlight.setFromObject(root);
    this.highlight.visible = root !== undefined;
    this.highlighted = targetId;
  }

  /** Outlines the object being held, or none for null. */
  showControl(id: string | null): void {
    // Called with every state message: only a new hold is a change.
    if (id !== this.controlled) this.changedAt = performance.now();
    this.controlled = id;
    this.outlineSelection();
  }

  private outlineSelection(): void {
    const held = this.controlled ? this.entityRoots.get(this.controlled) : undefined;
    if (held) this.control.setFromObject(held);
    this.control.visible = held !== undefined;
    const root = this.selected ? this.entityRoots.get(this.selected) : undefined;
    if (root) {
      this.selection.setFromObject(root);
      const bounds = new THREE.Box3().setFromObject(root);
      bounds.getCenter(this.selectionShell.position);
      bounds.getSize(this.selectionShell.scale).multiplyScalar(1.2);
    }
    this.selection.visible = root !== undefined;
    this.selectionShell.visible = root !== undefined;
    this.container.dataset.selected = root ? this.selected! : '';
  }

  async syncRoom(state: SessionState): Promise<{ version: number; acknowledge: boolean } | null> {
    const room = state.room ?? emptyRoom();
    if (!room.available || room.room_version === null) {
      this.clearRoom();
      if (room.error) throw new Error(room.error);
      return null;
    }
    if (this.loadedVersion !== room.room_version) {
      if (this.loadingVersion === room.room_version) return null;
      const token = ++this.loadToken;
      const version = room.room_version;
      this.loadingVersion = version;
      // Load every asset before showing any, so a failure never leaves a partial room.
      const urls = [...new Set(room.entities.map(entity => entity.asset_url))];
      // A phone draws the lighter copy when the room has one.
      const splatUrl = this.localRole === 'mobile_master' && room.splat_phone_url ? room.splat_phone_url : room.splat_url;
      let roots: Map<string, THREE.Object3D>;
      let splat: SplatMesh | null;
      try {
        const loading = Promise.all(urls.map(url => this.loader.loadAsync(url).then(
          gltf => [url, gltf.scene] as const,
          () => { throw new Error(`The prepared room asset ${url.split('/').pop()} could not be loaded.`); },
        )));
        const [scenes, loadedSplat] = await Promise.all([
          loading,
          splatUrl ? this.loadSplat(splatUrl) : null,
        ]);
        splat = loadedSplat;
        if (token !== this.loadToken) {
          splat?.dispose();
          return null;
        }
        roots = placeEntities(new Map(scenes), room.entities);
      } catch (error) {
        if (token !== this.loadToken) return null;
        this.clearRoom();
        throw error;
      }
      if (splat && room.splat_placement) {
        const { position, rotation, scale } = room.splat_placement;
        splat.position.set(position.x, position.y, position.z);
        splat.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
        splat.scale.setScalar(scale);
      }
      this.attach(roots, splat, room.entities);
      this.splatDrawn = splat && splatUrl ? { file: splatUrl.split('/').pop() ?? splatUrl, splats: splat.packedSplats?.numSplats ?? 0 } : null;
      this.changedAt = performance.now();
      this.loadedVersion = version;
      this.loadingVersion = null;
      return { version, acknowledge: true };
    }
    const gliding = this.smoothed ? this.entityRoots.get(this.smoothed.id)?.position.clone() : undefined;
    applyPlacement(this.entityRoots, room.entities);
    // Applied with every state message: only a moved object counts as a change.
    const placed = JSON.stringify(room.entities.map(entity => [entity.position, entity.rotation]));
    if (placed !== this.drawnPlacement) {
      this.drawnPlacement = placed;
      this.changedAt = performance.now();
    }
    if (this.smoothed && gliding) {
      // The new placement becomes where the glide heads, from where it is drawn now.
      const root = this.entityRoots.get(this.smoothed.id);
      if (root) {
        this.smoothed.target.copy(root.position);
        root.position.copy(gliding);
      }
    }
    if (this.settling) {
      // The hold has ended and this is Python's final placement, drawn exactly.
      const root = this.entityRoots.get(this.settling.id);
      if (root) this.onCorrection?.(root.position.distanceTo(this.settling.from));
      this.settling = null;
    }
    // Python's answer is a moment old; the phone's own aim stays in charge of what it draws.
    if (this.predicted) this.entityRoots.get(this.predicted.id)?.position.copy(this.predicted.position);
    this.outlineSelection();
    return { version: room.room_version, acknowledge: false };
  }

  clearRoom(): void {
    this.loadToken += 1;
    this.loadedVersion = null;
    this.loadingVersion = null;
    this.roomGroup?.removeFromParent();
    this.roomGroup = null;
    this.splat?.dispose();
    this.splat = null;
    this.container.dataset.splat = '';
    this.entityRoots = new Map();
    this.pointAt(null);
    this.predicted = null;
    this.smoothed = null;
    this.settling = null;
    this.select(null);
    this.showControl(null);
    this.grid.visible = true;
  }

  setPresenting(active: boolean): void {
    this.presenting = active;
    this.applyView(this.alignment);
  }

  applyView(alignment: AlignmentState): void {
    this.alignment = alignment;
    const aligned = alignment.status === 'aligned';
    if (this.presenting && aligned) {
      const yaw = alignment.yaw;
      const cosine = Math.cos(yaw);
      const sine = Math.sin(yaw);
      const { x, y, z } = alignment.origin;
      this.roomAnchor.rotation.y = -yaw;
      this.roomAnchor.position.set(-cosine * x + sine * z, -y, -sine * x - cosine * z);
    } else {
      this.roomAnchor.rotation.y = 0;
      // Before alignment the headset's head starts near the `local` origin; stand it on the floor.
      this.roomAnchor.position.set(0, this.presenting ? -STANDING_EYE_HEIGHT : 0, 0);
    }
    // A tracked pose already places this device's view in the room.
    if (!this.presenting && !this.following && aligned) {
      this.camera.position.set(0, STANDING_EYE_HEIGHT, 0);
      this.camera.lookAt(0, STANDING_EYE_HEIGHT, -1.2);
    } else if (!this.presenting && !this.following && this.splat) {
      // A splat room looks right only near where it was filmed: its origin, facing the way the
      // video mostly faced. From the stand-in room's corner view it is mostly gaps and smears.
      this.camera.position.set(0, STANDING_EYE_HEIGHT, 0);
      this.camera.lookAt(0, STANDING_EYE_HEIGHT - 0.4, -1.2);
    } else if (!this.presenting && !this.following) {
      this.camera.position.set(0, 1.6, 2.4);
      this.camera.lookAt(0, 0.6, -1.2);
    }
    this.container.dataset.view = this.following ? 'phone' : aligned ? 'calibrated' : 'overview';
    this.refreshStatus();
  }

  /** Shows `text` on the headset sign. Null returns to Press A or Aligned. */
  showNotice(text: string | null): void {
    this.notice = text;
    this.refreshStatus();
  }

  private refreshStatus(): void {
    const aligned = this.alignment.status === 'aligned';
    this.paintStatus(this.notice ?? (aligned ? 'Aligned' : 'Press A'));
    this.statusLabel.visible = this.presenting;
  }

  private paintStatus(text: string): void {
    if (this.statusText === text) return;
    this.statusText = text;
    const context = this.statusCanvas.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, this.statusCanvas.width, this.statusCanvas.height);
    context.fillStyle = '#08111ee8';
    context.fillRect(0, 0, this.statusCanvas.width, this.statusCanvas.height);
    context.fillStyle = text === 'Aligned' ? '#81ded1' : '#ffd399';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    const maxWidth = this.statusCanvas.width - 40;
    let size = 64;
    context.font = `700 ${size}px sans-serif`;
    while (size > 28 && context.measureText(text).width > maxWidth) {
      size -= 4;
      context.font = `700 ${size}px sans-serif`;
    }
    context.fillText(text, this.statusCanvas.width / 2, this.statusCanvas.height / 2);
    this.statusTexture.needsUpdate = true;
  }

  /** Downloads and prepares a room splat, loading Spark the first time one is needed. */
  private async loadSplat(url: string): Promise<SplatMesh> {
    const failed = new Error(`The prepared room splat ${url.split('/').pop()} could not be loaded.`);
    this.sparkReady ??= import('@sparkjsdev/spark').then(spark => {
      this.scene.add(new spark.SparkRenderer({ renderer: this.renderer }));
      return spark;
    });
    try {
      const [spark, response] = await Promise.all([this.sparkReady, fetch(url)]);
      if (!response.ok) throw failed;
      const mesh = new spark.SplatMesh({
        fileBytes: await response.arrayBuffer(),
        fileName: url.split('/').pop(),
        // Aiming hits the entities, not hundreds of thousands of splats.
        raycastable: false,
      });
      await mesh.initialized;
      return mesh;
    } catch {
      throw failed;
    }
  }

  private attach(
    roots: Map<string, THREE.Object3D>,
    splat: SplatMesh | null = null,
    entities: readonly RoomEntity[] = [],
  ): void {
    this.roomGroup?.removeFromParent();
    this.splat?.dispose();
    const group = new THREE.Group();
    group.name = 'prepared-room';
    group.add(...roots.values());
    if (splat) {
      // The splat shows the room. Static entities stay, unseen, so aiming still stops at
      // furniture and walking still keeps to the floor; movable ones are drawn over it.
      group.add(splat);
      for (const entity of entities) {
        const root = roots.get(entity.id);
        if (root && entity.kind === 'static') root.visible = false;
      }
    }
    this.splat = splat;
    this.container.dataset.splat = splat ? 'shown' : '';
    this.roomGroup = group;
    this.entityRoots = roots;
    this.roomAnchor.add(group);
    this.grid.visible = false;
    // A splat room changes where the overview looks from.
    this.applyView(this.alignment);
  }
}
