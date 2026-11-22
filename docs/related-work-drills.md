# Own-room fire drills hold up, with narrower wording

Of the four standout claims, two hold up and two need narrower wording. **Claim 1 (fire training normally uses generic or hand-built places, not the trainee's own reconstructed room) is supported.** **Claim 2 (prompted, generated 4D hazards on objects inside the user's own splat) is supported only in its narrow form.** Fire inside captured Gaussian scenes already exists through physics simulation (FieryGS, ICLR 2026) and LLM-scripted Blender effects (AutoVFX, 3DV 2025), so "first fire in a splat" would be false. **Claim 3 (cross-device phone-AR plus headset-VR emergency training is uncommon) is only partly supported.** Phone plus headset collaboration is a large field, with one review covering 238 papers. A smartphone plus HoloLens firefighter demo already exists. What did not turn up is the specific setup: a phone AR user in the real room, a VR user in a reconstruction of that same room, and a drill between them. **Claim 4 (browser-only, low-end inclusive XR training) is partly supported.** Published papers ask for exactly this, but reviewers will see it as engineering unless frame-rate and load-time numbers from low-end phones back it up. Across all four, the defensible contribution is the *combination*: a phone-captured home, a prompted generative 4D hazard on a real object, and an asymmetric browser drill. Each piece has precedent; the whole does not. The biggest risks the literature raises are technical (L4GM was trained only on Objaverse-style animated meshes, and Gaussian splatting is reported to "fundamentally fail" on fire) and evidential: no study has compared drills in one's own space with drills in a generic space, and evidence that VR training transfers to real behaviour is thin. All findings come from four research-note files built from roughly 70 searches. Many publisher pages were blocked, so several items rest on abstracts or snippets, and "not found" means "not found in a limited search", not "does not exist".

## Fire training reviews never list the trainee's own home

### Verdict on claim 1: supported

The systematic reviews describe a field built on purpose-made virtual buildings. These are game-engine scenes, sometimes modelled on one real school, hotel, hospital or campus. **None of them treats "the trainee's own reconstructed space" as a category.** Feng et al.'s review of immersive evacuation serious games covers indoor fire and earthquake scenarios in authored environments ([arXiv 1805.09138](https://arxiv.org/abs/1805.09138)). Others include a 2025 PRISMA review of 48 VR building-evacuation studies ([Fire 8(2):80](https://dx.doi.org/10.3390/fire8020080)), a 2023 *Safety Science* review of VR evacuation drills ([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0925753523000838)) and a 73-source scoping review of fire evacuation training ([Fire Safety Journal](https://www.sciencedirect.com/science/article/pii/S0379711223000103)). None of these surfaced an own-space category, though only abstracts were readable, so per-study coding of environment type remains unverified. Consumer home-fire VR apps such as "Escape My House" also use generic layouts ([EHS VR](https://www.ehsvr.com/apps/escape-my-house)). So does an Iowa State children's home-escape program, which reported enjoyment but no concrete learning gains ([ISU thesis](https://lib.dr.iastate.edu/cgi/viewcontent.cgi?article=15540&context=rtd)).

### Closest prior work

The closest counter-examples replicate real *institutional* buildings, not a trainee's home:

- **University campus building.** A Springer chapter trains fire evacuation in a digital twin of a campus building, with BCI devices ([Springer](https://link.springer.com/chapter/10.1007/978-3-032-30816-0_22)).
- **Existing school.** A 2022 *Buildings* paper reproduces evacuation from an existing school ([DOI 10.3390/buildings12020223](https://doi.org/10.3390/buildings12020223)).
- **Firefighter training in reconstructed scenes.** Lian et al. (2024) use **3D Gaussian Splatting and NeRF environments for multi-user VR firefighting**, but for firefighters at a site, not occupants at home, and with hand-authored fire ([Remote Sensing 16(13):2448](https://doi.org/10.3390/rs16132448)).
- **Earlier reconstruction for serious games.** A 2018 paper compared laser scanning, 360 panoramas and BIM for building indoor VR training scenarios ([arXiv 1812.01706](https://arxiv.org/pdf/1812.01706)).
- **Practice and products.** Kentucky fire departments laser-scan their drill sites ([ISHN](https://www.ishn.com/articles/113875-using-reality-capture-technology-for-virtual-firefighter-training)). AK Preparedness's SafetyNet VR puts occupants in a photoreal model of their own facility "from any device" ([AK Preparedness](https://akpreparedness.com/vr/)). This is the closest commercial "own space, any device" offering, but it works at organisation scale.
- **Planned AR project.** A 2025 George Mason project plans to use a room digital twin so AI can generate and predict a realistic fire for *firefighter* AR training ([GMU news](https://www.gmu.edu/news/2025-05/trial-virtual-fire-augmented-reality-project-tailors-training-firefighters)).

### What differs

None of these has a householder capture their own home with a phone and then drill inside it. The motivation is strong because official guidance is home-specific. The US Fire Administration says to practise your own escape plan twice a year ([USFA](https://webarchive.library.unt.edu/web/20120915093142/http://www.usfa.fema.gov/downloads/pdf/focus/jan_2012_escape_plans.pdf)), and plans need two ways out of every room ([LAFD](https://lafd.org/home-escape-plan)). Evacuation research shows that familiarity drives exit choice. With two equidistant exits, **about 71% of people chose the door they entered by** ([Kinateder et al.](https://www.sciencedirect.com/science/article/abs/pii/S0925753516306038)), and exit familiarity "generates a substantial shift" in choice probabilities ([Lovreglio et al.](https://www.researchgate.net/profile/Ruggiero-Lovreglio/publication/361426636_Exit_Choice_in_Built_Environment_Evacuation_combining_Immersive_Virtual_Reality_and_Discrete_Choice_Modelling/links/62b0dfd76ec05339cc94bd32/Exit-Choice-in-Built-Environment-Evacuation-combining-Immersive-Virtual-Reality-and-Discrete-Choice-Modelling.pdf)). In those studies, though, familiarity was created inside a virtual building during the experiment. No trial has tested drilling in one's own space against a generic space.

### Suggested wording

> "VR and AR fire training normally takes place in generic or purpose-modelled environments; where real places are used, they are replicas of a single institutional building or firefighter site. We found no peer-reviewed system in which occupants capture their own home with a phone and rehearse an emergency inside that reconstruction. Because evacuation behaviour depends strongly on familiarity with exits, and official guidance asks households to practise in their own layout, we argue such training is worth building; whether it outperforms generic environments remains to be tested."

## FieryGS and AutoVFX already burn captured scenes

### Verdict on claim 2: supported narrowly, contradicted broadly

Two must-cite papers rule out any broad claim of "fire in a reconstructed scene":

- **FieryGS (ICLR 2026)** runs physics-based volumetric combustion directly inside 3DGS reconstructions of real indoor and outdoor scenes (kitchen, chairs, stools, garden), with flame spread, smoke and charring. GPT-4o infers per-Gaussian burnability for **about $0.55 per scene**. Rendering is offline, there is no VR, and the fire is *simulated, not generated* ([arXiv 2605.00177](https://arxiv.org/abs/2605.00177); [project](https://pku-vcl-geometry.github.io/FieryGS/)).
- **AutoVFX (3DV 2025)** turns a natural-language instruction plus a captured video into GPT-4-written Blender code. That code inserts objects and sets them on fire with Mantaflow smoke and fire on a BakedSDF plus Gaussian scene ("make it on fire"). It failed on **19 of 55 test instructions**, and its output is an offline video along the input camera path ([arXiv 2411.02394](https://arxiv.org/abs/2411.02394v1)).

### Nearest generative precedents

**Splat4D (SIGGRAPH 2025)** edits 4D Gaussian objects with "house on fire" and "WALL-E on fire" prompts, but only qualitatively, on object-centric data ([arXiv 2508.07557](https://arxiv.org/html/2508.07557v1)). **WonderPlay (ICCV 2025)** couples a physics solver with a video generator, including smoke, but starts from a single image and is driven by forces rather than hazard prompts ([arXiv 2505.18151](https://arxiv.org/abs/2505.18151)).

### Interaction and authoring precedents

The interaction pattern "speak and the XR world changes" is already established:

- **LLMR** (CHI 2024) generates Unity code from prompts at runtime ([arXiv 2309.12276](https://arxiv.org/abs/2309.12276)).
- **DreamCodeVR** (IEEE VR 2024) turns spoken commands into runtime behaviour code ([UCL PDF](https://discovery.ucl.ac.uk/10190408/1/2024019754.pdf)).
- **ImaginateAR** (UIST 2025) does scene-aware speech-to-mesh authoring on mobile AR ([arXiv 2504.21360](https://arxiv.org/abs/2504.21360)).
- **CinemaWorld** (2026) places generated dynamic particles and lighting in a Quest 3 user's room ([arXiv 2603.08060](https://arxiv.org/abs/2603.08060)).
- **Editing Reality** (2026) erases, retextures and adds content in passthrough MR by speech ([CU Boulder](https://www.colorado.edu/atlas/editing-reality-situ-co-creation-generative-ai-mixed-reality)).

In safety training specifically, generative AI so far drives *dialogue*, not visuals. One example is an LLM "AI fire dispatcher" in a 2025 *Fire Safety Journal* study ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0379711225002607)). Scenarios themselves are hand-built, optimised ([Purdue ISMAR-Adj 2022](https://web.ics.purdue.edu/~cmousas/papers/conf22-IEEEISMAR-Adjunct-SharedSpaceEvacuation.pdf)) or adapted by simulation ([ProACT, arXiv 2610.38117](https://arxiv.org/abs/2610.38117)).

### What differs

No paper found combines all of the following:

- a hazard whose look and motion come from an **image-to-video model conditioned on the real object's own pixels**, cut from the user's splat;
- a **video-to-4D lift** (L4GM) into a reusable Gaussian asset;
- that asset **anchored back in the object's box** in the same reconstruction;
- **interactive free-view playback** in VR and AR;
- a **safety-drill purpose**.

Swapping the real bed for its burning twin is also a form of diminished reality, done in the reconstruction rather than in live passthrough. The DR review literature covered in the notes does not describe that ([Springer review](https://link.springer.com/article/10.1007/s10055-024-01074-0)). The honest trade-off compared with FieryGS is **open-vocabulary hazards** ("the TV sparks", "the sink floods") in exchange for **no physical spread or interaction with neighbouring objects**.

### Suggested wording

> "Fire has been simulated inside captured Gaussian scenes (FieryGS) and scripted into reconstructed videos from language instructions (AutoVFX), both offline. Our system instead generates the hazard: a spoken prompt drives an image-to-video model conditioned on the target object's own appearance in the user's reconstruction, the result is lifted to a 4D Gaussian asset and anchored at that object, and it is experienced interactively in VR and AR for drill purposes. To our knowledge this combination has not been reported. Our hazards are visually plausible rather than physically simulated."

## Phone and headset pairing is common; this drill configuration is not

### Verdict on claim 3: partly supported

"Asymmetric cross-device collaboration is uncommon" is false as a general statement:

- **MRxD** builds a usage framework from **238 papers pairing headsets with phones and desktops** ([arXiv 2611.16171](https://arxiv.org/pdf/2611.16171)).
- **ShareVR** (CHI 2017) is the canonical example of collaboration between HMD and non-HMD users ([PDF](https://www.uni-ulm.de/fileadmin/website_uni_ulm/iui.inst.100/1-hci/hci-paper/2017/ShareVRFinal.pdf)).
- **Numan et al.** (VRST 2022) studied AR–VR dyads ([preprint](https://discovery.ucl.ac.uk/10160098/1/Numan_VRST2022_preprint.pdf)).
- **Teo et al.** (CHI 2019) put a remote VR user in a 3D reconstruction of the local user's space, which is structurally the closest to this project's own-room setup ([dblp](https://dblp.org/rec/conf/chi/TeoLLBA19)).
- **CrossGaussian** extends that idea to room-scale 3DGS ([poster](https://accessible-cps.github.io/posters/CrossGaussianPoster.pdf)).

### Closest prior work in emergency training

On emergency training, the nearest match is **Dong, Chen and Li's INFOCOM 2023 workshop demo**. It runs collaborative firefighter MR on a **Pixel 6 smartphone plus HoloLens 2** with an edge server, and focuses on keeping the fire consistent across network delays. It is a two-page demo with no user study, both devices are AR, there is no reconstructed own room and no remote VR participant, and it appears to use native apps ([NSF PAR](https://par.nsf.gov/biblio/10426466)). Commercially, **FLAIM Trainer** pairs a Quest trainee with an instructor iPad, but the iPad is a control dashboard, not a participant in the space ([DHS VR market survey 2024](https://www.dhs.gov/sites/default/files/2024-07/2024_0709_st_vrmsr%20(2).pdf)). Multi-user fire VR also exists, but it is symmetric, with everyone in VR ([Braun et al.](https://www.researchgate.net/publication/365066099_Virtual_Reality_for_Immersive_Multi-User_Firefighter_Training_Scenarios); [tunnel simulator](https://www.scitepress.org/Papers/2021/103194/pdf/index.html)).

### What differs

Two things distinguish this project. First, the non-HMD participant is an *embodied AR occupant standing in the real room*, not someone at an instructor dashboard. Second, the headset user is a *remote commander inside a reconstruction of that same room*.

### Suggested wording

> "Phone–headset asymmetric collaboration is well studied, and instructor-tablet/trainee-HMD setups exist commercially. In emergency training we found one closely related demo pairing smartphones and HoloLens for firefighter MR (Dong et al. 2023). We did not find a system in which a phone-AR occupant in the real room and a VR-headset responder in a reconstruction of that room share one drill."

Avoid "first".

## Browser-only inclusivity is a motivated claim that still needs numbers

### Verdict on claim 4: partly supported

The motivation is well documented:

- **VRinDanger** (Universal Design 2024) concludes that there is a need for **cost-effective, cross-platform** browser VR and accessibility guidelines ([IOS Press](https://ebooks.iospress.nl/pdf/doi/10.3233/SHTI241042)).
- A Virginia Tech thesis frames mobile devices as an **inclusive alternative** to headsets in collaboration ([VTechWorks](https://hdl.handle.net/10919/117630)).
- A CEUR paper criticises XR "walled gardens" that stop a Quest user from collaborating with a smartphone user ([CEUR Vol-4226](https://ceur-ws.org/Vol-4226/paper20.pdf)).
- A review lists hardware cost as a major barrier in low-resource settings ([arXiv 2501.08237](https://arxiv.org/pdf/2501.08237)).

The rendering stack now makes the claim feasible. **Spark targets over 98% of WebGL2 devices** and reads compressed SPZ ([GitHub](https://github.com/sparkjsdev/spark)). WebSplatter brings WebGPU compute sorting ([arXiv 2602.03207](https://arxiv.org/html/2602.03207)).

### Caveats

WebXR *training* research is thin: mostly single-user education, plus a desktop web fire-drill game ([Applied Sciences 2021](https://www.mdpi.com/2076-3417/11/23/11284/xml)). "Heavy AI on a server, thin client" is a standard pattern that Dong et al. already used, so it is not a novelty. There are also hard counter-signals:

- A 2026 paper reports that sustained splat rendering on iPhone and iPad hits an **unavoidable thermal slowdown after a few dozen seconds** ([arXiv 2609.05255](https://arxiv.org/pdf/2609.05255)).
- WebSplatter argues that WebGL's CPU sorting makes large scenes impractical ([arXiv 2602.03207](https://arxiv.org/html/2602.03207)).
- No peer-reviewed data on headset ownership was found. Cost arguments rest on vendor or secondary sources.

### Suggested wording

> "Prior work calls for cost-effective, cross-platform XR training that does not exclude people without headsets. Our system runs entirely in the browser on both devices, and the generative pipeline runs on a server, so a low-end phone can take part. We report frame rate, load time and thermal behaviour on [named low-end and mid-range phones]."

Frame it as a systems and inclusion contribution, not a technique.

## L4GM, flames and transfer are the weak links reviewers will probe

### Technical risks

The pipeline's central technical risk is a distribution mismatch:

- **L4GM** is a roughly one-second feed-forward model trained only on synthetic animated Objaverse objects (44K objects, 110K animations) ([arXiv 2406.10324](https://arxiv.org/abs/2406.10324)). Fire and smoke are semi-transparent, emissive and change topology, which is far from that data.
- **No 4D-generation paper found evaluates fire, smoke or destruction** as a category.
- **Gaussians on Fire** states that standard Gaussian splatting "fundamentally fail[s]" on flames, and needs per-Gaussian lifetime and velocity to reconstruct them ([arXiv 2511.22459](https://arxiv.org/html/2511.22459v1)).
- Splat4D's fire demos are qualitative only.

Expect the lifted flames to look smeared or "sticky". WonderPlay notes "sticky smoke" artifacts that its video stage was added to fix ([arXiv 2505.18151](https://arxiv.org/abs/2505.18151)). The paper should say whether the quality gate catches this and show failure cases. AutoVFX's 35% instruction-failure rate is a useful benchmark for reporting generation failures openly. Nothing in the notes evaluates Wan 2.2 on fire, so its behaviour has to be measured rather than cited. Real-time playback of an L4GM asset inside a full room splat on Quest and phone is also unmeasured anywhere.

### Evidence risks

Meta-analysis favours VR over traditional methods for safety *knowledge* acquisition and retention, but knowledge declines over time ([Scorgie, Lovreglio et al. 2024](https://sciencedirect.com/science/article/pii/S0925753523003144)). VR extinguisher training preserved self-efficacy after 3–4 weeks where video did not ([Lovreglio et al. 2021](https://link.springer.com/article/10.1007/s10055-020-00447-5)). **Transfer to real behaviour is thin.** One residential-fire VR study reported most students transferred skills ([Computers & Education 2019](https://www.sciencedirect.com/science/article/abs/pii/S036013151930020X)), but a widely cited small study had only **6 of 10** participants transfer completely and correctly ([Chalmers thesis](https://odr.chalmers.se/server/api/core/bitstreams/cedef198-e79c-4a59-8840-88fe4acbc53a/content)). Lian et al.'s 3DGS firefighting users reported a **"lack of urgency"** ([Remote Sensing 2024](https://doi.org/10.3390/rs16132448)), which warns that photoreal reconstruction alone does not create stress realism.

### Ethics risk

Editing Reality participants worried about generative MR hiding real objects or signals ([PDF](https://www.colorado.edu/atlas/sites/default/files/attached-files/weng-editing_reality.pdf)). In a home drill the reverse risk applies: a phone user must always be able to tell a simulated fire from a real one. A process-safety article also warns that realistic but wrong AI scenarios create false confidence ([Processing Magazine](https://www.processingmagazine.com/maintenance-safety/article/55395825/how-vr-digital-twins-and-ai-can-strengthen-industrial-training-process-safety)). That supports both the quality gate and a clear "simulation" indicator.

## A four-part evaluation matches comparable papers

Comparable generative-XR papers pair a technical benchmark with a small mixed-methods study:

| Paper | Technical evaluation | User study |
|---|---|---|
| LLMR | Error rate | N=11 |
| ImaginateAR | Speed and accuracy | N=20 |
| CinemaWorld | 100 clips | N=12, plus 8 expert interviews |
| Say It, See It | Latency | N=11, satisfaction and intent-alignment scores |

Sources: [LLMR](https://arxiv.org/abs/2309.12276); [ImaginateAR](https://arxiv.org/abs/2504.21360); [CinemaWorld](https://arxiv.org/abs/2603.08060); [Say It, See It](https://arxiv.org/abs/2508.12498).

Say It, See It found that **users tolerated latency when quality was high**. That justifies authoring hazards minutes before the drill. Safety-training papers instead compare learning outcomes against VR or video baselines with about 60 participants ([Safety Science 2024 AR study](https://www.sciencedirect.com/science/article/pii/S0925753524003047)).

| Part | What to measure | Precedent |
|---|---|---|
| 1. Pipeline benchmark | Prompt-to-hazard success rate over N prompts and objects, quality-gate pass and fail rates against human ratings, per-stage latency, prompt alignment of the 4D result (CLIP-style), temporal consistency, failure taxonomy | AutoVFX failure reporting; RoomDreamer CLIP similarity; LLMR error rates |
| 2. Device performance | FPS, load time, memory and thermal throttling over a 5–10 min drill on low-end, mid-range and high-end phones plus Quest; splat size before and after SPZ | Thermal finding in arXiv 2609.05255 |
| 3. Within-subjects study (N≈12–20 pairs) | Own-room vs generic-room (or prebuilt-fire) condition: presence (IPQ), perceived realism and urgency, hazard-recognition and response correctness, SUS for the commander's authoring, co-presence for both roles | CinemaWorld, Prop-Chromeleon baselines; Lian et al. urgency gap |
| 4. Expert review | Interviews with fire-safety instructors or firefighters on drill validity and hazard plausibility | CinemaWorld's 8 expert interviews |

If time allows, a delayed (2–4 week) retention probe of escape-route knowledge would speak directly to the knowledge-decline finding. Claim only what the study measures: the project cannot claim better real-world transfer without a behavioural test.

## Citations still to verify

The notes flag these items as resting on memory, snippets or unconfirmed details. Check them before citing in the paper.

| Item | Issue |
|---|---|
| Consistent4D, 4DGen, Animate124, STAG4D, SV4D, SV4D 2.0, Diffusion4D, 4Real, CAT4D | IDs and venues from memory; links not reopened |
| PhysGaussian, Gaussian Splashing, PhysGen3D | From memory |
| Instruct-NeRF2NeRF, Instruct-GS2GS, GaussianEditor, DGE, Instruct 4D-to-4D | From memory |
| L4GM author list | "Cheng Xie" vs "Kevin Xie" inconsistent across listings |
| Lian et al. 2024 (Remote Sensing) | Which site was reconstructed, how, and the "lack of urgency" quote: snippet only |
| Campus digital-twin and BCI chapter (Springer) | Capture method, whether trainees were occupants, year |
| Dong, Chen, Li INFOCOM 2023 demo | Native or browser, and roles: PDF unreadable |
| CrossGaussian | Venue, year and devices unknown (image-only PDF) |
| Editing Reality | Venue not confirmed (ACM page 403) |
| CinemaWorld | How the room is mapped |
| ProACT | Whether an LLM is used: conflicting summaries |
| Fire Safety Journal 2025 LLM dispatcher; SAGE 2026 "From Simulation to Dialogue" | Snippet only; roles and study sizes unknown |
| "Contextual (home-like) platform improved hazard identification" | Paper attribution unclear; do not cite until found |
| *Fire* 2025 and *Safety Science* 2023 reviews; Scorgie 2024 meta-analysis | Full text blocked; no pooled effect sizes or environment-type counts |
| Kinateder ~71% familiar-exit figure; Kobes hotel study | Abstract or snippet only |
| CG&A 2024 "Integrated AR and VR fire drill"; HoloLens evacuation (Stigall and Sharma); smartphone-HMD evacuation system (authors) | Snippet only or authors unverified |
| NFPA household escape-plan statistics (1 in 3, 23%, 71%/45%); "2 minutes to escape" | Secondary sources with conflicting figures; check nfpa.org |
| "Only seven collaborative fire systems support >2 users" | Source unidentified; do not cite |
| MRxD 238-paper count; Numan VRST 2022 dyad findings | Snippet only |
| IEEE VR / ISMAR / CHI 2024–2026 proceedings and 3DUI contest entries | Not searched directly; the novelty claims need a final targeted check |

## Conclusion

The project's novelty does not sit in any single headline feature. Fire in splats, prompting XR, phone plus headset collaboration and web splats all have precedent. It sits in one join no paper has made: **open-vocabulary generative hazards in a home the user scanned with a phone, drilled across devices in the browser**. That means the paper should spend its novelty budget on the join and cite FieryGS, AutoVFX, Teo et al. and Dong et al. directly, rather than letting reviewers raise them.

The literature also points to an empirical opening the project is well placed to fill. Familiarity strongly shapes evacuation choices, yet no one has tested a drill in one's own space against a generic one. Even a small own-room vs generic-room comparison would add evidence where the field currently has none. The real failure risk sits in the L4GM-on-fire step, so showing quality-gate results and failure cases openly will make the paper stronger.
