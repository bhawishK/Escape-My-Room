# Escape My Room: related research

Researched 12 October 2026. Based on `Escape My Room Prototype Spec.md`, including the agreed mobile-master authority, remote VR participation, reconstructed personal room, and selection–hold–phone movement–release sequence. The specification has not been changed.

## Main finding

**The basic phone-motion technique already has close precedents.** Grandi and colleagues describe selecting an object, holding a circular button to attach it to the phone pose, moving the phone to translate/rotate the object, and releasing to stop. Their 2018 paper explicitly discusses clutching to reposition the device and repeat manipulation. This is a particularly close baseline for the current proposal. [2017 author paper, §2.2](https://www.artanim.ch/pdf/publications/67.pdf), [2018 author paper, §3.2](https://www.artanim.ch/pdf/publications/86.pdf)

Mobile AR paired with immersive VR is also established: Grandi et al. evaluated that combination for co-located collaborative manipulation. Shared reconstructed physical environments with remote VR participants appear in CoVAR, MCoAVR, Room2XR, and CIDER. Consequently, phone movement, asymmetric devices, reconstructed rooms, or their broad combination should not yet be claimed as the contribution. [2019 author paper](https://pure.itu.dk/ws/files/84411580/2019_IEEEVR_Asymmetric_Collab.pdf), [CoVAR author institution record](https://research.monash.edu/en/publications/covar-mixed-platform-remote-collaborative-augmented-and-virtual-r/), [MCoAVR paper](https://par.nsf.gov/servlets/purl/10185645), [Room2XR author institution record](https://researchoutput.ncku.edu.tw/en/publications/room2xr-virtual-interactive-collaboration-in-real-world-scenes/), [CIDER publisher paper](https://doi.org/10.1145/3796237)

**Interpretation:** the prototype is still worthwhile, but it should reproduce the basic mechanism first and investigate a specific extension. Object-relative placement around personal furniture, understandable exclusive authority, and private manipulation in an asymmetric game are promising questions, not verified research gaps.

## Prioritized papers

### 1. Design and Assessment of a Collaborative 3D Interaction Technique for Handheld Augmented Reality

**Jerônimo G. Grandi, Henrique G. Debarba, Iago Berndt, Luciana Nedel, Anderson Maciel. 2018. IEEE Conference on Virtual Reality and 3D User Interfaces.** DOI: [10.1109/VR.2018.8446295](https://doi.org/10.1109/VR.2018.8446295). [Author PDF](https://www.artanim.ch/pdf/publications/86.pdf).

**Verified:** combines touchscreen gestures and device movement for 7-DOF manipulation; assesses touch, device-motion, and hybrid interaction, followed by collaborative manipulation. Its attachment mode uses press/hold, physical device movement, release, and clutching (§3.2).

**Overlap:** exceptionally close input sequence and repeated engagement. **Difference:** the proposed first experiment uses translation only, one authoritative mobile master, remote VR participation, and personal-room content rather than simultaneous mobile co-manipulation. **Implication:** use its device-motion mode as the principal interaction baseline. Translation-only simplification and a different application do not establish novelty.

### 2. Characterizing Asymmetric Collaborative Interactions in Virtual and Augmented Realities

**Jerônimo Gustavo Grandi, Henrique Galvan Debarba, Anderson Maciel. 2019. IEEE Conference on Virtual Reality and 3D User Interfaces, pp. 127–135.** DOI: [10.1109/VR.2019.8798080](https://doi.org/10.1109/VR.2019.8798080). [Author PDF](https://pure.itu.dk/ws/files/84411580/2019_IEEEVR_Asymmetric_Collab.pdf). [Author institution metadata](https://vbn.aau.dk/en/publications/characterizing-asymmetric-collaborative-interactions-in-virtual-a/).

**Verified:** evaluates co-located mobile AR and immersive VR against symmetric configurations. The AR interface adopts earlier touch/device attachment manipulation; the system supports simultaneous contributions, synchronized content, avatars, and action-awareness cues.

**Overlap:** phone-driven object manipulation, mobile–VR asymmetry, presence, and shared state. **Difference:** the proposal is remote and retains exclusive master control during manipulation, rather than combining simultaneous inputs. **Implication:** distinguish device asymmetry, role asymmetry, and control authority explicitly. A visible avatar does not automatically explain control state.

### 3. CIDER: Collaborative Interactive Dynamic Environments for eXtended Reality

**Hung-Jui Guo, Hiranya Garbha Kumar, Yung-Jen Lin Guo, Balakrishnan Prabhakaran. 2026. ACM Transactions on Multimedia Computing, Communications, and Applications, 22(5), Article 130. Published 21 April 2026.** DOI: [10.1145/3796237](https://doi.org/10.1145/3796237). [Author institution record](https://researchoutput.ncku.edu.tw/en/publications/cider-collaborative-interactive-dynamic-environments-for-extended/).

**Verified:** the leader's physical environment becomes a synchronized interactive scene; co-located participants use MR and remote followers use VR. Participants can manipulate CAD objects and introduce objects. The reconstruction pipeline uses semantic object extraction, CAD retrieval/alignment, and lightweight scene descriptors.

**Overlap:** reconstructed personal space, local/remote roles, interactive virtual objects, synchronized scenes. **Difference:** CIDER addresses a broader reconstruction/distribution platform; the proposal focuses on a phone manipulation technique and game-master authority. **Implication:** “scan a room and let remote VR users interact” is already a strong architectural precedent. Compare reconstruction choices against it, without adopting its authors' “first platform” wording as an independently established fact.

## Additional closely related work

### 4. Collaborative Manipulation of 3D Virtual Objects in Augmented Reality Scenarios using Mobile Devices

**Jerônimo G. Grandi, Iago Berndt, Henrique G. Debarba, Luciana Nedel, Anderson Maciel. 2017. IEEE Symposium on 3D User Interfaces, pp. 264–265.** [Author PDF](https://www.artanim.ch/pdf/publications/67.pdf).

**Verified:** marker-tracked phones support selection, translation, rotation, scaling, and simultaneous manipulation. Section 2.2 attaches the object to the device while a circular button is held and stops attachment on release.

**Overlap:** the basic hold–move–release mechanism already appears here. **Difference:** tabletop markers, multiple mobile users, and additive simultaneous control. **Use:** a short, readable predecessor to paper 1; establish the interaction lineage rather than citing only the later evaluation.

### 5. Virtual Object Manipulation using a Mobile Phone

**Anders Henrysson, Mark Billinghurst, Mark Ollila. 2005. International Conference on Artificial Reality and Telexistence (ICAT).** [Official conference paper](https://icat.vrsj.org/papers/2005/full190.pdf).

**Verified:** explores mobile AR selection, positioning, and rotation with several input techniques. Table 1's Tangible 1 mode fixes an object relative to the moving phone and preserves its final translated position on release, while resetting orientation. Selection uses crosshairs and held joypad input.

**Overlap:** foundational phone-as-manipulation-proxy and engaged physical movement. **Difference:** older marker-tracked hardware, single-user techniques, and no remote room collaboration. **Use:** cite as historical prior art; current positional tracking improves implementation capabilities without making the basic metaphor new.

### 6. SlidAR: A 3D positioning method for SLAM-based handheld augmented reality

**Jarkko Polvi, Takafumi Taketomi, Goshiro Yamamoto, Arindam Dey, Christian Sandor, Hirokazu Kato. 2016. Computers & Graphics, 55, pp. 33–43.** DOI: [10.1016/j.cag.2015.10.013](https://doi.org/10.1016/j.cag.2015.10.013). [Author-lab PDF](https://ar-lab.org/publication/polvi-cag-15/polvi-cag-15.pdf). [Publisher abstract](https://www.sciencedirect.com/science/article/pii/S0097849315001806).

**Verified:** compares ray/epipolar-based positioning against HoldAR, a device-centric method. HoldAR fixes object position in camera coordinates during tap-and-hold, moves it through device motion, and commits on release. SlidAR does not require perfect scene reconstruction.

**Overlap:** markerless tracked handheld positioning and a close hold/move/release comparator. **Difference:** in-situ positioning without remote VR roles. **Use:** compare phone-motion placement with a touch/ray alternative. Its results are task-specific; do not assume they establish superiority in this project's room-scale setting.

### 7. Touch-Move-Release: Studies of Surface and Motion Gestures for Mobile Augmented Reality

**Ze Dong, Jingjing Zhang, Xiaoliang Bai, Adrian Clark, Robert W. Lindeman, Weiping He, Thammathip Piumsomboon. 2022. Frontiers in Virtual Reality, 3, Article 927258.** [Publisher full text](https://www.frontiersin.org/journals/virtual-reality/articles/10.3389/frvir.2022.927258/full). DOI: [10.3389/frvir.2022.927258](https://doi.org/10.3389/frvir.2022.927258).

**Verified:** elicits surface and motion gestures and validates TMR in a ball-throwing AR game. Motion interaction supported engagement/game experience, while the tested surface gesture offered higher precision and easier use.

**Overlap:** touch activation, phone motion, release, and game interaction. **Difference:** throwing in a single-user AR game rather than continuous shared-room placement. **Use:** measure engagement separately from precision. A deliberate release-to-place and a release-to-throw action have different semantics despite a similar input sequence.

### 8. CoVAR: Mixed-Platform Remote Collaborative Augmented and Virtual Realities System with Shared Collaboration Cues

**Thammathip Piumsomboon, Arindam Dey, Barrett Ens, Gun Lee, Mark Billinghurst. 2017. IEEE ISMAR Adjunct, pp. 218–219.** DOI: [10.1109/ISMAR-Adjunct.2017.72](https://doi.org/10.1109/ISMAR-Adjunct.2017.72). [Author institution record and abstract](https://research.monash.edu/en/publications/covar-mixed-platform-remote-collaborative-augmented-and-virtual-r/).

**Verified:** remote AR–VR collaboration shares a reconstruction of the AR participant's environment. Inputs include gaze and hand gestures; head/hand avatars and field-of-view/gaze cues support awareness.

**Overlap:** reconstructed local space, remote VR access, presence, and spatial communication. **Difference:** it does not establish the proposal's phone hold-control interface or game secrecy policy. **Use:** separate presence from awareness of actions. There is also a distinct SIGGRAPH Asia 2017 CoVAR publication with a different author list; do not mix their bibliographic records.

### 9. Integrating AR and VR for Mobile Remote Collaboration

**Jeremy Venerella, Lakpa Sherpa, Tyler Franklin, Hao Tang, Zhigang Zhu. 2019. IEEE ISMAR Adjunct, pp. 104–108.** DOI: [10.1109/ISMAR-Adjunct.2019.00041](https://doi.org/10.1109/ISMAR-Adjunct.2019.00041). [Public research paper](https://par.nsf.gov/servlets/purl/10185645).

**Verified:** MCoAVR reconstructs a textured mesh through a local smartphone AR system and shares it with a remote mobile VR participant. The remote interface supports annotations and landmarks for assistance, with viewpoint/gaze information shared between users.

**Overlap:** mobile capture, remote VR access to a real scene, and spatial guidance. **Difference:** remote expertise assists a local user, whereas the proposal's local master manages content for the remote solver. **Use:** study alignment and shared references. The repository's extracted page title incorrectly says “Global Illumination for Fun and Profit”; the PDF's first page verifies the actual paper and authors.

### 10. Room2XR: Virtual Interactive Collaboration in Real-world Scenes

**Hung-Jui Guo, Hiranya Garbha Kumar, Minhas Kamal, Balakrishnan Prabhakaran. 2024. ACM Multimedia, pp. 11206–11209.** DOI: [10.1145/3664647.3685521](https://doi.org/10.1145/3664647.3685521). [Author institution record](https://researchoutput.ncku.edu.tw/en/publications/room2xr-virtual-interactive-collaboration-in-real-world-scenes/). [Authors' Unity repository](https://github.com/HenryGuo2003/Room2XR-Unity).

**Verified:** reconstructs semantically similar virtual scenes using CAD models and shares them for real-time remote collaboration and manipulation. The author record links implementation resources.

**Overlap:** real-room reconstruction into interactive shared scenes. **Difference:** CAD substitution may preserve semantics while changing the appearance of distinctive personal belongings. **Use:** an implementation reference for semantic reconstruction; evaluate recognizability separately from geometric alignment. CIDER is a later, closely related publication, so these should not be treated as wholly independent system families.

### 11. 3D Gaussian Splatting for Real-Time Radiance Field Rendering

**Bernhard Kerbl, Georgios Kopanas, Thomas Leimkuehler, George Drettakis. 2023. ACM Transactions on Graphics, 42(4), Article 139.** [Publisher paper](https://doi.org/10.1145/3592433). [Author preprint](https://arxiv.org/abs/2308.04079).

**Verified:** represents scenes with optimized 3D Gaussians and a visibility-aware renderer for high-quality novel-view synthesis.

**Overlap:** a possible route to recognizable, visually convincing personal-room appearance. **Difference:** its central output concerns appearance/rendering, rather than executable cabinets, containers, puzzle rules, or shared ownership. **Interpretation:** treat splats as a visual representation and explicitly provide interaction geometry and behaviors. A visually plausible drawer is not evidence that the drawer has an accessible modeled interior or articulation.

## Comparison against the current specification

| Spec component | Closest evidence | Consequence for the project |
| --- | --- | --- |
| Hold phone control, move object, release | Papers 1, 4, 5, 6 | Established interaction family; reproduce as baseline |
| Reposition phone and engage again | Paper 1 | Clutching is also prior art |
| Mobile AR plus immersive VR | Paper 2 | Device asymmetry alone is insufficient |
| Local physical room shared with remote VR | Papers 3, 8, 9, 10 | Strong architectural precedents |
| Phone motion in an entertaining game | Paper 7 | Engagement and placement precision may differ |
| Recognizable visual reconstruction | Paper 11 | Rendering fidelity and interactive structure are separate |
| Master-exclusive authority and hidden game content | Current specification | Design distinction to investigate, not a verified gap |
| Object-relative “on desk / inside cabinet” placement | Current specification | Potential technique extension; requires additional targeted prior-art checking |

## Reconstruction is not automatically interaction

Use four explicit layers in the prototype:

1. **Appearance:** the personal room must look recognizable.
2. **Geometry:** surfaces and collision volumes must support reliable placement.
3. **Object identity and semantics:** the same desk/cabinet must be identifiable on both clients.
4. **Behavior:** a container needs containment rules and an accessible virtual interior; a door needs a movable part, pivot, limits, and state.

This is a proposed architecture, not a claim that every cited reconstruction paper uses these exact layers. Paper 11 primarily motivates the appearance distinction; papers 3 and 10 provide semantic/CAD precedents. Neither photorealism nor CAD retrieval guarantees the puzzle behaviors the specification requires.

A practical first build can retain the room reconstruction as background, add authored colliders and named anchors to one desk/cabinet, and attach explicitly authored behavior. Measure recognizability, registration accuracy, and interaction reliability separately. This is a recommendation rather than an established finding of the reviewed papers.

## Concrete next experiment

**Keep the agreed test boundary:** selection, hold, movement, release, synchronization, and ownership across the connected mobile and VR clients. Do not introduce automatic solver takeover; the user rejected it.

**Baseline:** reproduce device-motion attachment/clutching from paper 1. Implement the specification's translation-only relative-displacement variant, documenting where it differs from full rigid attachment. Log coordinate frame, movement gain, tracking state, engagement points, and release semantics. Keep those parameters constant within a trial.

**First candidate extension:** object-relative assisted placement using explicitly authored desk/floor surfaces and cabinet containment anchors. Compare free phone translation with assisted placement while holding reconstruction, authority, and networking constant. This is a research proposal, not a settled implementation requirement or novelty claim.

**Tasks:** place an object on the desk, beside the cabinet, and on the floor; add an “inside cabinet” task only once containment behavior and a valid target are implemented. Have the VR participant identify final location and whether the object is available to interact with. Separate visible-object trials from hidden-content trials so secrecy does not confound awareness measurement.

**Measures:** completion time, final placement error, invalid/interpenetrating placements, unintended motion, repeated engagements, tracking failures, and both users' observations. For the VR user, record understanding of location and control availability. Report descriptive pilot findings first; avoid inventing acceptance thresholds or claiming comparative superiority from a few demonstrations.

**Questions this can answer:** Does assistance reduce placement ambiguity around reconstructed furniture? Does it preserve the master's sense of continuous control? Can the remote participant understand released state without exposing private preparation? These are more specific than asking whether a phone can move a virtual object.

The user's premise that mobile placement is easier remains an accepted design premise. This experiment does not require a mobile-versus-VR contest; it compares variants of the chosen mobile technique.

## Reading order and search limits

Read **paper 1 (§3 and evaluation), paper 2 (§3 and discussion), then paper 3 (§1–3)**. These address the closest motion mechanism, asymmetric interaction, and reconstructed remote environment respectively. Paper 6 supplies a positioning comparator; paper 7 helps distinguish game engagement from precision.

This is a focused related-work review, not an exhaustive systematic review and not proof that no matching system exists. Search terms covered phone-motion 3D manipulation, hold/release attachment, mobile AR–VR collaboration, reconstructed remote rooms, and interactive scene reconstruction. Evidence comes from original author papers, publisher text, and author institution records; secondary indexes were used only to discover leads.

Full text was inspected for papers 1, 2, 4, 5, 6, 7, and 9. Papers 3 and 11 were checked through publisher material; papers 8 and 10 were checked through institutional author abstracts/metadata, with the latter also linking author code. Findings from abstracts are correspondingly limited. No participant-performance numbers are transferred into project expectations.

Further follow-up: inspect room-scale reach and movement-gain studies; search object-relative constraint/containment techniques; investigate asymmetric game-master interfaces and privacy-aware shared scenes. Do not treat the absence of those works from this shortlist as evidence of novelty. SceneCtrl (Yue, Yang, Ren, Wang; UIST 2017) is an additional scene-editing lead, but its full text was inaccessible during this review, so detailed claims are deferred. [Author institution record](https://researchportal.bath.ac.uk/en/publications/scenectrl-mixed-reality-enhancement-via-efficient-scene-editing/)

## Follow-up: selecting objects for reconstruction, refinement, and behavior authoring

Added 12 October 2026 in response to the more specific question about user-guided partial reconstruction and turning selected objects into interactive content. **Yes, substantial related work exists**, but the following operations should be distinguished:

| Operation | What the user changes | Relevant work |
| --- | --- | --- |
| Interactive segmentation | Which already captured points belong to an object | AGILE3D, Easy3D |
| Geometry processing | Gaps or unwanted components in reconstructed content | Editing Reality |
| Interaction-guided acquisition | Which physical objects are discovered and captured from additional views | PickScan |
| Behavior authoring | What action triggers which virtual response | Teachable Reality |

These categories are an analytical distinction for this project. Correcting an object mask is not automatically improving its geometry; improving geometry is not automatically creating an openable container.

### Editing Reality: A Tool for Interactive Segmentation and Manipulation of 3D Reconstructed Scenes

**Christoph Huber. 2016. Diploma thesis, Technische Universität Wien.** DOI: [10.34726/hss.2016.29541](https://doi.org/10.34726/hss.2016.29541). [University research-unit abstract and metadata](https://www.vr.tuwien.ac.at/publications/editing-reality-a-tool-for-interactive-segmentation-and-manipulation-of-3d-reconstructed-scenes-2016/).

**Verified:** tablet-plus-depth-camera reconstruction, combined automatic/manual separation of planes and objects, subsequent gap filling and removal of unwanted components, and touch-based repositioning, duplication, transformation, and deletion of segmented objects. **Relevance:** particularly close to a workflow that lets a user clean up and manipulate selected parts of their reconstructed room. **Limit:** the checked abstract does not establish selective high-resolution rescanning, cabinet articulation, or puzzle behavior authoring. This is a thesis rather than a peer-reviewed conference paper.

### AGILE3D: Attention Guided Interactive Multi-object 3D Segmentation

**Yuanwen Yue, Sabarinath Mahadevan, Jonas Schult, Francis Engelmann, Bastian Leibe, Konrad Schindler, Theodora Kontogianni. ICLR 2024.** [Authors' project, paper, and code](https://ywyue.github.io/AGILE3D/).

**Verified:** a user and model iteratively delineate objects in an existing 3D point cloud. User clicks correct object/background assignments; the method reasons jointly about multiple objects and produces globally consistent masks. **Relevance:** selecting a personal item and correcting its boundary is already a concrete, implemented research capability. **Limit:** its stated task refines segmentation masks; it does not acquire unseen geometry or assign interactive behavior. A useful component of the proposed workflow, rather than evidence of the entire workflow.

### Easy3D: A Simple Yet Effective Method for 3D Interactive Segmentation

**Andrea Simonelli, Norman Müller, Peter Kontschieder. ICCV 2025.** [CVF open-access paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Simonelli_Easy3D_A_Simple_Yet_Effective_Method_for_3D_Interactive_Segmentation_ICCV_2025_paper.pdf), [authors' project](https://simonelli-andrea.github.io/easy3d/).

**Verified:** 3D clicks generate object masks, with additional clicks refining the result. The authors show a VR application that segments and rearranges objects within a Gaussian-splatting rendering pipeline. **Relevance:** a close precedent for selecting reconstructed content and making it separately manipulable. **Limit:** the demonstration does not establish recovered interior geometry, functional drawers, or per-object selective recapture. Its segmentation capability should not be described as reconstructing a selected object from scratch.

### PickScan: Object discovery and reconstruction from handheld interactions

**Vincent van der Brugge, Marc Pollefeys, Joshua B. Tenenbaum, Ayush Tewari, Krishna Murthy Jatavallabhula. IROS 2024.** [Authors' paper and publication comment](https://arxiv.org/abs/2411.11196).

**Verified:** interaction-guided, class-agnostic object discovery and reconstruction. A user moves through a scene with an RGB-D camera and holds up objects; the method detects user–object interactions, extracts masks, and produces one 3D model per held-up object. **Relevance:** physical interaction can guide which personal items become independently reconstructed assets. **Limit:** “handheld interactions” refers to physically handling the target objects, not simply tapping an object on a phone. It is not directly applicable to lifting a desk or cabinet, and the checked abstract does not describe selectable local rescanning of fixed furniture.

### Teachable Reality: Prototyping Tangible Augmented Reality with Everyday Objects by Leveraging Interactive Machine Teaching

**Kyzyl Monteiro, Ritik Vatsal, Neil Chulpongsatorn, Aman Parnami, Ryo Suzuki. CHI 2023, Article 459.** DOI: [10.1145/3544548.3581449](https://doi.org/10.1145/3544548.3581449). [Author preprint](https://arxiv.org/abs/2302.11046).

**Verified:** authors user-defined tangible/gestural interactions with everyday objects using an on-demand vision classifier and trigger–action interface, supporting functional AR prototypes without programming. **Relevance:** making ordinary personal objects support authored interaction also has prior art. **Limit:** recognizing a physical trigger and responding with AR content differs from building a remote virtual cabinet's interior, hinge, containment, and puzzle state. It does not remove the need to author those structures.

### What this means for the proposed direction

**Interpretation:** a plausible project pipeline is: capture a rough room → select and correct an object mask → request more capture or geometry repair for that object → assign a simple virtual behavior → share the interactive result with VR. The reviewed work establishes substantial pieces of this pipeline. This search has not established that its particular cross-device workflow or selection-driven geometry-refinement interaction is novel.

For the first prototype, make the operation explicit: does selecting the cabinet improve its mask, ask the user to capture additional views, replace it with an editable model, or assign a container behavior? Each produces a different contribution and needs a different baseline. The strongest unresolved question is how a mobile user understands and specifies **what needs improvement** in a selected object and when the result is sufficient for the intended VR interaction.

This follow-up checked primary project pages, author abstracts, the CVF paper, and university records. It does not establish mobile runtime feasibility for these models or guarantee their outputs meet the project's fidelity requirements.

### Camera-specific clarification

**Ordinary mobile RGB cameras have relevant precedents, but distinguish them from depth-equipped devices.** Mobile3DRecon (2020) specifically reconstructs meshes from a mobile phone's monocular embedded camera while tracking camera pose. It establishes camera-only mobile reconstruction, rather than the exact selection-driven refinement and behavior pipeline proposed here. [Authors' project and paper](https://zju3dv.github.io/mobile3drecon/)

Mobile3DScanner (ISMAR 2021) is a separate object-scanning lead using an iPad Pro RGB-D stream and reconstruction preview. It should not be cited as evidence for ordinary RGB-only phone hardware. Its author PDF was inaccessible during this camera-specific check; implementation details need direct inspection before relying on them. [Author paper](https://www.cad.zju.edu.cn/home/gfzhang/papers/mobile3dscanner/mobile3dscanner_ismar2021.pdf)

RealitySketch (UIST 2020) lets users sketch on a mobile AR screen and bind graphical elements to physical objects so they respond to physical motion. This concerns camera-view authoring and responsive graphics, rather than reconstructing object geometry. [Authors' project](https://ryosuzuki.org/realitysketch/)

Teachable Reality (CHI 2023) explicitly captures interaction examples through the mobile camera using an Add Data control, then authors corresponding AR states. Its implementation was tested on **Google Pixel 6 and iPad Pro**, so smartphone participation is verified, despite the workflow often using “tablet” terminology. Its object color-tracking anchor is obtained by raycasting onto a surface; this is not arbitrary 3D object reconstruction. [Publisher paper, §§4–5](https://doi.org/10.1145/3544548.3581449)

**Interpretation:** mobile-camera capture and behavior authoring both exist. This review has not established the exact end-to-end sequence “select an object in the live camera → refine its local geometry → assign virtual behavior → share with remote VR.” Check that sequence directly before making a novelty claim.

**Additional close lead:** PlanAR (Ami Miyake, Hideaki Uchiyama, Atsushi Shimada, Rin-Ichiro Taniguchi; VISAPP 2020) uses smartphone visual SLAM and manual selection of feature points to indicate planes and support reconstruction/positioning. It connects camera capture to user-guided geometric specification, but its plane scope differs from full-object reconstruction and behavior. The university record was checked by the parallel researcher; it could not be independently reopened in this append pass. [Author university record](https://kyushu-u.elsevierpure.com/en/publications/planar-accurate-and-stable-3d-positioning-system-via-interactive-/)

## Deeper review: browser-based environments

Added 12 October 2026. This review distinguishes **actual browser execution**, **a browser front end with native capture**, and **a native application whose project is merely documented online**. Server-side reconstruction is compatible with a browser-based user workflow; it does not mean reconstruction runs inside the phone browser.

The strongest new findings are the **Foo et al. progressive reconstruction lineage** for capture/editing, **WXR** for reconstructed mobile-to-VR collaboration, and **Co-VREUD** for browser collaborative behavior authoring. None of the inspected sources establishes the complete proposed sequence of live camera object selection, user-guided local geometry refinement, virtual behavior assignment, and remote VR play in ordinary browsers.

### Browser-workflow comparison

“Verified” means explicitly supported by the linked primary source. “Partial” identifies a materially different capability. “Not established” is an evidence limit, not proof that the feature is absent.

| System | Browser status | Camera/reconstruction | Selection or local refinement | Virtual behavior authoring | Shared VR |
| --- | --- | --- | --- | --- | --- |
| Foo et al. 2023 | Browser capture and editing verified | Ordinary smartphone images; edge Meshroom reconstruction | Models for scene construction; targeted refinement not established | Not established | Immersive shared VR not established in early paper |
| demoConstruct / R3CAP 2025 | WebXR editor; native iOS capture | LiDAR iPad capture; progressive edge reconstruction | Transform, annotate, inspect evolving reconstruction; selection-driven rescan not established | Metadata/tools; puzzle behavior not established | Multi-user VR editing verified; released code currently same-network |
| WXR ambient objects 2021 | Web XR with custom native-backed iOS browser | LiDAR point clouds and pre-reconstructed objects | Masks known objects out of streamed background | Not established | Remote shared VR verified |
| WXR view study 2023/2024 | Browser client plus custom iOS ARKit browser | Live reconstructed workspace | Viewpoint/context sharing; local refinement not established | Not established | iPad–Quest remote collaboration verified |
| Teachable Reality 2023 | Mobile browser authoring verified | Camera detection and tracking; not reconstruction | Camera-defined states and anchors | Trigger/action verified | Shared remote VR not established |
| Co-VREUD 2026 | Desktop browser and WebXR VR verified | Imported assets; camera reconstruction not established | Entity selection/transforms | Event–condition–action verified | Collaborative VR verified; evaluated co-located |
| DimSplat 2025 | Mobile WebXR verified | Existing splats over live camera | Bounding-volume removal; not new geometry capture | General behavior authoring not established | Remote shared VR not established |
| CollabXR 2024 | WebXR framework verified | Camera reconstruction not established | Dynamic plugins for tools/data | Programmable extension; end-user puzzle authoring not established | Cross-reality collaboration verified |
| ImaginateAR 2025 | Native Unity ARFoundation | Offline scene understanding | AR placement/refinement of authored scene | Rich interactive behaviors listed as future direction | Collaboration listed as future direction |

### 1. Progressive 3D Reconstruction for Collaborative Construction of Digital Twins

**Leon Foo, Songjia Shen, Ambrose Wee, Chek Tien Tan. 2023. Proceedings of the AAAI Symposium Series, 1(1), pp. 7–10.** [Official paper](https://ojs.aaai.org/index.php/AAAI-SS/article/download/27466/27239/31517). DOI: [10.1609/aaaiss.v1i1.27466](https://doi.org/10.1609/aaaiss.v1i1.27466).

The paper explicitly describes browser capture of images from common smartphones, a browser editing client, and edge-node Meshroom SfM reconstruction. This is a close precedent for browser camera capture feeding scene authoring. Crucially, it is a **position paper and early prototype**: near-real-time collaboration, progressive methods, simultaneous editing, and user studies are discussed as goals or further development. Do not convert these plans into completed evaluations. Its abstract's exploration of GAN-based methods also differs from its then-implemented Meshroom pipeline.

### 2. Collaborative Scene Authoring with Near Real-Time 3D Reconstruction

**Leon Foo et al. 2025. CHI Extended Abstracts, Interactivity, five pages.** DOI: [10.1145/3706599.3721190](https://doi.org/10.1145/3706599.3721190). [Author paper](https://www.immersification.org/assets/publications/democonstruct-chi2025.pdf), [research-group project/publication record](https://www.immersification.org/projects/2025/10/09/r3cap.html), [current authors' code](https://github.com/singaporetech/r3cap).

The demoConstruct lineage progresses to coarse-to-fine reconstruction shared between capture, desktop editing, and VR inspection roles. The paper supports multiple-user editing, transforms, metadata, annotations, and measurements. Its LiDAR iPad capture is **not RGB-only browser capture**. Current R3CAP code explicitly separates a native iOS RTAB-Map capture app, Python edge reconstruction, and WebXR editing app for PC/VR. Its README currently requires the same network; wide-area deployment is not established by that release. Browser use is verified for editing, not for every stage. This substantial architectural overlap should be examined before claiming the integrated workflow as new.

### 3. Sharing Ambient Objects Using Real-time Point Cloud Streaming in Web-based XR Remote Collaboration

**Yongjae Lee, Byounghyun Yoo, Soo-Hong Lee. 2021. Web3D, nine pages.** DOI: [10.1145/3485444.3487642](https://doi.org/10.1145/3485444.3487642). [Author paper](https://nfyfamr.github.io/assets/pdf/sharing_ambient_objects.pdf).

WXR combines pre-reconstructed polygon meshes for objects of interest with live ambient point clouds for background awareness. Known objects are masked out of the background stream. Interaction events use WebSocket and point clouds use WebRTC. An iPad Pro supplies LiDAR depth and ARKit object tracking through a custom WXR browser application. This is a strong browser-mediated mobile reconstruction/shared-VR precedent, but it depends on a native-backed browser, depth hardware, and prepared object models. Masking an already tracked object is distinct from selecting arbitrary personal furniture to refine its geometry.

### 4. A User Study on the Comparison of View Interfaces for VR-AR Communication in XR Remote Collaboration

**Eunhee Chang, Yongjae Lee, Byounghyun Yoo. Online 2023; International Journal of Human–Computer Interaction, 40(19), pp. 5794–5809, 2024.** [Publisher full text](https://www.tandfonline.com/doi/abs/10.1080/10447318.2023.2241294?role=tab&scroll=top&tab=permissions), [author PDF](https://nfyfamr.github.io/assets/pdf/A%20User%20Study%20on%20the%20Comparison%20of%20View%20Interfaces%20for%20VR-AR%20Communication%20in%20XR%20Remote%20Collaboration.pdf).

The WXR extension uses A-Frame, a Node.js/MariaDB server, iPad Pro AR, and Meta Quest 2 VR. It compares video, panoramic video, and reconstructed context during target-finding/placing. Section 3.2 explicitly acknowledges a custom WebKit/ARKit iOS browser for otherwise unavailable tracking functionality. This verifies browser-based collaboration with a native bridge, not ordinary Safari-only capture. It informs what spatial context to share, rather than providing selected-object reconstruction or authored game behavior.

### 5. Teachable Reality, revisited as a browser implementation

See its full citation above. Its publisher implementation section verifies client-side mobile browser authoring, camera-based examples, and trigger/action behavior creation. It uses 8th Wall, A-Frame, Three.js, and TensorFlow.js. This is the strongest inspected browser **behavior-authoring** precedent, while geometry reconstruction and remote VR remain separate missing evidence. [Publisher §5](https://doi.org/10.1145/3544548.3581449)

### 6. Exploring the Dynamics of Authoring Interactive VR Environments: Human Collaboration vs. AI Assistance

**Enes Yigitbas, Alessio Dell’Aquila. 2026. Proceedings of the ACM on Human-Computer Interaction, 10(4), Article EICS014. Published 29 June 2026.** DOI: [10.1145/3816766](https://doi.org/10.1145/3816766).

Co-VREUD executes authoring in desktop browsers and WebXR VR, sharing editing events through WebRTC. It includes entity selection/transformation, event–condition–action rules, and spatial task authoring. The study pairs a PC editor and VR editor in the same physical space, and the prototype's described session setup uses the same local network. This is a close **browser collaborative interactive-scene authoring** precedent. Camera reconstruction, phone-camera authoring, and wide-area collaboration are not established here. Imported assets and editable behavior should not be confused with reconstruction of personal furniture.

### 7. DimSplat: A Real-Time Diminished Reality System for Revisiting Environments Using Gaussian Splats in Mobile WebXR

**Kristoffer Waldow, Jonas Scholz, Arnulph Fuhrmann. 2025. IEEE VR publication.** [Author institution paper record](https://cg.web.th-koeln.de/dimsplat-a-real-time-diminished-reality-system-for-revisiting-environments-using-gaussian-splats-in-mobile-webxr/), [authors' IEEE VR tutorial slides](https://mediated-reality.github.io/rf4xr/vr25tutorial/pdf/IEEEVR-2025-T2-3min_Waldow.pdf).

DimSplat uses mobile WebXR, bounding-volume selection, and splat culling to diminish objects while overlaying the reconstructed scene on live camera imagery. It is a particularly relevant browser/mobile-camera precedent for editing what is visible from an existing reconstruction. It does not establish acquisition of additional selected-object geometry, assigning container behavior, or shared remote VR play. Its pre-captured scene must be distinguished from live reconstruction.

### 8. CollabXR: Bridging Realities in Collaborative Workspaces with Dynamic Plugin and Collaborative Tools Integration

**Cheng-Yao Wang, David Saffo, Bill Moriarty, Blair MacIntyre. 2024. IEEE VR Abstracts and Workshops, pp. 454–457.** DOI: [10.1109/VRW62533.2024.00089](https://doi.org/10.1109/VRW62533.2024.00089). [Author research page and paper link](https://ericwang0701.github.io/research).

The authors identify Babylon.js, WebXR, and Colyseus as its implementation stack and support dynamic integration of custom code/data through plugins. It is a verified web-technology cross-reality collaboration platform and a potential implementation reference. That platform extensibility does not itself establish a demonstrated phone-camera reconstruction or end-user behavior-authoring workflow. Avoid conflating this academic CollabXR with other products/projects sharing the name.

### 9. ImaginateAR: AI-Assisted In-Situ Authoring in Augmented Reality

**Jaewook Lee et al. 2025. UIST.** DOI: [10.1145/3746059.3747635](https://doi.org/10.1145/3746059.3747635). [Author project with full author list](https://nianticspatial.github.io/imaginatear/), [paper](https://arxiv.org/abs/2504.21360), [team's technical account](https://www.nianticspatial.com/blog/imaginate-ar).

Relevant to contextual in-situ scene authoring and manual/AI placement refinement, but its real-time interface is built in **Unity with ARFoundation**, not a mobile browser. The team's account identifies interactive behaviors and multi-user co-authoring/sharing as future directions. A web server, online demo video, or project page is not evidence of browser execution. Its generated assets are also distinct from faithfully reconstructing selected personal items.

### Assessment and next research decision

**Verified partial precedents:** browser smartphone capture with edge reconstruction; native mobile depth capture plus browser/VR scene editing; browser-backed AR-to-VR reconstruction sharing; camera-based mobile browser behavior authoring; and collaborative browser VR behavior editing all have concrete examples.

**Evidence limit:** this search has not identified an inspected system demonstrating the complete sequence **ordinary mobile browser camera → arbitrary object selection → selective local geometry refinement → virtual behavior assignment → remote shared VR**. This is a bounded finding, not a universal absence claim. Browser delivery alone is not a research contribution, and combining known components does not automatically establish one.

**Recommended next step:** specify the reconstruction-refinement action and browser boundary before building. Is the user correcting a mask, adding views, changing a mesh, or replacing an object with a behavior-ready proxy? Must capture work in an ordinary browser, or is a native capture bridge acceptable? Those choices determine which precedent is closest and whether the prototype is feasible on the target phone. A focused study could investigate how the master marks an inadequate region, receives targeted capture guidance, and knows that the refined object is sufficient for the intended VR behavior.

For immediate reading, use Foo et al. 2023 and demoConstruct 2025 together to understand the actual lineage, WXR 2021 for the native/browser boundary, and Co-VREUD plus Teachable Reality for behavior authoring. Recent current source-code claims are dated to this review; no code was installed or executed. Publisher pages intermittently failed to open, so indexed primary publisher text and accessible author paper/code records were used. No general browser/device support guarantee is inferred from these historical implementations.
