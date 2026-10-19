import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { RoomPose } from './marker-geometry';
import type { AlignmentState, SessionState } from './protocol';
import { applyPlacement, placeEntities } from './room';

const emptyRoom = (): SessionState['room'] => ({
  available: false, room_version: null, units: null, frame: null, quaternion_order: null, error: null,
  entities: [], markers: [], loaded_by: { mobile_master: null, vr_solver: null },
});

export class DiagnosticScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(60, 1, 0.01, 100);
  private readonly marker: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;
  private readonly grid: THREE.GridHelper;
  private readonly loader = new GLTFLoader();
  private readonly container: HTMLElement;
  private readonly roomAnchor = new THREE.Group();
  private roomGroup: THREE.Group | null = null;
  private presenting = false;
  /** This phone's own measured pose, which its view follows while it tracks. */
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

  constructor(container: HTMLElement) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.xr.enabled = true;
    this.camera.position.set(0, 1.6, 2.4);
    this.camera.lookAt(0, 0.6, -1.2);
    this.scene.background = new THREE.Color('#0c1828');
    this.scene.add(new THREE.HemisphereLight(0xdff7ff, 0x344156, 2));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 4, 1);
    this.scene.add(light);
    this.grid = new THREE.GridHelper(10, 20, 0x537a91, 0x23394f);
    this.scene.add(this.grid);
    this.roomAnchor.name = 'room-anchor';
    this.scene.add(this.roomAnchor);
    // The phone's accepted position, in room meters like the furniture.
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.08, 24, 16),
      new THREE.MeshStandardMaterial({ color: 0x66e6cf, emissive: 0x154b43 }),
    );
    this.marker.name = 'phone-marker';
    this.marker.visible = false;
    this.roomAnchor.add(this.marker);
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
    container.append(this.renderer.domElement);
    container.dataset.view = 'overview';
    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      this.renderer.setSize(width, height);
      this.camera.aspect = width / Math.max(height, 1);
      this.camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe(container);
    resize();
  }

  apply(state: SessionState): void {
    const position = state.marker.position;
    // A tracking phone looks out from its own position, so it does not draw itself.
    this.marker.visible = position !== null && this.following === null;
    if (position) this.marker.position.set(position.x, position.y, position.z);
  }

  /** Moves this device's view to its measured room pose, or back to the default view with null. */
  follow(pose: RoomPose | null): void {
    this.following = pose;
    if (pose) {
      this.marker.visible = false;
      this.camera.position.set(pose.position.x, pose.position.y, pose.position.z);
      this.camera.quaternion.set(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w);
      this.container.dataset.view = 'tracked';
    } else {
      this.applyView(this.alignment);
    }
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
      let roots: Map<string, THREE.Object3D>;
      try {
        const scenes = await Promise.all(urls.map(url => this.loader.loadAsync(url).then(
          gltf => [url, gltf.scene] as const,
          () => { throw new Error(`The prepared room asset ${url.split('/').pop()} could not be loaded.`); },
        )));
        if (token !== this.loadToken) return null;
        roots = placeEntities(new Map(scenes), room.entities);
      } catch (error) {
        if (token !== this.loadToken) return null;
        this.clearRoom();
        throw error;
      }
      this.attach(roots);
      this.loadedVersion = version;
      this.loadingVersion = null;
      return { version, acknowledge: true };
    }
    applyPlacement(this.entityRoots, room.entities);
    return { version: room.room_version, acknowledge: false };
  }

  clearRoom(): void {
    this.loadToken += 1;
    this.loadedVersion = null;
    this.loadingVersion = null;
    this.roomGroup?.removeFromParent();
    this.roomGroup = null;
    this.entityRoots = new Map();
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
      this.roomAnchor.position.set(0, 0, 0);
    }
    // A tracked pose already places this device's view in the room.
    if (!this.presenting && !this.following && aligned) {
      this.camera.position.set(0, 1.6, 0);
      this.camera.lookAt(0, 1.6, -1.2);
    } else if (!this.presenting && !this.following) {
      this.camera.position.set(0, 1.6, 2.4);
      this.camera.lookAt(0, 0.6, -1.2);
    }
    this.container.dataset.view = this.following ? 'tracked' : aligned ? 'calibrated' : 'overview';
    this.paintStatus(aligned ? 'Aligned' : 'Press A');
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
    context.font = '700 72px sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, this.statusCanvas.width / 2, this.statusCanvas.height / 2);
    this.statusTexture.needsUpdate = true;
  }

  private attach(roots: Map<string, THREE.Object3D>): void {
    this.roomGroup?.removeFromParent();
    const group = new THREE.Group();
    group.name = 'prepared-room';
    group.add(...roots.values());
    this.roomGroup = group;
    this.entityRoots = roots;
    this.roomAnchor.add(group);
    this.grid.visible = false;
  }
}
