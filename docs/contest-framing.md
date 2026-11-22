# Framing the IEEE VR 2027 3DUI Contest entry

Drawn from the call ([3DUI Contest 2027](https://ieeevr.org/2027/contribute/3dui-contest/)) and the two literature reviews: [related-work-drills.md](related-work-drills.md) (own-room fire drills, generated hazards) and [related-work-dollhouse.md](related-work-dollhouse.md) (dollhouse view, asymmetric guidance). Written 2026-11-22.

## What the contest asks for

- **Theme:** *"Beyond Shared Reality: 3D User Interfaces for Shared Spatial Interaction"*. Devices differ (headsets, MR glasses, desktop, **mobile**), so people collaborate across different viewpoints, inputs and levels of immersion.
- **Encouraged topics:** cross-device interaction, **asymmetric collaboration**, shared spatial workspaces, remote collaboration, **transitions between realities**, multimodal interaction.
- **The rule that shapes everything:** "All submissions must demonstrate novel techniques for shared spatial interaction", and "the primary contribution should be a novel 3D User Interface or interaction technique". **The application is not what's judged.**
  - So the fire generation is the scenario that makes the techniques matter, not the contribution.
  - The contribution is **how a headset user and a phone user act together on one shared real space at two scales**.
- **Judging:**
  - innovation of the 3DUI;
  - support for shared spatial interaction;
  - usability and experience;
  - technical quality and robustness;
  - impact and creativity.

  Expert judges and the audience try it live at IEEE VR. A real demo must work for strangers, many times over.
- **Submission:**
  - a two-page VGTC extended abstract;
  - a 3–5 minute video;
  - deployment instructions.

  It must say **which techniques were created, adapted or extended**. A formal study is optional.
- **Dates (AoE):**
  - registration 11 Dec 2026;
  - abstract and video **16 Dec 2026**;
  - notification 23 Dec;
  - camera-ready 12 Jan 2027.

  The conference runs 27 Feb – 3 Mar 2027 in Melbourne, and one author must present on site.

## The pitch

> **A personal sand table for shared emergencies.** One person walks their real home with a phone. Another, in a headset, holds that same home as a live, photoreal dollhouse. The commander sets a real object on fire by touching it in the miniature; the occupant sees it burn at full size in the real room, and the commander guides them out with a giant hand and a path drawn from above.

Working title options:
- *Sand Table: Commanding a Shared Real Space Across Scales and Devices*
- *Giant Hands, Small Houses: Cross-Scale Interaction Between Headset and Phone in a Shared Real Home*

## The contribution, as interaction techniques

The call asks us to label each technique as created, adapted or extended. Each is listed with its closest prior work.

| # | Technique | Status | Builds on (cite) | What's ours |
|---|---|---|---|---|
| 1 | **Personal sand table:** a live, photoreal Gaussian-splat dollhouse of the occupant's own space, kept in step with the person inside it | Extended | WIM (Stoakley CHI 1995), Dollhouse VR (Ibayashi 2015), VirtualNexus (UIST 2024), GaussianNexus (UIST 2025) | The whole real home as a miniature, made from a phone video, linked live to someone standing in it |
| 2 | **Touch-to-trigger in the miniature:** pinch a real object in the dollhouse to make it the hazard; it plays at once in both the miniature and the real room at 1:1, on one shared clock | Created | WIM manipulation (Stoakley), direct demonstration on virtual copies (Oda UIST 2015) | Editing the shared real space's *events*, not just its objects, across scales and devices. No AR–VR paper was found where the remote person both triggers events in the trainee's real space and guides them |
| 3 | **Giant hand + path:** the commander's hand in the miniature appears to the phone user as a giant hand in their room, with a ray or path to the exit | Adapted | Stafford et al. "god-like" hands (ISMAR 2006), Mini-Me (CHI 2018), Kim et al. hand vs pointer (CHI 2019), Le Chénéchal guiding arrows (2019) | Seen on a **phone** at 1:1; the literature says pair the hand with a pointer when the two viewpoints differ |
| 4 | **Occupant awareness in the miniature:** the phone user's live position and view cone in the dollhouse | Adapted | On the Shoulder of the Giant (CHI 2019), view-frustum cues | Phone pose kept aligned in the shared splat frame |
| 5 | **Cross-scale shared manipulation:** either person moves the same real-room objects; the phone carries at 1:1, the headset in the miniature or at life size, under one server-side physics | Extended | WIM manipulation, asymmetric VR (ShareVR CHI 2017), Grandi et al. handheld AR + HMD (IEEE VR 2019) | One Havok simulation shared by a phone and a headset at two scales |
| 6 | **Transition between scales:** two-handed pinch shrinks the room to a dollhouse or grows it back to life size, snapping into place at 1:1 | Adapted | Scaled and scrolling WIMs, Danyluk et al. WIM design space (CHI 2021) | The life-size state is aligned with the real room the phone is in |

**The supporting system** isn't claimed as interaction innovation. It goes in "implementation":
- the phone-video → splat reconstruction;
- the AI hazard pipeline: picture cut from the splat → Wan 2.2 → quality gate → L4GM → placed in the object's box;
- browser-only (WebXR) on low-end phones.

## What not to claim

- Not "the first dollhouse / WIM of a real room": VirtualNexus and Dollhouse VR exist. Say *"to our knowledge, the first live miniature of a user's own reconstructed home used to command a co-present occupant"*.
- Not "the first fire in a Gaussian splat scene": FieryGS (ICLR 2026) and AutoVFX (3DV 2025) do this offline. Say *"prompted hazards generated from the object's own appearance, played interactively in XR"*.
- Not "the first phone + headset collaboration": that's a large field, with a 238-paper review (MRxD). The closest fire precedent is Dong et al. 2023, which used a phone and a HoloLens, both in AR.
- Use "to our knowledge" for any absence; the searches were broad but not exhaustive.

## Two-page abstract outline

1. **Problem (3–4 lines):**
   - People rarely practise escaping their own home.
   - Exit familiarity drives escape choice (Kinateder: about 71% use the door they came in by).
   - VR fire training uses generic buildings.
   - Collaboration between a remote commander and an occupant crosses devices and scales.
2. **System overview, with a figure:** the occupant on the phone (1:1 AR over the real room) and the commander on the Quest (dollhouse), sharing one splat, one physics and one clock.
3. **Techniques 1–6** from the table, each a short paragraph, marked created, adapted or extended.
4. **Implementation:** WebXR on both devices, Spark splats, server-side Havok, the AI hazard pipeline and its quality checks, SPZ frames (176 KB each).
5. **Design iterations:**
   - #213 floor fix;
   - #218 floor touch;
   - the camera-switch experiment, dropped;
   - furniture in the dollhouse leading to hazards in it;
   - giant hand only, then hand plus path.
6. **Pilot results,** if time allows (below).
7. **Related work and novelty:** the table above, compressed.

## Video, 3–5 minutes

1. Title, names and affiliations; the equipment (Quest 3, an Android phone and an iPhone, a GPU server).
2. Film the room with the phone, with the coach; the splat appears.
3. The commander shrinks the room to a dollhouse and sees the occupant's marker.
4. The commander pinches the bed and says "catches fire". Show the progress, or cut to the cached result.
5. Split screen: the fire in the miniature, and the same fire on the phone at 1:1 over the real bed.
6. The giant hand and path guide the occupant to the door; the occupant walks out.
7. Cross-scale manipulation: the commander drops a box from the dollhouse, and the phone sees it fall.
8. Labels: created, adapted, extended.

## Live demo at IEEE VR (the big practical risk)

The demo can't be in the occupant's own home. The booth becomes the "home":
- **Plan A:** film the booth on day one with the phone, build it on the GPU server, and run the drill in the booth's own splat. The server is reached over the internet from Melbourne.
- **Plan B:** a pre-built room from home, played as a VR walkthrough. The phone then can't do 1:1 AR in it.
- **Cache** a few hazards in advance (#235); live generation takes minutes and spends quota.
- **Booth needs:** network to the server, a stand for the phone or a helper walking, and a clear path for the phone user.

## Pilot study (optional for the abstract, worth having)

Eight to twelve people, two parts:
- **Part A:** the participant is the occupant; an experimenter commands from a script. Conditions are voice only, hand plus voice, and hand plus path plus voice.
- **Part B:** the participant is the commander; a helper walks a fixed route.

**Measures:**
- time to the first step and to the exit;
- wrong turns, and path length against the shortest path;
- NASA-TLX;
- a few co-presence items;
- ease and fun ratings;
- SSQ for the commander.

**Safety:**
- a permanent "DRILL" label on the phone;
- no real alarm sounds;
- a cleared path with someone alongside;
- a stop button;
- anxiety rated before and after;
- screening for fire-related trauma;
- consent for storing the home scan.

## What to build in 24 days, in order

1. **#230:** hazards play on the Quest, also in the dollhouse. *Done, in review.*
2. **#231:** phone playback over the real room, with the **DRILL** label.
3. **#234, reduced:** pinch an object in the dollhouse to start its hazard. This is technique 2.
4. **New:** a **path or ray from the giant hand** to where it points, seen on the phone (technique 3), and the **phone user's view cone** in the dollhouse (technique 4).
5. **#235:** cache hazards for the demo.
6. **#218:** floor touch, so things sit on the real floor in the headset.
7. Video and abstract: draft from 8 December; register by **11 December**.

Can wait until after submission:
- #232 (spoken prompt to object), since pinching in the dollhouse covers it;
- #233 (new objects);
- #219 (phone throw);
- #241 (flaky tests).

## Check before submitting

- Read GaussianNexus's full paper for a miniature mode; one would narrow technique 1.
- Check whether Stafford 2006's table showed a 3D miniature or a map.
- Check the Snow Dome mechanics.
- Look for prior 3DUI contest winners with a WIM plus phone setup.
- Verify the citations marked "from memory" in both reviews.
