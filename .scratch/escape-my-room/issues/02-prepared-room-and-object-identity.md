# 02: Load a prepared room and independently selectable objects

**What to build:** Both participants enter the same recognizable prepared room, with matching furniture identities and one independently movable virtual item.

**Blocked by:** 01 — Connect mobile and VR through Python with a tracked pose

**Status:** ready-for-agent

## Proposed technical approach

- Start from an existing room reconstruction exported to a browser-loadable format; GLB/glTF plus a small manifest is the proposed default. Python serves or references assets and validates the room version loaded by each participant.
- The manifest assigns stable entity IDs, initial transforms, meters as scene units, and explicit static/movable/selectable flags. Render-node names alone are not authoritative entity IDs.
- Separate background room visuals from interactive proxies or independently addressable meshes. A single reconstructed mesh does not automatically provide separate furniture, interiors, or movable parts.
- Check scale, origin, axis convention, object bounds, and mesh/material cost on both devices. Use simple furniture proxies where necessary while keeping recognizable room references.

## Acceptance criteria

- [ ] Both clients load the same room version, floor, recognizable desk/cabinet references, and one movable item.
- [ ] Entity IDs and initial room-space transforms match in the Python manifest and both clients.
- [ ] Static furniture and movable content are clearly distinguished in the manifest and rendering.
- [ ] Room loading failures, missing assets, and version mismatches produce clear feedback rather than inconsistent sessions.
- [ ] Demonstrate that the item is independently addressable without moving the background room mesh.
- [ ] Document the asset preparation procedure and device observations, including any geometry simplification.

## Scope boundary

Prepared assets only. Automatic camera scanning, segmentation, model training, and selection-driven reconstruction are outside this ticket.
