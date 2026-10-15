import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { SessionState } from './protocol';
import { applyPlacement, placeEntities } from './room';

const emptyRoom = (): SessionState['room'] => ({
  available: false, room_version: null, units: null, frame: null, quaternion_order: null, error: null,
  entities: [], loaded_by: { mobile_master: null, vr_solver: null },
});

export class DiagnosticScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(60, 1, 0.01, 100);
  private readonly marker: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;
  private readonly grid: THREE.GridHelper;
  private readonly loader = new GLTFLoader();
  private roomGroup: THREE.Group | null = null;
  private entityRoots = new Map<string, THREE.Object3D>();
  private loadedVersion: number | null = null;
  private loadingVersion: number | null = null;
  private loadToken = 0;

  constructor(container: HTMLElement) {
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
    const diagnostic = new THREE.Group();
    // Marker offset only; the prepared room uses manifest meters at the scene origin.
    diagnostic.position.set(0, 1.2, -3);
    diagnostic.add(new THREE.AxesHelper(0.5));
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.08, 24, 16),
      new THREE.MeshStandardMaterial({ color: 0x66e6cf, emissive: 0x154b43 }),
    );
    this.marker.visible = false;
    diagnostic.add(this.marker);
    this.scene.add(diagnostic);
    container.append(this.renderer.domElement);
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
    this.marker.visible = position !== null;
    if (position) this.marker.position.set(position.x, position.y, position.z);
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

  setAR(enabled: boolean): void {
    this.scene.background = enabled ? null : new THREE.Color('#0c1828');
  }

  private attach(roots: Map<string, THREE.Object3D>): void {
    this.roomGroup?.removeFromParent();
    const group = new THREE.Group();
    group.name = 'prepared-room';
    group.add(...roots.values());
    this.roomGroup = group;
    this.entityRoots = roots;
    this.scene.add(group);
    this.grid.visible = false;
  }
}
