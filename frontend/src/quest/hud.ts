import * as THREE from 'three';

/**
 * A short line of text in front of the headset's eyes, below the centre. IWSDK's sessions have no
 * DOM overlay, so what the page's `xr-hud` said is drawn here.
 */
export class Hud {
  readonly sprite: THREE.Sprite;
  private readonly canvas = document.createElement('canvas');
  private readonly texture: THREE.CanvasTexture;
  private text = '';

  constructor() {
    this.canvas.width = 768;
    this.canvas.height = 128;
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.texture, transparent: true, depthTest: false }));
    this.sprite.scale.set(0.6, 0.1, 1);
    this.sprite.position.set(0, -0.22, -0.8);
    this.sprite.renderOrder = 10;
    this.sprite.visible = false;
  }

  /** Shows `text`, or hides the line for null. `calm` draws it in the colour for good news. */
  show(text: string | null, calm = false): void {
    this.sprite.visible = text !== null;
    if (text === null || text === this.text) return;
    this.text = text;
    const context = this.canvas.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    context.fillStyle = '#08111ee8';
    context.fillRect(0, 0, this.canvas.width, this.canvas.height);
    context.fillStyle = calm ? '#81ded1' : '#ffd399';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    let size = 48;
    context.font = `700 ${size}px sans-serif`;
    while (size > 22 && context.measureText(text).width > this.canvas.width - 40) {
      size -= 2;
      context.font = `700 ${size}px sans-serif`;
    }
    context.fillText(text, this.canvas.width / 2, this.canvas.height / 2);
    this.texture.needsUpdate = true;
  }
}
