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
