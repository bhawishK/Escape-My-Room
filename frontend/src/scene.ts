import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/addons/loaders/GLTFLoader.js';
import type { AlignmentState, RoomEntity, SessionState } from './protocol';

const emptyRoom = (): SessionState['room'] => ({
  available: false, room_version: null, units: null, asset_url: null, error: null, entities: [],
  loaded_by: { mobile_master: null, vr_solver: null },
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
  private alignment: AlignmentState = { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } };
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
    this.roomAnchor.name = 'room-anchor';
    this.scene.add(this.roomAnchor);
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
    this.marker.visible = position !== null;
    if (position) this.marker.position.set(position.x, position.y, position.z);
  }

  async syncRoom(state: SessionState): Promise<{ version: number; acknowledge: boolean } | null> {
    const room = state.room ?? emptyRoom();
    if (!room.available || room.room_version === null || room.asset_url === null) {
      this.clearRoom();
      if (room.error) throw new Error(room.error);
      return null;
    }
    if (this.loadedVersion !== room.room_version) {
      if (this.loadingVersion === room.room_version) return null;
      const token = ++this.loadToken;
      const version = room.room_version;
      this.loadingVersion = version;
      let gltf: GLTF;
      try {
        gltf = await this.loader.loadAsync(room.asset_url);
      } catch {
        if (token !== this.loadToken) return null;
        this.clearRoom();
        throw new Error('The prepared room model could not be loaded.');
      }
      if (token !== this.loadToken) return null;
      const missing = room.entities.find(entity => gltf.scene.getObjectByName(entity.node) === undefined);
      if (missing) {
        this.clearRoom();
        throw new Error(`The prepared room model is missing ${missing.id}.`);
      }
      this.attach(gltf, room.entities);
      this.loadedVersion = version;
      this.loadingVersion = null;
      this.applyEntities(room.entities);
      return { version, acknowledge: true };
    }
    this.applyEntities(room.entities);
    return { version: room.room_version, acknowledge: false };
  }

  clearRoom(): void {
    this.loadToken += 1;
    this.loadedVersion = null;
    this.loadingVersion = null;
    this.roomGroup?.removeFromParent();
    this.roomGroup = null;
    this.grid.visible = true;
  }

  setAR(enabled: boolean): void {
    this.scene.background = enabled ? null : new THREE.Color('#0c1828');
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
    if (!this.presenting && aligned) {
      this.camera.position.set(0, 1.6, 0);
      this.camera.lookAt(0, 1.6, -1.2);
    } else if (!this.presenting) {
      this.camera.position.set(0, 1.6, 2.4);
      this.camera.lookAt(0, 0.6, -1.2);
    }
    this.container.dataset.view = aligned ? 'calibrated' : 'overview';
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

  private attach(gltf: GLTF, entities: RoomEntity[]): void {
    this.roomGroup?.removeFromParent();
    const group = new THREE.Group();
    group.name = 'prepared-room';
    for (const entity of entities) {
      const object = gltf.scene.getObjectByName(entity.node);
      if (!object) throw new Error(`The prepared room model is missing ${entity.id}.`);
      object.removeFromParent();
      object.userData.entityId = entity.id;
      group.add(object);
    }
    this.roomGroup = group;
    this.roomAnchor.add(group);
    this.grid.visible = false;
  }

  private applyEntities(entities: RoomEntity[]): void {
    for (const entity of entities) {
      this.roomGroup?.getObjectByName(entity.node)?.position.set(
        entity.position.x, entity.position.y, entity.position.z,
      );
    }
  }
}
