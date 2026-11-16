import * as THREE from 'three';
import type { RoomEntity } from './protocol';

/**
 * Give each entity its own placement root holding its node from the loaded asset scenes.
 *
 * The node's own transform and its ancestors' are placement, which the manifest owns, so they are
 * dropped here and the root applies the manifest position and rotation once. Transforms below the
 * node belong to the asset and are kept.
 */
export function placeEntities(
  assets: ReadonlyMap<string, THREE.Object3D>,
  entities: readonly RoomEntity[],
): Map<string, THREE.Object3D> {
  // Resolve every node before detaching any, so a missing one leaves the assets untouched.
  const nodes = entities.map(entity => {
    const node = assets.get(entity.asset_url)?.getObjectByName(entity.node);
    if (!node) throw new Error(`The prepared room model is missing ${entity.id}.`);
    return node;
  });
  const roots = new Map<string, THREE.Object3D>();
  entities.forEach((entity, index) => {
    const node = nodes[index];
    node.removeFromParent();
    node.position.set(0, 0, 0);
    node.quaternion.identity();
    node.scale.set(1, 1, 1);
    node.userData.entityId = entity.id;
    const root = new THREE.Group();
    root.name = `entity:${entity.id}`;
    root.add(node);
    roots.set(entity.id, root);
  });
  applyPlacement(roots, entities);
  return roots;
}

/** The room's own objects: everything but placed furniture, which `LateEntities` draws (#181). */
export function roomOwn(entities: readonly RoomEntity[]): RoomEntity[] {
  return entities.filter(entity => !entity.furniture);
}

/** Loads models, each asset once, for anything that needs a copy of one of its nodes. */
interface ModelLoader { loadAsync(url: string): Promise<{ scene: THREE.Object3D }> }

/**
 * Draws entities that arrive after their room loaded, such as placed furniture (#181), and takes
 * away those that are gone. Each new entity gets its own copy of its node; each asset loads once.
 */
export class LateEntities {
  private readonly loading = new Set<string>();
  /** Entities whose model couldn't be drawn: tried again only with the next room. */
  private readonly failed = new Set<string>();
  /** The roots of the room drawn now; a model arriving for an earlier room is dropped. */
  private current: Map<string, THREE.Object3D> | null = null;
  private latest: readonly RoomEntity[] = [];

  constructor(private readonly models: ModelCopies) {}

  /**
   * Brings `roots`, and the drawn `group` that holds them, in line with `entities`: new ones are
   * added once their model has loaded, gone ones go at once. `changed` is called after either,
   * with how many placed pieces of furniture are drawn now.
   */
  sync(
    entities: readonly RoomEntity[],
    roots: Map<string, THREE.Object3D>,
    group: THREE.Object3D,
    changed: (furniture: number) => void,
  ): void {
    if (this.current !== roots) {
      this.loading.clear();
      this.failed.clear();
    }
    this.current = roots;
    this.latest = entities;
    const drawn = () => this.latest.filter(entity => entity.furniture && roots.has(entity.id)).length;
    const listed = new Set(entities.map(entity => entity.id));
    let removed = false;
    for (const [id, root] of roots) {
      if (listed.has(id)) continue;
      root.removeFromParent();
      roots.delete(id);
      removed = true;
    }
    if (removed) changed(drawn());
    for (const entity of entities) {
      if (roots.has(entity.id) || this.loading.has(entity.id) || this.failed.has(entity.id)) continue;
      this.loading.add(entity.id);
      void this.copy(entity).then(root => {
        if (this.current !== roots) return;
        this.loading.delete(entity.id);
        if (!root) {
          this.failed.add(entity.id);
          return;
        }
        if (roots.has(entity.id) || !this.latest.some(listed => listed.id === entity.id)) return;
        roots.set(entity.id, root);
        group.add(root);
        // Placed where it is now, which may have moved while its model loaded.
        applyPlacement(roots, this.latest);
        changed(drawn());
      });
    }
  }

  /** A placed copy of the entity's node, or null if its model can't be drawn. */
  private async copy(entity: RoomEntity): Promise<THREE.Object3D | null> {
    const node = await this.models.copy(entity.asset_url, entity.node);
    if (!node) return null;
    const roots = placeEntities(new Map([[entity.asset_url, node]]), [{ ...entity, node: node.name }]);
    return roots.get(entity.id) ?? null;
  }
}

/** Copies of nodes from glTF models, each model loaded once (#181, #184). */
export class ModelCopies {
  private readonly assets = new Map<string, Promise<THREE.Object3D>>();

  constructor(private readonly loader: ModelLoader) {}

  /** A fresh copy of the named node, or null if its model or node can't be had. */
  async copy(url: string, node: string): Promise<THREE.Object3D | null> {
    let scene = this.assets.get(url);
    if (!scene) {
      scene = this.loader.loadAsync(url).then(gltf => gltf.scene);
      this.assets.set(url, scene);
      // A failed load may work next time it's asked for.
      scene.catch(() => this.assets.delete(url));
    }
    return (await scene.catch(() => null))?.getObjectByName(node)?.clone(true) ?? null;
  }
}

export function applyPlacement(
  roots: ReadonlyMap<string, THREE.Object3D>,
  entities: readonly RoomEntity[],
): void {
  for (const entity of entities) {
    const root = roots.get(entity.id);
    if (!root) continue;
    root.position.set(entity.position.x, entity.position.y, entity.position.z);
    root.quaternion.set(entity.rotation.x, entity.rotation.y, entity.rotation.z, entity.rotation.w);
  }
}
