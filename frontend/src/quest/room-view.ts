import type { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { STANDING_EYE_HEIGHT } from '../alignment';
import { ServerClock } from '../hazard-playback';
import type { AlignmentState, CatalogueItem, Position, PresenceState, RoomEntity, SessionState } from '../protocol';
import { RAY_REACH_METERS } from '../grab';
import { LateEntities, ModelCopies, applyPlacement, placeEntities, roomOwn } from '../room';
import {
  FIGURE_METRES, LIFE_SIZE, residentFigure, scaleLabel, type DollhouseView,
} from './dollhouse';
import { HazardFrames, type HazardRoom } from './hazard-frames';
import { PAGE_NAMES, WRIST_PAGES, type WristButton, type WristMenu } from './wrist-menu';

/** A ray drawn from a controller, a hand or a fingertip, in the `local` reference space. */
export interface DrawnRay {
  origin: Position;
  direction: Position;
  /** The colour says what it is on: cyan nothing, orange a movable object, red one the phone holds. */
  look: 'miss' | 'target' | 'blocked';
}

const RAY_COLOURS = { miss: 0x30b0c7, target: 0xff9500, blocked: 0xff3b30 } as const;
const REACH_METRES = RAY_REACH_METERS;
/** The card of a piece being made: its size, and how far above the hand it is held. */
const CARD_METRES = 0.14;
const CARD_ABOVE_HAND = 0.1;
/** Palette previews fit a cube this size; the held piece's label is this wide, this far above it. */
const PREVIEW_METRES = 0.05;
const LABEL_WIDTH = 0.18;
const LABEL_ABOVE = 0.03;
/** The wrist menu's slider stops and its buttons (#204): this wide, a third as tall; its line of text this wide. */
const STOP_METRES = 0.06;
const WRIST_BUTTON_METRES = 0.07;
const WRIST_LINE_METRES = 0.22;
/** The label of a piece being resized (#202): this wide, this far above its top. */
const RESIZE_LABEL_WIDTH = 0.24;
const RESIZE_LABEL_ABOVE = 0.06;
const ROOM_BACKGROUND = new THREE.Color('#f5f5f7');

/**
 * The live room in the headset's IWSDK scene: the prepared room's objects and its splat, the
 * phone user's marker, and the rays. Like the phone page's `DiagnosticScene`, but drawing into
 * IWSDK's scene and renderer, and only what the headset needs.
 */
export class QuestRoom {
  /** Holds the room in room metres; turned and moved by the headset's alignment. */
  readonly anchor = new THREE.Group();
  /** Draws the aligned room smaller, turned and moved as the dollhouse (#180); life size by default. */
  private readonly dollhouse = new THREE.Group();
  private readonly loader = new GLTFLoader();
  /** Every catalogue model, loaded once for the room and the palette alike. */
  private readonly models = new ModelCopies(this.loader);
  private readonly late = new LateEntities(this.models);
  private readonly phone: THREE.Group;
  private readonly highlight = new THREE.BoxHelper(new THREE.Object3D(), 0xffcc00);
  private readonly control = new THREE.BoxHelper(new THREE.Object3D(), 0xff9500);
  private readonly rays: THREE.Mesh[] = [];
  /** The picture of a piece being made (#186), held in the hand. */
  private readonly card = new THREE.Mesh(
    new THREE.PlaneGeometry(CARD_METRES, CARD_METRES),
    new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }),
  );
  private cardUrl: string | null = null;
  /** The wrist menu above the left hand (#204), its catalogue previews, and the piece taken from it (#184). */
  private readonly palette = new THREE.Group();
  private readonly previews = new Map<string, THREE.Object3D>();
  /** The slider's stops, each drawn chosen or not. */
  private readonly stops = WRIST_PAGES.map(page => ({
    on: buttonSprite(PAGE_NAMES[page], '#2f6fc6', `wrist:stop:${page}`, STOP_METRES),
    off: buttonSprite(PAGE_NAMES[page], '#5b6472', `wrist:stop:${page}:off`, STOP_METRES),
  }));
  /** Each button, and the other face some have: Listening while speaking, Stop while making. */
  private readonly wristButtons: Record<WristButton, { idle: THREE.Sprite; busy: THREE.Sprite | null }> = {
    speak: {
      idle: buttonSprite('Hold to speak', '#2f8f5f', 'wrist:speak', WRIST_BUTTON_METRES),
      busy: buttonSprite('Listening…', '#c62f2f', 'wrist:speak:busy', WRIST_BUTTON_METRES),
    },
    make: {
      idle: buttonSprite('Make it', '#2f6fc6', 'wrist:make', WRIST_BUTTON_METRES),
      busy: buttonSprite('Stop', '#c62f2f', 'wrist:make:busy', WRIST_BUTTON_METRES),
    },
    move: { idle: buttonSprite('Move', '#2f6fc6', 'wrist:move', WRIST_BUTTON_METRES), busy: null },
    resize: { idle: buttonSprite('Resize', '#2f8f5f', 'wrist:resize', WRIST_BUTTON_METRES), busy: null },
    exit: { idle: buttonSprite('Exit VR', '#c62f2f', 'wrist:exit', WRIST_BUTTON_METRES), busy: null },
  };
  private readonly wristLine = textSprite('');
  private wristText = '';
  /** The piece being resized, drawn at its new scale until Python says so, and its size label. */
  private resizing: { id: string; scale: number } | null = null;
  private readonly resizeLabel = textSprite('');
  private resizeText = '';
  private held: { id: string; root: THREE.Group; label: THREE.Sprite; height: number } | null = null;
  /** The phone user's latest presence, and the dollhouse view the figure is drawn in (#182). */
  private presence: PresenceState | undefined = undefined;
  private view: DollhouseView = LIFE_SIZE;
  private roomGroup: THREE.Group | null = null;
  private splat: SplatMesh | null = null;
  private sparkReady: Promise<typeof import('@sparkjsdev/spark')> | null = null;
  private entityRoots = new Map<string, THREE.Object3D>();
  private loadedVersion: number | null = null;
  private loadingVersion: number | null = null;
  private loadToken = 0;
  private presenting = false;
  /** Whether the VR reference space's y = 0 is the real floor (#207). */
  private onFloor = false;
  private alignment: AlignmentState = { status: 'not_aligned', yaw: 0, origin: { x: 0, y: 0, z: 0 } };
  private predicted: { id: string; position: THREE.Vector3 } | null = null;
  /** An object the phone holds glides to each placement Python sends, over about this long. */
  private readonly glideMs = 120;
  private gliding: { id: string; target: THREE.Vector3 } | null = null;
  /** Hazards in the room (#230), played on the server's clock, which each state sets this one by. */
  private readonly hazards: HazardFrames;
  private readonly clock = new ServerClock();
  private hazardRoom: HazardRoom | null = null;

  constructor(
    private readonly scene: THREE.Scene,
    private readonly renderer: THREE.WebGLRenderer,
    private readonly container: HTMLElement,
  ) {
    this.hazards = new HazardFrames(() => this.loadSpark(), container);
    this.anchor.name = 'room-anchor';
    this.dollhouse.name = 'dollhouse';
    this.dollhouse.add(this.anchor);
    scene.add(this.dollhouse);
    scene.background = ROOM_BACKGROUND;
    scene.add(new THREE.HemisphereLight(0xdff7ff, 0x344156, 2));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 4, 1);
    scene.add(light);
    this.phone = person(0x30b0c7);
    // In the scene, not the anchor: `residentFigure` places it, also in a dollhouse (#182).
    scene.add(this.phone);
    this.highlight.visible = false;
    this.control.visible = false;
    scene.add(this.highlight, this.control);
    this.card.name = 'piece-card';
    this.card.visible = false;
    scene.add(this.card);
    this.palette.name = 'palette';
    this.palette.visible = false;
    for (const stop of this.stops) this.palette.add(stop.on, stop.off);
    for (const { idle, busy } of Object.values(this.wristButtons)) this.palette.add(idle, ...(busy ? [busy] : []));
    this.wristLine.name = 'wrist:line';
    this.wristLine.scale.set(WRIST_LINE_METRES, WRIST_LINE_METRES / 6, 1);
    this.palette.add(this.wristLine);
    scene.add(this.palette);
    this.resizeLabel.name = 'resize-label';
    this.resizeLabel.visible = false;
    this.resizeLabel.scale.set(RESIZE_LABEL_WIDTH, RESIZE_LABEL_WIDTH / 6, 1);
    scene.add(this.resizeLabel);
    this.container.dataset.scale = scaleLabel(this.view.scale);
    this.align(this.alignment);
  }

  /** Draws the phone user where Python last placed them; faded while their tracking is stale. */
  showPhone(presence: PresenceState | undefined): void {
    this.presence = presence;
    this.drawPhone();
  }

  /** Puts the phone user's figure where they stand, in the room or the dollhouse (#182). */
  private drawPhone(): void {
    const anchor = { yaw: this.anchor.rotation.y, offset: this.anchor.position };
    const figure = residentFigure(this.presence, this.view, anchor);
    this.phone.visible = figure !== null;
    this.container.dataset.phoneShown = String(figure !== null);
    if (!figure) return;
    this.phone.position.set(figure.position.x, figure.position.y, figure.position.z);
    this.phone.rotation.y = figure.heading;
    this.phone.scale.setScalar(figure.height / FIGURE_METRES);
    this.container.dataset.phoneHeight = figure.height.toFixed(3);
    this.phone.traverse(child => {
      const material = (child as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
      if (!material) return;
      material.transparent = true;
      material.opacity = figure.opacity;
    });
  }

  /**
   * Puts the room where the headset's alignment says it is; before alignment, the floor under the
   * eyes: on the real floor when the reference space has one (`onFloor`, #207), else standing eye
   * height below them.
   */
  setPresenting(active: boolean, onFloor = false): void {
    this.presenting = active;
    this.onFloor = onFloor;
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
      // below; `local-floor` has the real floor at y = 0 (#207). On the page the preview camera
      // stands on the room's own floor.
      this.anchor.position.set(0, this.presenting && !this.onFloor ? -STANDING_EYE_HEIGHT : 0, 0);
    }
    this.container.dataset.view = alignment.status === 'aligned' ? 'calibrated' : 'overview';
    this.drawPhone();
  }

  /**
   * The picture a new piece is being made from (#186), as a card in the hand while its 3D piece
   * is made; null takes it away.
   */
  showCard(url: string | null): void {
    if (url === this.cardUrl) return;
    this.cardUrl = url;
    const material = this.card.material as THREE.MeshBasicMaterial;
    material.map?.dispose();
    material.map = null;
    material.needsUpdate = true;
    this.card.visible = false;
    this.container.dataset.card = url ? 'shown' : '';
    if (!url) return;
    new THREE.TextureLoader().load(url, texture => {
      if (this.cardUrl !== url) {
        texture.dispose();
        return;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      material.map = texture;
      material.needsUpdate = true;
    });
  }

  /** Holds the card just above `hand`, facing `head`, in the `local` space; hidden without either. */
  placeCard(hand: Position | null, head: Position | null): void {
    this.card.visible = this.cardUrl !== null && hand !== null && head !== null;
    if (!this.card.visible || !hand || !head) return;
    this.card.position.set(hand.x, hand.y + CARD_ABOVE_HAND, hand.z);
    this.card.lookAt(head.x, head.y, head.z);
  }

  /**
   * The wrist menu (#204), or null to hide it: the slider's stops with its page chosen, the
   * page's line of text, and its catalogue pieces (#184), each fitting a 5 cm cube, or its buttons.
   * `busy` turns Hold to speak into Listening and Make it into Stop.
   */
  showWristMenu(
    items: readonly CatalogueItem[],
    menu: WristMenu | null,
    line = '',
    busy: { speaking: boolean; making: boolean } = { speaking: false, making: false },
  ): void {
    this.palette.visible = menu !== null;
    this.container.dataset.palette = menu ? menu.page : '';
    if (!menu) return;
    WRIST_PAGES.forEach((page, index) => {
      const { on, off } = this.stops[index];
      const at = menu.stops[index];
      on.position.set(at.x, at.y, at.z);
      off.position.set(at.x, at.y, at.z);
      on.visible = page === menu.page;
      off.visible = page !== menu.page;
    });
    if (line !== this.wristText) {
      this.wristText = line;
      drawText(this.wristLine, line);
    }
    this.wristLine.visible = line !== '';
    this.wristLine.position.set(menu.line.x, menu.line.y, menu.line.z);
    for (const [name, { idle, busy: other }] of Object.entries(this.wristButtons) as [WristButton, { idle: THREE.Sprite; busy: THREE.Sprite | null }][]) {
      const at = menu.buttons[name];
      const showBusy = other !== null && (name === 'speak' ? busy.speaking : name === 'make' && busy.making);
      idle.visible = at !== undefined && !showBusy;
      if (other) other.visible = at !== undefined && showBusy;
      if (at) {
        idle.position.set(at.x, at.y, at.z);
        other?.position.set(at.x, at.y, at.z);
      }
    }
    const slots = menu.pieces;
    // A piece no longer in the catalogue leaves the palette.
    const listed = new Set(items.map(item => item.id));
    for (const [id, preview] of this.previews) {
      if (listed.has(id)) continue;
      preview.removeFromParent();
      this.previews.delete(id);
    }
    items.forEach((item, index) => {
      let preview = this.previews.get(item.id);
      if (!preview) {
        const holder = new THREE.Group();
        holder.name = `palette:${item.id}`;
        this.palette.add(holder);
        this.previews.set(item.id, holder);
        preview = holder;
        const { width, height, depth } = item.size;
        const fit = PREVIEW_METRES / Math.max(width, height, depth);
        void this.models.copy(item.model_url, item.node).then(model => {
          if (!model) return;
          model.scale.setScalar(fit);
          // The model's origin is its bottom face; the preview is centred on its slot.
          model.position.y = -height * fit / 2;
          holder.add(model);
        });
      }
      const slot = slots[index];
      preview.visible = slot !== undefined;
      if (slot) preview.position.set(slot.x, slot.y, slot.z);
    });
  }

  /**
   * The piece taken from the palette, at the dollhouse's `scale`, at a fingertip and turned with
   * the hand, with its true size above it (#184); null puts it away.
   */
  showHeld(item: CatalogueItem | null, at: { position: Position; yaw: number } | null, scale: number): void {
    if (!item || !at) {
      this.dropHeld();
      this.held = null;
      this.container.dataset.held = '';
      return;
    }
    if (this.held?.id !== item.id) {
      this.dropHeld();
      const root = new THREE.Group();
      root.name = `held:${item.id}`;
      const { width, depth, height } = item.size;
      const label = textSprite(`${item.name} · ${width} × ${depth} × ${height} m`);
      root.add(label);
      void this.models.copy(item.model_url, item.node).then(model => {
        if (model && this.held?.root === root) root.add(model);
      });
      this.scene.add(root);
      this.held = { id: item.id, root, label, height };
      this.container.dataset.held = item.id;
    }
    const { root, label, height } = this.held!;
    root.position.set(at.position.x, at.position.y, at.position.z);
    root.rotation.y = at.yaw;
    root.scale.setScalar(scale);
    // The label keeps its size, just above the piece.
    label.scale.set(LABEL_WIDTH / scale, LABEL_WIDTH / 6 / scale, 1);
    label.position.set(0, height + LABEL_ABOVE / scale, 0);
  }

  /** The top centre of a drawn piece, in the `local` space, or null if it isn't drawn. */
  pieceTop(id: string): Position | null {
    const root = this.entityRoots.get(id);
    if (!root) return null;
    const box = new THREE.Box3().setFromObject(root);
    if (box.isEmpty()) return null;
    const centre = box.getCenter(new THREE.Vector3());
    return { x: centre.x, y: box.max.y, z: centre.z };
  }

  /**
   * Draws the piece being resized at `scale` with its true size, `text`, above it (#202), whatever
   * Python last said, until it is called with a null id.
   */
  showResize(id: string | null, scale = 1, text = ''): void {
    this.container.dataset.resizing = id ?? '';
    this.resizeLabel.visible = id !== null;
    if (!id) {
      this.resizing = null;
      return;
    }
    if (text !== this.resizeText) {
      this.resizeText = text;
      drawText(this.resizeLabel, text);
    }
    this.resizing = { id, scale };
    this.applyResize();
  }

  /** The piece being resized at its new scale, its label above it. */
  private applyResize(): void {
    if (!this.resizing) return;
    const root = this.entityRoots.get(this.resizing.id);
    if (!root) return;
    root.scale.setScalar(this.resizing.scale);
    const top = this.pieceTop(this.resizing.id);
    this.resizeLabel.visible = top !== null;
    if (top) this.resizeLabel.position.set(top.x, top.y + RESIZE_LABEL_ABOVE, top.z);
  }

  /** Takes the held piece out of the scene and frees its label's texture. */
  private dropHeld(): void {
    if (!this.held) return;
    this.held.root.removeFromParent();
    const material = this.held.label.material;
    material.map?.dispose();
    material.dispose();
  }

  /** Draws the aligned room as the dollhouse `view` says: life size, or smaller in front of the person. */
  setDollhouse(view: DollhouseView): void {
    // Called every frame: nothing to do for the view already drawn.
    const now = this.view;
    if (view.scale === now.scale && view.yaw === now.yaw &&
      view.offset.x === now.offset.x && view.offset.y === now.offset.y && view.offset.z === now.offset.z) return;
    this.dollhouse.position.set(view.offset.x, view.offset.y, view.offset.z);
    this.dollhouse.rotation.y = view.yaw;
    this.dollhouse.scale.setScalar(view.scale);
    // Outlines are measured from world matrices now, not at the next render.
    this.dollhouse.updateMatrixWorld(true);
    this.container.dataset.scale = scaleLabel(view.scale);
    this.view = view;
    this.drawPhone();
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
    this.hazards.tick(this.clock.now(Date.now()));
    const root = this.gliding ? this.entityRoots.get(this.gliding.id) : undefined;
    if (!this.gliding || !root) return;
    root.position.lerp(this.gliding.target, 1 - Math.exp(-ms / this.glideMs));
  }

  /**
   * Loads a new room version, or places the objects of the one loaded. Resolves with the version
   * and whether it was just loaded, so the page tells Python once.
   */
  async sync(state: SessionState): Promise<{ version: number; loaded: boolean } | null> {
    if (state.server_time_ms !== undefined) this.clock.sample(state.server_time_ms, Date.now());
    const result = await this.syncRoom(state);
    if (this.hazardRoom) this.hazardRoom.entities = state.room.entities;
    this.hazards.sync(state.room.hazards ?? [], this.hazardRoom);
    return result;
  }

  private async syncRoom(state: SessionState): Promise<{ version: number; loaded: boolean } | null> {
    const room = state.room;
    if (!room.available || room.room_version === null) {
      this.clear();
      if (room.error) throw new Error(room.error);
      return null;
    }
    if (this.loadedVersion === room.room_version) {
      const glidingFrom = this.gliding ? this.entityRoots.get(this.gliding.id)?.position.clone() : undefined;
      this.drawLate(room.entities);
      applyPlacement(this.entityRoots, room.entities);
      // A piece being resized stays at the hands' scale, not the last one Python was sent.
      this.applyResize();
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
      // Every asset loads before any shows, so a failure never leaves half a room. Placed
      // furniture is drawn by `late` once the room shows: several pieces can share one model.
      const own = roomOwn(room.entities);
      const urls = [...new Set(own.map(entity => entity.asset_url))];
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
      const roots = placeEntities(new Map(scenes), own);
      if (splat && room.splat_placement) {
        const { position, rotation, scale } = room.splat_placement;
        splat.position.set(position.x, position.y, position.z);
        splat.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
        splat.scale.setScalar(scale);
      }
      this.attach(roots, splat, room);
      this.drawLate(room.entities);
      this.loadedVersion = version;
      return { version, loaded: true };
    } catch (error) {
      if (token === this.loadToken) this.clear();
      throw error;
    } finally {
      if (token === this.loadToken) this.loadingVersion = null;
    }
  }

  /** Draws furniture placed since the room loaded (#181), and takes away what is gone. */
  private drawLate(entities: readonly RoomEntity[]): void {
    if (!this.roomGroup) return;
    this.late.sync(entities, this.entityRoots, this.roomGroup, furniture => {
      this.container.dataset.furniture = String(furniture);
    });
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
    this.anchor.add(group);
    this.roomGroup = group;
    this.splat = splat;
    this.entityRoots = roots;
    this.hazardRoom = { group, splat, entities: room.entities, roots };
    this.container.dataset.roomVersion = String(room.room_version);
    // Shown only once the splat is really in this scene: a second copy of three.js would refuse it.
    this.container.dataset.splat = splat && splat.parent === group ? 'shown' : '';
  }

  private clear(): void {
    this.loadToken += 1;
    this.loadedVersion = null;
    this.loadingVersion = null;
    this.hazards.clear();
    this.hazardRoom = null;
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

  /** Spark, loaded the first time it is needed, with its renderer added to the scene. */
  private loadSpark(): Promise<typeof import('@sparkjsdev/spark')> {
    this.sparkReady ??= import('@sparkjsdev/spark').then(spark => {
      this.scene.add(new spark.SparkRenderer({ renderer: this.renderer }));
      return spark;
    });
    return this.sparkReady;
  }

  /** Downloads a room splat, loading Spark the first time one is needed. */
  private async loadSplat(url: string): Promise<SplatMesh> {
    const failed = new Error(`The prepared room splat ${fileName(url)} could not be loaded.`);
    try {
      const [spark, response] = await Promise.all([this.loadSpark(), fetch(url)]);
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

/** A button in the headset: white `text` on a rounded `colour`, `width` metres wide (#200, #202). */
function buttonSprite(text: string, colour: string, name: string, width: number): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 384;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (context) {
    context.fillStyle = colour;
    context.beginPath();
    context.roundRect(4, 4, canvas.width - 8, canvas.height - 8, 56);
    context.fill();
    context.fillStyle = '#ffffff';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    // Longer words, as Hold to speak, are drawn smaller to fit the button (#204).
    let size = 64;
    context.font = `700 ${size}px sans-serif`;
    while (size > 32 && context.measureText(text).width > canvas.width - 48) {
      size -= 2;
      context.font = `700 ${size}px sans-serif`;
    }
    context.fillText(text, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.name = name;
  sprite.scale.set(width, width / 3, 1);
  sprite.renderOrder = 10;
  return sprite;
}

/** A line of text as a sprite, one unit wide and a sixth tall before scaling. */
function textSprite(text: string): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 768;
  canvas.height = 128;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.renderOrder = 10;
  drawText(sprite, text);
  return sprite;
}

/** Draws `text` on a text sprite's own canvas, in place of what it said. */
function drawText(sprite: THREE.Sprite, text: string): void {
  const texture = sprite.material.map as THREE.CanvasTexture | null;
  const canvas = texture?.image as HTMLCanvasElement | undefined;
  const context = canvas?.getContext('2d');
  if (texture && canvas && context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#08111ee8';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#ffffff';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    let size = 52;
    context.font = `700 ${size}px sans-serif`;
    while (size > 22 && context.measureText(text).width > canvas.width - 40) {
      size -= 2;
      context.font = `700 ${size}px sans-serif`;
    }
    context.fillText(text, canvas.width / 2, canvas.height / 2);
    texture.needsUpdate = true;
  }
}
