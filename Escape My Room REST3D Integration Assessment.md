# REST3D integration assessment for Escape My Room

Research date: 2026-10-14. Scope: the official `ShirleyMaxx/REST3D` master branch and its documented dependencies. This is source inspection, not an installation or hardware benchmark. The application remains guided Chrome capture, Python/FastAPI orchestration on remote GPU infrastructure, and shared mobile-master / Quest 3 WebXR interaction. Capture may contain many photographs; that requirement is not reduced to one photograph.

## Assessment

REST3D is a strong candidate for an object-first scene-construction worker and a reference for reasoning about support relationships. It is not a complete browser VR application or a native multi-view reconstruction pipeline. Reuse its independent-object construction, support tree, and preparation-time stabilization; adapt its outputs into our own scene manifest and retain our existing WebXR interaction architecture.

The inspected release has three command-line stages: VLM-assisted scene-tree inference and segmentation, SAM 3D Objects reconstruction/canonicalization, and Isaac Gym stabilization. The final folders hold separate objects and an optional fitted-wall variant. [Repository overview](https://github.com/ShirleyMaxx/REST3D/blob/master/README.md), [stage-one/two runner](https://github.com/ShirleyMaxx/REST3D/blob/master/1_infer_scenecanon.sh), [stabilization runner](https://github.com/ShirleyMaxx/REST3D/blob/master/2_stable_scene.sh).

## What the released code actually provides

| Component | Verified implementation | How we would use or adapt it |
|---|---|---|
| Visual object grounding | SAM 3 segmentation agent, with VLM-assisted object listing and grounding. | Import as a worker; add master confirmation and stable object IDs before publishing a scene. |
| Support semantics | `scene_tree.json` records structural roots, object nodes, and edges with `child`, `parent`, `relation`, and `type`. | Supply spatial context to puzzle planning and maintain relationships after objects move. |
| Individual geometry | SAM 3D Objects is invoked per mask, then per-object meshes and bounds are saved. | Convert separate assets to GLB and simplify them for Quest. |
| Scene stabilization | Cross-entropy search over placement perturbations, with GPU physics checking settling, geometry penetration, and layout preservation. | Preparation-time placement repair; later experiment with validating proposed story placements. |
| Background/walls | Optional postprocessing constructs fitted wall meshes and adjusts wall-attached objects. | Approximate spatial context, not a measured reconstruction of every room boundary. |
| Browser inspection | Viser serves reconstructed meshes and recorded settling states. | Useful debugging/reference viewer; our mobile/Quest interaction needs its own implementation. |
| Articulated interaction | URDF generation creates one rigid base link per object, without drawer/door joints. | Explicit mechanics, part segmentation, and joints remain application work when required. |

Sources: [segmentation/tree stage](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/infer_scenetree.py), [geometry stage](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/infer_scene3d.py), [physics optimizer](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/models/cem_opt.py), [wall processing](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/utils/postprocess.py), [URDF generator](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/utils/urdf.py).

## Scene and asset contracts

### Semantic metadata

The scene tree has roots `floor`, `wall`, `ceiling`, and `floor-wall`. Its VLM prompt distinguishes `on`, `inside`, `attach`, `hang`, and `on-attach`, and labels objects `fixed` or `movable`. Invalid parent names fall back to floor; failures can therefore produce plausible-looking but incorrect relationships. The parser detects support-tree cycles. These are useful initial annotations, not authoritative affordances or a general spatial knowledge graph. [Tree inference](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/infer_scenetree.py), [tree parser and grouping](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/models/scene_layout.py).

A relation such as `inside` does not prove that the reconstructed cabinet has a usable interior or an openable drawer. The generated URDF has one base link with nominal mass and inertia, rather than inferred physical material properties or articulation. [Rigid-object URDF](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/utils/urdf.py).

### Geometry and appearance

The release writes separate OBJ files, not a promised ready-to-use scene GLB. Stage two also saves NPZ bounding-box corners/centers/axes; it produces `scene_raw`, `scene_y_align`, and `scene_canon`, plus URDFs and the copied tree. Image folders are iterated as separate per-image jobs. [Geometry stage](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/infer_scene3d.py).

The reconstruction wrapper explicitly disables texture baking and enables vertex color. Do not describe the released output as UV-textured/PBR GLBs without testing an additional conversion/baking step. The wrapper handles SAM 3D's axis and scale/rotation/translation conventions; other stages align up to +Y. [SAM 3D wrapper](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/models/build_sam3dobj.py).

### Placement and export traps

The optimizer's pose representation is `base_dy` plus per-object `pos`, `rot`, and `lin_vel`; quaternion order is x,y,z,w. Physics uses +Y up and gravity along -Y. The exported meshes have the final transforms baked into their vertices. [Optimizer and pose-export helpers](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/models/cem_opt.py), [quaternion helpers](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/utils/quat.py).

Stage-three replay explicitly loads world-frame OBJ files at identity actor pose. Applying the reported final pose again would double-transform them. Our asset adapter should either recenter each baked mesh and derive a corresponding instance transform, or retain local geometry and explicitly persist its transformation. We must calibrate real-world scale; a numerically consistent simulation does not establish measured phone-capture dimensions. [Replay loader](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/replay_in_simulator.py).

Do not rely on a default fresh run writing `global_scene_poses.json`. The current code passes the best pose dictionary in memory to postprocessing; `save_global_poses_json` accepts an optional filename, while the best-result call supplies none. Optional mean-result persistence is disabled by default, and postprocessing receives `out_json_name=None`. We should persist our own explicit manifest at the integration boundary. This is a source-level finding to verify during reproduction, not a claim that pose export is impossible. [Stabilization code](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/stable_scene.py), [default configuration](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/config/stable_scene_cfg.py).

## Browser replay versus VR interaction

The release's documented browser path performs a finite Isaac Gym settling run, records states, destroys the simulator, then offers Viser frame/FPS controls and Play/Pause. It can render/record the settling process, but this path is playback, not live grabbing that feeds back into the simulator. The comment mentioning `vr_demo_render.py` is not sufficient evidence that this VR bridge is supplied. [Replay implementation](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/replay_in_simulator.py).

In the inspected root, `scripts`, `rest3d/models`, `rest3d/utils`, and `third_party` listings, no Quest/WebXR hand-tracking or teleoperation entry point was found. This is an inspected absence rather than proof no such code exists anywhere. The paper's demonstrated VR system must be distinguished from the public reconstruction/replay package. [Scripts](https://github.com/ShirleyMaxx/REST3D/tree/master/scripts), [models](https://github.com/ShirleyMaxx/REST3D/tree/master/rest3d/models), [utilities](https://github.com/ShirleyMaxx/REST3D/tree/master/rest3d/utils), [third-party folder](https://github.com/ShirleyMaxx/REST3D/tree/master/third_party).

For our prototype, exporting assets into Three.js/WebXR and synchronizing object transforms through FastAPI is the first proposed integration. Keeping Isaac Gym as a continuously running remote physics server would additionally require an input/state bridge, collision and ownership policy, latency handling, and deployment work. Neither route has been implemented here.

## Many-photo capture and multi-view adaptation

REST3D itself is single-image reconstruction. A folder input batches separate scenes; it does not fuse views, associate the same object across frames, or register outputs into one room coordinate system. [Per-image loop](https://github.com/ShirleyMaxx/REST3D/blob/master/scripts/infer_scene3d.py).

We can still accept many photographs from the phone. Proposed adaptation steps are:

1. Preserve a shared capture set and choose a clear overview plus the best available view for each selected object.
2. Establish cross-view object identity and camera/scene registration using a separate geometry pipeline.
3. Use REST3D/SAM 3D to initialize independent meshes and support metadata; align each instance using observed geometry, with master corrections where needed.
4. Evaluate later whether a genuine multi-view mesh method should replace SAM 3D while retaining the support-tree and stabilization stages.

The wrapper exposes an optional `pointmap` parameter, which is a promising seam for registered geometry. It is not proof that feeding several views into the released pipeline yields better meshes. Coordinate conventions, visibility, scale, and model expectations need an explicit adapter and validation. [Wrapper interface](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/models/build_sam3dobj.py).

## GPU and hosting feasibility

The authors prescribe two isolated conda environments: reconstruction uses Python 3.11, PyTorch 2.5.1/CUDA 12.1; stabilization uses Python 3.8, PyTorch 2.2.2/CUDA 12.1 and Isaac Gym Preview 4. Installation pins and patches SAM 3 and SAM 3D Objects. Both checkpoint repositories require access approval. [Main installation](https://github.com/ShirleyMaxx/REST3D/blob/master/INSTALL.md), [reconstruction setup](https://github.com/ShirleyMaxx/REST3D/blob/master/environments/install_rest3d.md), [physics setup](https://github.com/ShirleyMaxx/REST3D/blob/master/environments/install_gym.md).

SAM 3D's upstream setup calls for Linux and at least 32 GB NVIDIA GPU memory. A 96 GB GPU meets that capacity baseline, but memory capacity does not prove software compatibility or runtime. [SAM 3D prerequisites](https://github.com/facebookresearch/sam-3d-objects/blob/main/doc/setup.md).

Blackwell is a compatibility task before a performance estimate: PyTorch introduced official Blackwell support with its 2.7/CUDA 12.8 release, newer than REST3D's pinned environments. CUDA extensions and the separate simulator need individual verification. NVIDIA now calls Isaac Gym deprecated and unsupported. Do not promise RTX PRO 6000 Blackwell support or substitute Isaac Lab without a port. [PyTorch release](https://pytorch.org/blog/pytorch-2-7/), [NVIDIA Isaac Gym status](https://developer.nvidia.com/isaac-gym).

Hugging Face Jobs or a GPU server could host the workers, but no official REST3D deployment or Blackwell benchmark was verified. Treat Linux/CUDA environments, simulator binaries, driver/graphics capabilities, checkpoint access, output persistence and timeouts as deployment requirements. FastAPI should dispatch preparation jobs; separate environments need not share its process.

The VLM wrapper defaults to Gemini 3 Flash Preview and includes a GPT-4o backend. Orchestration can eventually substitute a backend, but that does not establish equivalence of segmentation and support reasoning. [VLM interface](https://github.com/ShirleyMaxx/REST3D/blob/master/rest3d/utils/vlm.py).

## Reuse plan owned by the project's orchestration layer

Proposed worker boundary: capture bundle and model configuration in; independent assets, object manifest, support graph, stage logs, cost/time measurements and validation results out. Master corrections belong in a project-owned scene record so future model changes do not erase them.

An LLM should propose bounded symbolic requests such as placing `book_01` on `desk_02`. The project's geometry/placement layer resolves the coordinates, checks collisions and permitted actions, and updates shared state. REST3D's stabilization can be studied as an offline repair/validation component; it is not a released story planner. After movement, update the support graph or mark its relationships stale. No model fine-tuning is required to test this orchestration, although pretrained model inference and scene-specific placement optimization remain necessary.

## Bounded first experiment

1. Inspect a supplied demo's assets and establish the OBJ-to-GLB adapter, preserving independent names, vertex color and orientation. Avoid paying for generation to validate an export contract if example outputs are available.
2. Reproduce one official scene on a Linux NVIDIA machine with compatible environments. Record actual time and peak memory per stage; do not extrapolate a Blackwell speedup.
3. Use a small user capture set containing a support surface and two movable objects. For the REST3D baseline select an overview; retain every other view for association checks and later reconstruction comparisons.
4. Export separate GLBs plus our manifest; verify object scale, pivots, recognizability from several viewpoints, and supported placement before publication.
5. Load the scene in the existing Quest WebXR client. Move one object from the mobile master and verify the synchronized instance moves independently. Test supported placement and a failed placement request.
6. Only then compare multi-view registration and alternative geometry workers, or add backend story planning.

Suggested evaluation: detection/mask correctness; support-edge correctness; distinct object count; view-dependent geometry defects; time/cost/peak memory; correction effort; asset complexity; Quest frame stability; placement validity; object-state consistency across clients. Successful reconstruction alone is insufficient if object IDs, pivots, bounds, or client synchronization fail.

## License and limitations

REST3D identifies its own code as CC BY-NC 4.0 with attribution and noncommercial use; dependencies have their own terms. This is relevant to an academic prototype, while any later commercial reuse requires checking the applicable licenses. [Official license statement](https://github.com/ShirleyMaxx/REST3D/blob/master/README.md).

No software was installed, checkpoints downloaded, GPU jobs submitted, images uploaded, credentials changed, or application code modified for this research. Runtime, final mesh quality, browser compatibility, and deployment remain untested.

## Paper and website cross-check

The supplied [paper](</C:/Users/user/Downloads/Rest3D.pdf>) was extracted and relevant figures, tables and complete sections inspected. The official [online paper](https://arxiv.org/html/2605.30338v1) and [project page](https://shirleymaxx.github.io/REST3D/) were cross-checked. The website HTML and its public demonstration JSON were read on 2026-10-14; no video was downloaded.

### Actual VR demonstration

Section 4.5 and supplementary C.3 describe real-time, 30 FPS interaction using a Meta Quest Pro. Hand tracking is sent to an Isaac Gym server, mapped to simulated Inspire dexterous hands, and the simulated scene is rendered back to the headset. Wrist control uses force/torque actuation; finger motions use IK retargeting, with a proximity-activated spring assisting grips. This is substantive evidence for manipulating reconstructed objects in VR. It does not establish released Quest 3 WebXR multiplayer support or an AR registration pipeline. The website's VR recordings play at 3x speed; the reported underlying loop rate is 30 FPS. [Paper, Sections 4.5/C.3](https://arxiv.org/html/2605.30338v1), [VR demonstration description](https://shirleymaxx.github.io/REST3D/#vr).

### Website viewer is directly relevant to our renderer

The page's inline module imports Three.js 0.170.0, OrbitControls and GLTFLoader. It loads separate `meshes/<actor>.glb` assets and a `simulation.json` containing `actors`, `n_frames`, `fps`, `camera`, and position/quaternion tracks. `applyFrame` assigns saved poses; its animation loop advances a playback frame. This is an object-level browser rendering example, not live browser physics or user-driven object movement. Our proposed frontend can reuse the asset/state separation while replacing replay tracks with authoritative interaction updates. [Inspected page source](https://shirleymaxx.github.io/REST3D/), [inspected Room 1 playback JSON](https://shirleymaxx.github.io/REST3D/assets/custom_room1/ours/simulation.json).

The inspected Room 1 JSON lists 20 named actors and 61 frames. The browser code converts stored quaternion w,x,y,z to Three.js x,y,z,w. This differs from the optimizer's inspected pose-dictionary convention, so an adapter must declare and validate quaternion order at each boundary. The website's existing GLBs demonstrate an export route; they do not establish that the reconstruction CLI directly exports GLB or includes the website's conversion tooling. Reuse of example assets should preserve applicable attribution and data-source terms.

### Measured preparation time

Supplementary Table 4 reports the following on an NVIDIA TITAN RTX. Total time includes API calls and their waiting time; the monetary column is Gemini 3 Flash API cost, not GPU hosting cost. These are paper-reported results, not our benchmark or a prediction for a new capture.

| Stage | Minutes per scene | API cost per scene |
|---|---:|---:|
| Scene-tree construction | 10.6 | $0.22 |
| Geometry initialization/canonicalization | 4.8 | $0.25 |
| Physics-constrained optimization | 10.4 | - |
| Total | 25.8 | $0.47 |

The experiments cover scenes containing 4-30 objects. This supports a minutes-scale baseline rather than the earlier hours-scale discussion of other methods. It does not support multiplying by a theoretical Blackwell speedup: API latency and simulator compatibility remain separate constraints. [Paper, supplementary B/C.1 and Table 4](https://arxiv.org/html/2605.30338v1).

### What spatial awareness supplies and what we add

The paper models a gravity-support hierarchy with ground, wall, ceiling and ground-wall roots; the release uses slightly different labels and additional relation types as documented above. It is useful for choosing a support surface and preserving stable arrangements. It does not supply a complete puzzle ontology: visibility from each user, reachability, hiding volumes, containers, movable restrictions and puzzle roles must be validated or recorded by our project.

Example proposed orchestration: the backend story planner requests `place(book_01, on=desk_02)`. Our geometry layer chooses a valid support pose, checks collisions and gameplay permissions, and commits a scene revision to both clients. The mobile master and VR solver then interact with that shared state. Heavy reconstruction and CEM stabilization run during preparation or explicit scene-edit batches, not on every grab update. This remains a design proposal, not behavior released by REST3D.

The optimizer penalizes deviation from the initial layout. An intentional storyline relocation therefore requires updating the target/reference layout and relevant support edges before re-optimizing; otherwise reconstruction-oriented refinement can oppose the intended change. Support edges must also be updated after gameplay movement. An optimization group is not a permanent transform parent or welded group: placing a vase on a table must not automatically make both inseparable during gameplay. [Paper, Section 3.3](https://arxiv.org/html/2605.30338v1).

### Limits that affect our game

The paper focuses on rigid objects; articulated and deformable objects are future work. Supplementary C.4 and Figure 13 show missed detection of a wall shelf and relocation of wall-supported objects onto the ground. Walls are not explicitly represented as supporting structures during core optimization, so fitted postprocessing walls should not be described as faithful room scanning. The VR demo assigns heuristic masses by semantic category; these are interaction parameters rather than measured physical properties. Therefore master review of identities, support edges, movable flags and placements remains useful before the scene becomes playable. [Paper, Sections 5/C.3/C.4](https://arxiv.org/html/2605.30338v1).

## Final recommendation

Use REST3D as a leading candidate for the object/support/placement portion of the Python GPU pipeline. Preserve the user's many-photo capture and interchangeable-model orchestration. Start with a small single-view REST3D reproduction and an object export/synchronization experiment; evaluate multi-view geometry as a separate provider and measured adapter task. Reproduce the legacy simulator environment before committing to a Blackwell or Hugging Face deployment. Keep the current WebXR client and shared-state design, with backend story planning added after independent-object manipulation works.
