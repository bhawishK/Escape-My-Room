import * as THREE from 'three';
import type { SessionState } from './protocol';

export class DiagnosticScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(60, 1, 0.01, 100);
  private readonly marker: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;

  constructor(container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.xr.enabled = true;
    this.camera.position.set(0, 1.4, 2);
    this.camera.lookAt(0, 1.2, -3);
    this.scene.background = new THREE.Color('#0c1828');
    this.scene.add(new THREE.HemisphereLight(0xdff7ff, 0x344156, 2));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 4, 1);
    this.scene.add(light);
    const grid = new THREE.GridHelper(10, 20, 0x537a91, 0x23394f);
    this.scene.add(grid);
    const diagnostic = new THREE.Group();
    // Presentation offset only; no room alignment or calibration is implied.
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

  setAR(enabled: boolean): void {
    this.scene.background = enabled ? null : new THREE.Color('#0c1828');
  }
}
