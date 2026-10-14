# Escape My Room: AI Interaction Design Notes

Date: 2026-10-12. Exploratory design notes; these do not revise the approved prototype specification or GitHub issues.

The proposed extension is a good fit when AI uses room context to create tasks that require the mobile master and VR user to communicate and act together. Story generation and hidden-object placement provide useful authoring, but collaboration needs explicit rules about what each participant can see and do.

## What the scene should know

Three layers should remain distinct:

1. **Semantic evidence:** object class, visual description, visible writing, candidate associations, confidence, and source images. A VLM can help produce these.
2. **Spatial representation:** stable entity IDs, room-frame transforms, geometry, selectable proxies, dimensions, and validated placement anchors. Use the prepared scene and reconstruction data as the source of geometry. Compute relations from that geometry where possible.
3. **Virtual capabilities:** which objects can be moved, inspected, activated, used as containers, or reveal a clue, together with permissions and state transitions. These are game features supplied by the implementation or master, rather than abilities guaranteed by recognizing the object.

Recognizing a cabinet does not establish a usable interior or an implemented opening behavior. A generated plan may refer only to capabilities supported by the prototype. A hiding anchor behind or beneath a known object can work without inventing its internal geometry.

## Six relevant primary sources

| Source | Verified finding | Relevance and boundary |
|---|---|---|
| [ImaginateAR, UIST 2025](https://arxiv.org/html/2504.21360v1) | Processes pre-scanned outdoor scenes offline into labelled 3D bounding boxes; language agents plan and assemble virtual content. Users preferred AI assistance with manual refinement. | Strong precedent for the proposed scene understanding → language plan → placement architecture. Its bounding-box abstraction caused floating or clipping on irregular surfaces. It does not demonstrate a browser-based cooperative puzzle game. |
| [SpatialLM, NeurIPS 2025 — official repository](https://github.com/manycore-research/SpatialLM), [model card](https://huggingface.co/manycore-research/SpatialLM1.1-Qwen-0.5B) | Consumes point clouds and produces architectural elements and oriented object boxes with semantic categories. Version 1.1 supports user-selected subsets of its furniture categories. Inputs assume axis-aligned point clouds with Z up. | An optional structured indoor-understanding component for Python. It does not directly turn an arbitrary 2D photograph into exact interactive room objects. The repository's video examples use a separate reconstruction pipeline. Existing WebXR coordinates would need an explicit conversion. |
| [SpatialVLM, CVPR 2024 — author project](https://spatial-vlm.github.io/) | Improves spatial question answering using specially generated spatial training data. The reported quantitative experiment had only 37.2% of estimates within 0.5–2 times the true distance. | Demonstrates useful spatial reasoning, while giving a concrete reason to compute precise positions from scene geometry. These are results for that model and experiment, not a claim that every newer model has the same accuracy. |
| [AssistVR, author preprint](https://arxiv.org/html/2410.21091v1), [SUI 2025 publication record](https://www.repository.cam.ac.uk/items/36ae60a4-6d8b-43e4-93ef-daeb80ed4f27) | Combines speech and raycast selection. Its 24-person study found benefits for multiple-object selection compared with a disocclusion minimap. The preprint implementation uses Azure CLU with constrained intents and entities. | Supports grounding language in an actual selected object or pointing region. It is not evidence that an unconstrained VLM understands arbitrary room instructions or that a multiplayer puzzle will work. |
| [GenEscape, 2025 author preprint](https://arxiv.org/html/2506.21839v1) | Generates 2D escape-room puzzle images using structured scene graphs, solution sequences, and Designer/Player/Examiner/Builder refinement. It evaluates visual solvability, shortcut avoidance, and spatial alignment. | Useful inspiration for separating puzzle logic from presentation and checking shortcuts. Its agents collaborate during generation; it does not establish executable puzzles requiring two human roles. |
| [LayoutVLM, CVPR 2025 — author project](https://cs.stanford.edu/~sunfanyun/layoutvlm/) | A VLM proposes an initial layout and spatial relations among assets and walls; differentiable optimization produces the final placements. | Supports separating semantic intent from geometric placement. For this prototype, validated anchors and simple deterministic constraints can provide a smaller alternative to adopting the full optimization system. It does not establish role-interdependent gameplay. |

No source above proves the complete proposed workflow. The point is to borrow established components and test their combination at prototype scale.

## Recommended first implementation — design proposal

Use a bounded catalogue of two or three puzzle mechanics with AI-assisted room binding and storytelling:

```text
Prepared room + object views + stable entity IDs
    → VLM semantic suggestions, corrected by the master
    → Scene registry with geometry and supported capabilities
    → LLM chooses a puzzle template, room objects, story, and role clues
    → Python validates the structured plan and computes placement
    → Master previews/adjusts the proposal
    → Python commits authoritative puzzle state
    → Mobile and VR clients receive their permitted views and actions
```

Images can be prepared scan views or explicitly captured/uploaded images. This design does not depend on unrestricted camera-pixel access within an immersive WebXR session.

The LLM should return structured fields such as `template_id`, `entity_ids`, `anchor_ids`, `role_clues`, `allowed_actions`, `dependencies`, and `success_condition`. Story text accompanies the plan. Python checks IDs and capabilities, rejects invalid or inaccessible anchors, checks the expected solution path, and attempts that path under each role alone. For small fixed mechanics, exhaustive state traversal can expose solo shortcuts and impossible states. Role-specific capabilities may make some cooperative actions unavailable to either role alone.

Object transforms, ownership, and puzzle success remain deterministic server state. Use the AI when preparing a puzzle or responding to an explicit authoring request; keep phone movement and VR manipulation responsive through the existing state protocol. A plan should reference the room-state revision used to generate it and be checked against current state before applying it.

## Ways to make the AI contribution more interesting — design proposals

| Direction | Example | Why it strengthens interaction |
|---|---|---|
| **Complementary clues and abilities** | The master positions a virtual lens using phone motion. Only the VR user sees the revealed symbol and tells the master how to adjust the lens; the VR user then operates the corresponding virtual lock. | Both users need to communicate about the same spatial state. Merely being present in the same story is insufficient. |
| **Point-and-describe authoring** | The master selects a desk and requests, “Make this the final clue location, and make us use the lamp to get there.” | Selection grounds the request in stable IDs, and the resulting preview makes the AI's interpretation inspectable and editable. |
| **Objects become story roles** | A clock becomes a virtual sequence clue, a book becomes an inspectable message, and a shelf supplies validated placement anchors. | Familiar personal objects motivate spatial exploration. The VLM suggests associations while the game engine supplies the actual actions. |
| **Spatially grounded hints** | The master requests a mild hint; the system proposes a clue attached to the relevant room object, and the master chooses whether to release it. | Hints become part of the shared scene and preserve the master's control. They can be generated from the validated solution graph without repeatedly analyzing camera images. |
| **Repair and remix** | The master changes which object may be moved; AI proposes a new room binding or alternative puzzle template and Python validates it. | The interaction becomes iterative collaboration with AI rather than a single generation button. Start with changes during preparation before exploring live puzzle changes. |

The strongest small demo is **AI-assisted authoring plus one spatial puzzle with complementary information and actions**. It demonstrates why the AI needs room semantics and why the mobile–VR interaction matters. Keep the master as an active facilitator: AI proposes an arrangement, the master previews it and refines it using phone movement, and the VR user inspects the shared result and reports the information needed for the next action. A longer generated story can be added after that mechanism works.

If the mobile participant will now solve alongside the VR user, the earlier “master knows and controls the puzzle” premise needs an explicit design choice: either retain the master as an active facilitator with indispensable actions, or withhold the full solution from the master and issue separate role clues. The second option changes the role model and should be agreed before revising approved tickets.

## Prototype checks — proposed

- Every generated reference resolves to an existing entity and supported virtual action.
- Every placed item uses a valid anchor and remains reachable or inspectable through supported interaction.
- A cooperative completion path exists; removing either role's unique contribution prevents completion for the selected mechanic.
- Participants can understand, discuss, and correct an AI placement proposal in the shared scene.
- Ambiguous references produce candidate highlighting or a clarification rather than an unexplained state change.
- AI failures have a prepared puzzle fallback; continuous manipulation still works without inference.

No model was installed or trained. No approved spec, ticket, GitHub issue, commit, or remote repository was changed by this investigation.
