/**
 * Hazards drawn on the headset (#230, part of #221): each hazard's 4D frames, a Spark splat per
 * frame, shown one at a time like a flip-book, and the real object they replace hidden.
 *
 * The frames go in the room group, in room metres, so the dollhouse (#180) shows them too, small,
 * on the same frame as at life size. The real object is hidden with Spark's splat editing: a box
 * of the room splat's splats made invisible, edited live, with no room rewritten. A room without a
 * splat hides the object's model instead.
 */
import type { SplatMesh } from '@sparkjsdev/spark';
import * as THREE from 'three';
import { frameAt, frameUrl, hazardsLabel, hideBox, type SessionHazard } from '../hazard-playback';
import type { RoomEntity } from '../protocol';

type Spark = typeof import('@sparkjsdev/spark');

/** The room the hazards are drawn in: its group in room metres, its splat, and its objects. */
export interface HazardRoom {
  group: THREE.Group;
  splat: SplatMesh | null;
  entities: readonly RoomEntity[];
  roots: ReadonlyMap<string, THREE.Object3D>;
}

interface Drawn {
  hazard: SessionHazard;
  /** The frames, placed: scaled, turned and moved as the hazard's placement says. */
  group: THREE.Group;
  meshes: SplatMesh[];
  ready: boolean;
  frame: number;
  /** What hides the real object: a splat edit and its box, or a model made invisible. */
  hiding: { edit: THREE.Object3D; box: THREE.Object3D } | { root: THREE.Object3D } | null;
  /** Set when the hazard is taken away while its frames are still loading. */
  gone: boolean;
}

export class HazardFrames {
  private readonly drawn = new Map<string, Drawn>();
  private room: HazardRoom | null = null;
  private label = '';

  constructor(
    /** Spark, loaded the first time it is needed, with its renderer in the scene. */
    private readonly spark: () => Promise<Spark>,
    private readonly container: HTMLElement,
  ) {}

  /** The hazards in the session now: new ones start loading, gone ones are taken away. */
  sync(hazards: readonly SessionHazard[], room: HazardRoom | null): void {
    if (room !== this.room) {
      this.clear();
      this.room = room;
    }
    if (!room) return;
    const wanted = new Map(hazards.map(hazard => [hazard.id, hazard]));
    for (const [id, drawn] of this.drawn) {
      if (!wanted.has(id)) this.remove(id, drawn);
    }
    for (const hazard of hazards) {
      const drawn = this.drawn.get(hazard.id);
      if (drawn) drawn.hazard = hazard;
      else if (hazard.placement) this.add(hazard, room);
    }
    this.showLabel();
  }

  /** Shows each hazard's frame for this moment on the server's clock. */
  tick(serverMs: number): void {
    for (const drawn of this.drawn.values()) {
      if (!drawn.ready) continue;
      const frame = Math.min(frameAt(drawn.hazard, serverMs), drawn.meshes.length - 1);
      if (frame === drawn.frame) continue;
      drawn.meshes[drawn.frame].visible = false;
      drawn.meshes[frame].visible = true;
      drawn.frame = frame;
    }
    this.showLabel();
  }

  /** Takes every hazard away, as when the room changes. */
  clear(): void {
    for (const [id, drawn] of this.drawn) this.remove(id, drawn);
    this.room = null;
    this.showLabel();
  }

  private add(hazard: SessionHazard, room: HazardRoom): void {
    const placement = hazard.placement!;
    const group = new THREE.Group();
    group.name = `hazard:${hazard.id}`;
    group.position.set(...placement.position);
    group.rotation.y = placement.turn;
    group.scale.setScalar(placement.scale);
    const drawn: Drawn = { hazard, group, meshes: [], ready: false, frame: 0, hiding: null, gone: false };
    this.drawn.set(hazard.id, drawn);
    void this.load(drawn, room);
  }

  /** Every frame loads before the hazard shows; then its first frame replaces the real object. */
  private async load(drawn: Drawn, room: HazardRoom): Promise<void> {
    const { hazard } = drawn;
    try {
      const spark = await this.spark();
      const meshes = await Promise.all(Array.from({ length: hazard.frames }, async (_, n) => {
        const response = await fetch(frameUrl(hazard, n));
        if (!response.ok) throw new Error(`Frame ${n} of hazard ${hazard.id} could not be loaded.`);
        const mesh = new spark.SplatMesh({ fileBytes: await response.arrayBuffer(), fileName: `${n}.spz`, raycastable: false });
        await mesh.initialized;
        return mesh;
      }));
      if (drawn.gone || this.room !== room) {
        for (const mesh of meshes) mesh.dispose();
        return;
      }
      for (const mesh of meshes) {
        mesh.visible = false;
        drawn.group.add(mesh);
      }
      drawn.meshes = meshes;
      meshes[0].visible = true;
      room.group.add(drawn.group);
      drawn.hiding = this.hide(spark, room, hazard.hide);
      drawn.ready = true;
    } catch (error) {
      console.warn(error instanceof Error ? error.message : error);
    }
    this.showLabel();
  }

  /** Hides the real object: its splats made invisible by a box edit, or its model if no splat. */
  private hide(spark: Spark, room: HazardRoom, id: string | null): Drawn['hiding'] {
    const box = hideBox(room.entities, id);
    if (!box || !id) return null;
    if (!room.splat) {
      const root = room.roots.get(id);
      if (!root) return null;
      root.visible = false;
      return { root };
    }
    // The box is in the room group, in room metres, so it shrinks and turns with the dollhouse.
    // Spark sizes a box by its scale: half its width, height and depth.
    const sdf = new spark.SplatEditSdf({ type: spark.SplatEditSdfType.BOX, opacity: 0 });
    sdf.position.set(box.centre.x, box.centre.y, box.centre.z);
    sdf.rotation.y = box.yaw;
    sdf.scale.set(box.half.x, box.half.y, box.half.z);
    room.group.add(sdf);
    // A child of the room's splat, so it edits that splat only, not the hazard's frames.
    const edit = new spark.SplatEdit({ rgbaBlendMode: spark.SplatEditRgbaBlendMode.MULTIPLY, sdfs: [sdf], softEdge: 0.02 });
    room.splat.add(edit);
    return { edit, box: sdf };
  }

  private remove(id: string, drawn: Drawn): void {
    drawn.gone = true;
    drawn.group.removeFromParent();
    for (const mesh of drawn.meshes) mesh.dispose();
    const hiding = drawn.hiding;
    if (hiding && 'edit' in hiding) {
      hiding.edit.removeFromParent();
      hiding.box.removeFromParent();
    } else if (hiding) {
      hiding.root.visible = true;
    }
    this.drawn.delete(id);
  }

  private showLabel(): void {
    const label = hazardsLabel([...this.drawn.values()].map(drawn => ({ id: drawn.hazard.id, ready: drawn.ready, frame: drawn.frame })));
    const hidden = [...this.drawn.values()].filter(drawn => drawn.hiding).map(drawn => drawn.hazard.hide).join(',');
    if (label === this.label && hidden === (this.container.dataset.hazardHidden ?? '')) return;
    this.label = label;
    this.container.dataset.hazards = label;
    this.container.dataset.hazardHidden = hidden;
  }
}
