# Claim the join, not the dollhouse

Neither headline feature is new by itself, but the way this project combines them is. **(a) A dollhouse or world-in-miniature (WIM) command view is a 30-year-old 3DUI technique.** Stoakley et al. introduced it in 1995, Dollhouse VR (2015) already split roles between a top-down manipulator and an inside occupant, and VirtualNexus (UIST 2024) already builds a WIM from a live capture of a real room and syncs edits to a co-present AR user. What we did not find is a **photoreal Gaussian-splat dollhouse of the user's own whole home, used live to command a person who is physically standing in it**. **(b) Asymmetric AR–VR guidance at different scales is a mature line of work.** It runs from Stafford et al.'s 2006 "god-like" indoor hands shown to outdoor AR users, through CoVAR, Mini-Me and On the Shoulder of the Giant, to Le Chénéchal et al.'s handheld-tablet navigation guidance from a WIM view (2019). Two things in this project have no evaluated precedent that we found: a **giant hand seen at 1:1 by a phone-AR user**, and a **trainer-as-commander who both injects hazards into the trainee's real space and guides them out**. Reviewers will cite Stoakley, Dollhouse VR, VirtualNexus, GaussianNexus, Stafford 2006, Le Chénéchal 2019, Grandi 2019 and the Piumsomboon papers, so the paper should cite them first and claim only the combination. The literature also gives a concrete design warning. When the guide and the guided person have independent viewpoints, local users struggle to read the remote person's hand gestures and fall back on pointers ([Kim et al. 2020](https://opus.lib.uts.edu.au/bitstream/10453/144637/2/jmui%202020.pdf)). The giant hand therefore needs a ray or arrow path alongside it. For the 2-page contest format, a pilot of about 8–12 people with exit time, route errors, NASA-TLX, a few co-presence items and clear drill-safety mitigations fits what the contest asks for and what comparable papers report. These findings come from three new note files (about 60 searches) plus an earlier own-room fire-drill report. ACM full texts were blocked (HTTP 403), so many details are abstract-level, and "not found" means "not found in a limited search".

## The miniature is 1995 technology; its referent is what changed

The WIM is foundational 3DUI. **Stoakley, Conway and Pausch (CHI 1995)** gave VR users a hand-held miniature copy of the virtual world as a second viewport. Users could select, move objects and navigate through it, and moving a copy in the miniature moved the real-size object ([CMU copy](https://www.cs.cmu.edu/~stage3/publications/95/conferences/chi/paper.html)). Voodoo Dolls (I3D 1999) extended this to transient hand-held copies for multi-scale manipulation ([Pierce thesis](https://www.csd.cmu.edu/sites/default/files/phd-thesis/CMU-CS-01-160.pdf)). **Danyluk et al. (CHI 2021)** then mapped the whole design space along seven dimensions: size-scope-scale, abstraction, geometry, reference frame, links, multiples and virtuality. They explicitly extended WIMs "across the XR spectrum" ([iLab](https://ilab.ucalgary.ca/publications/chi-2021-danyluk/)). The project's Quest feature of placing furniture or hazards in the dollhouse so they appear at full scale is therefore the original 1995 manipulation idea, and the paper should say so. Danyluk's **links** dimension (how the miniature is coupled to the full-size world) and **virtuality** dimension (where the WIM and its referent sit on the reality–virtuality continuum) are the right vocabulary for positioning the work. Here the referent is a real home with a person inside it, and the link crosses devices and users.

**Dollhouse VR (Ibayashi et al., SIGGRAPH Asia 2015 E-Tech)** is the closest conceptual match for "commander above, occupant inside". Designers manipulated a top-down miniature on a tabletop, while occupants in HMDs saw the same space from inside, and the two groups had techniques for communicating ([SIGGRAPH history](https://history.siggraph.org/?p=193457); [SA2015 E-Tech](https://sa2015.siggraph.org/en/attendees/emerging-technologies/event/E-Tech%20talks/367.html)). It differs from this project in four ways. Its space was a virtual design, not a reconstructed home. Its occupant was in an HMD, not physically in a real room on a phone. Its manipulator arranged layouts and did not trigger dynamic hazards. It ran on lab hardware, not in browsers. No user-study results for it were found.

Miniatures of *captured real* places also exist, and these set the tightest bound on claim (a):

- **VirtualNexus (Huang et al., UIST 2024).** A remote VR user ray-casts a region of a live 360° video aligned to a HoloLens 2 mesh, pulls the cut-out close as a WIM, and places annotations or objects on it, which then appear in the local AR user's view. The authors themselves say WIMs in remote collaboration are "not widely explored" ([arXiv 2408.02914](https://arxiv.org/html/2408.02914)).
- **Duplicated Reality (Yu et al., TVCG 2022).** A small sensor-covered workspace is reconstructed live as an AR copy that co-located users annotate ([record](https://nufind.nu.edu.sa/EdsRecord/edseee,edseee.9712238)).
- **Remixed Reality (Lindlbauer and Wilson, CHI 2018).** It manipulates a live Kinect reconstruction of the user's own room, but for a single user ([MSR](https://www.microsoft.com/en-us/research/?p=505793)).
- **GaussianNexus (UIST 2025).** It is the most dangerous neighbour on rendering. A remote VR user walks a **photoreal 3DGS reconstruction of the local room**, object changes update the splat live, and a remote instructor guides the local AR user. As far as the abstracts show, though, the remote user is at 1:1 and there is no miniature ([ACM DL](https://dl.acm.org/doi/10.1145/3746059.3747693)).
- **Mosquera et al. (VRST 2026).** A remote expert uses a tabletop WIM of a *virtual* plant and a tangible avatar to guide an operator (n=29) ([arXiv 2610.26360](https://arxiv.org/abs/2610.26360)).

Outside academia, the command metaphor is long established. Incident command uses sand tables, and an XR sand table for wildfire command training reported better effectiveness and lower cognitive load ([IEEE Xplore](https://ieeexplore.ieee.org/document/10902197/)). "Sand on Fire" even lets trainers start fires by touching a tangible terrain ([ResearchGate](https://www.researchgate.net/publication/260389692_Sand_on_fire_An_interactive_tangible_3D_platform_for_the_modeling_and_management_of_wildfires)). Matterport "dollhouse" twins are used for school pre-incident planning, but offline ([Matterport](https://matterport.com/industries/case-studies/transforming-emergency-preparedness-how-digital-twin-imaging-and-matterport)). The verdict on (a) is that "a dollhouse of a real space" is not new. A **persistent, photoreal splat dollhouse of one's own home, live-linked to a person standing in it, used to start hazards**, is something we did not find. The honest framing is a "personal sand table" for a home drill.

## Giant hands reached field AR users in 2006; the trainer who also lights the fire did not

Scale-asymmetric AR–VR collaboration has a clear lineage, and reviewers from the Empathic Computing community will know it well:

- **Stafford, Piekarski and Thomas (ISMAR 2006).** This is the strongest prior art for "a giant hand seen by the person on the ground". Indoor tabletop users' hands, gestures and props were captured and reconstructed at real-world locations for outdoor AR users, to pass on situational and navigational information ([dblp](https://dblp1.uni-trier.de/rec/conf/ismar/StaffordPT06.html); [AUIC 2008 evaluation](https://crpit.scem.westernsydney.edu.au/abstracts/CRPITV76Stafford.html)).
- **CoVAR (SIGGRAPH Asia 2017).** It shared an AR user's scanned room with a VR user who could scale their body and snap to the AR user's view ([SA2017](https://sa2017.siggraph.org/attendees/emerging-technologies/event/114)).
- **Mini-Me (CHI 2018, n=16).** The VR user appeared as a *miniature* avatar that resized to stay in the AR user's view, which significantly improved social presence ([Adelaide](https://digital.library.adelaide.edu.au/items/ccd94df2-e451-473e-bb9c-aef3171a8320)).
- **Superman vs Giant (TVCG 2018).** It showed that changing IPD and eye height changes the VR user's *own* perceived body size ([ISMAR 2018](https://ismar2018.vgtc.org/papers/tvcg2018_pcs_paper_1126.html)).
- **On the Shoulder of the Giant (CHI 2019, n=24).** It makes the *local AR user* the Giant carrying a VR "Miniature" through 360 video, which is the reverse of this project's roles ([AMiner](https://www.aminer.org/pub/5ccaceaae1cd8ee42d495497/on-the-shoulder-of-the-giant-a-multi-scale-mixed-reality-collaboration)).

None of these studies a *giant* remote hand as seen by the local AR user at 1:1, and no study compared giant, life-size and miniature guide embodiments.

Handheld local devices are a minority in this literature, but they exist:

- **Gauglitz et al. (UIST 2014).** A tablet user received world-stabilised annotations from a remote user who navigated an incrementally built model ([PDF](https://sites.cs.ucsb.edu/~mturk/pubs/GauglitzUIST2014.pdf)).
- **Le Chénéchal et al. (Frontiers 2019).** This is the closest match to the project's guidance loop. A hand-worn tablet AR user was guided by an expert with a WIM-style global view of a live 3D reconstruction. A 3D arrow beat compass-plus-pointer on angular precision (**6.30° vs 8.96°, p<0.001**), while the time difference was not significant (22.09 s vs 27.11 s, p=0.07). The authors deliberately left out an expert avatar ([Frontiers](https://www.frontiersin.org/articles/10.3389/frobt.2019.00106)).
- **Grandi et al. (IEEE VR 2019, 36 participants in 18 pairs).** It paired HMD VR with *handheld* AR. VR–AR pairs beat AR–AR and roughly matched VR–VR, with balanced work participation ([ITU Pure](https://pure.itu.dk/en/publications/characterizing-asymmetric-collaborative-interactions-in-virtual-a/)). It is co-located manipulation, not navigation.

None of the handheld systems found runs in the browser on both ends.

The trainer-as-commander role is where the literature goes quiet. A VR-training review cites an **instructor controlling a virtual fire's position and intensity during an evacuation drill** ([Frontiers in VR 2021](https://doi.org/10.3389/FRVIR.2021.645153)). Patents describe trainer-injected "unexpected events" ([US 11080930](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11080930)). Commercially, FLAIM pairs a Quest trainee with an instructor iPad dashboard ([DHS market survey](https://www.dhs.gov/sites/default/files/2024-07/2024_0709_st_vrmsr%20(2).pdf)). We found no AR–VR collaboration paper in which **one remote person both injects hazards into the trainee's real space and guides them out with embodied cues**. The firefighter literature confirms the need: incident commanders lack accessible pre-incident plans ([UCF](https://www.eecs.ucf.edu/~jjl/pubs/FINAL_ARforFirefighting.pdf)), and disorientation in smoke is a leading cause of fatalities ([arXiv 2403.04660](https://arxiv.org/html/2403.04660v1)). Remote-guide research names the guide's **lack of environmental knowledge** as a recurring failure ([Kamikubo et al. CHI 2020](https://ri.cmu.edu/publications/support-strategies-for-remote-guides-in-assisting-people-with-visual-impairments-for-effective-indoor-navigation)). That is exactly what a dollhouse of the evacuee's own home plus their live position fixes, and it is the strongest motivating citation the notes produced. One caveat: this part of the search covered only about 18 queries, so claim (b) should be worded "to our knowledge".

## Ten papers reviewers will raise, and the one-line difference for each

| Prior work | What it already shows | How this project differs |
|---|---|---|
| Stoakley et al., CHI 1995 ([CMU](https://www.cs.cmu.edu/~stage3/publications/95/conferences/chi/paper.html)) | Hand-held WIM for selection, manipulation and navigation | Here the miniature is a photoreal capture of a real home, and edits reach a person physically inside it |
| Danyluk et al., CHI 2021 ([iLab](https://ilab.ucalgary.ca/publications/chi-2021-danyluk/)) | WIM design space across XR | Use its "links" and "virtuality" axes to position: cross-user, cross-device link to a real referent |
| Dollhouse VR, SIGGRAPH Asia 2015 ([history](https://history.siggraph.org/?p=193457)) | Top-down designer plus HMD occupants in the same virtual space | Real reconstructed home; occupant on a phone in the real room at 1:1; hazards, not layout |
| VirtualNexus, UIST 2024 ([arXiv](https://arxiv.org/html/2408.02914)) | VR user's WIM cut-out of a live-captured room; edits sync to a HoloLens user | Persistent whole-room splat dollhouse; AI 4D hazards; phone browser on both ends; drill purpose |
| GaussianNexus, UIST 2025 ([ACM](https://dl.acm.org/doi/10.1145/3746059.3747693)) | Remote VR user in a live 3DGS of the local room; remote instructor guides | Exocentric miniature command view, not 1:1 telepresence; hazard injection; giant-hand cue |
| Stafford et al., ISMAR 2006 ([dblp](https://dblp1.uni-trier.de/rec/conf/ismar/StaffordPT06.html)) | Indoor commanders' hands shown "god-like" to outdoor AR users | Indoor home scale; photoreal splat miniature; commander also creates the hazard; phone AR |
| Mini-Me, CHI 2018 ([Adelaide](https://digital.library.adelaide.edu.au/items/ccd94df2-e451-473e-bb9c-aef3171a8320)) | Miniature remote avatar in AR improves social presence | Opposite scale: the remote guide appears as a *giant* hand |
| On the Shoulder of the Giant, CHI 2019 ([AMiner](https://www.aminer.org/pub/5ccaceaae1cd8ee42d495497/on-the-shoulder-of-the-giant-a-multi-scale-mixed-reality-collaboration)) | AR user is the Giant, VR user the Miniature | Roles reversed: VR commander is the giant over the AR user's space |
| CoVAR, SIGGRAPH Asia 2017 ([SA2017](https://sa2017.siggraph.org/attendees/emerging-technologies/event/114)) | Shared scanned room; VR body scaling | Dollhouse-scale overview plus 1:1 hand projection, on consumer browsers |
| Grandi et al., IEEE VR 2019 ([ITU](https://pure.itu.dk/en/publications/characterizing-asymmetric-collaborative-interactions-in-virtual-a/)) | Handheld AR + HMD VR pairs perform as well as VR–VR | Remote rather than co-located; navigation and evacuation rather than manipulation |
| Le Chénéchal et al., Frontiers 2019 ([Frontiers](https://www.frontiersin.org/articles/10.3389/frobt.2019.00106)) | Expert with a WIM-like view guides a handheld-AR user's navigation with arrows | Photoreal home splat; giant hand plus arrow; expert also triggers hazards |

**Suggested wording for (a):** "World-in-miniature interfaces [Stoakley 1995; Danyluk 2021] and asymmetric dollhouse collaboration [Ibayashi 2015] are well established, and recent systems build miniatures from live captures of real rooms [VirtualNexus 2024; Duplicated Reality 2022] or let remote users walk photoreal splat reconstructions [GaussianNexus 2025]. We apply the dollhouse to a Gaussian-splat reconstruction of the participant's own home, captured with a phone, and couple it live to that participant, who stands in the real room. To our knowledge, a splat dollhouse of a person's own home has not been used as a live command view."

**Suggested wording for (b):** "Remote experts at a different scale have guided local AR users through god-like hands [Stafford 2006], adaptive miniature avatars [Mini-Me 2018] and WIM-based arrow guidance for handheld users [Le Chénéchal 2019], and handheld AR + HMD VR pairs collaborate effectively [Grandi 2019]. Our commander additionally authors the scenario: they start AI-generated 4D hazards on real objects in the trainee's home and then guide the trainee out with a giant hand and path cue, all in the browser on a consumer phone and a Quest. We found no prior system in which one remote trainer both injects hazards into the trainee's real space and guides them through it." Avoid "first" everywhere. Also avoid saying a giant hand or a dollhouse of a real space is new.

## Pair the giant hand with a ray, and always show where the evacuee is

The cue literature gives the clearest design guidance:

- **Do not rely on the hand alone.** Kim et al. found that with a *dependent* (shared) view, hand gestures were the main cue and adding sketches sped up tasks. With an *independent* view, "local workers had trouble understanding the expert's hand gestures" and the **pointer became the main cue** ([JMUI 2020](https://opus.lib.uts.edu.au/bitstream/10453/144637/2/jmui%202020.pdf)). The commander's dollhouse view and the phone user's first-person view are independent, so the giant hand should cast a **pointing ray or arrow path to the exit**. Le Chénéchal's precision result for 3D arrows backs the arrow, and stretchable "guiding arms" were faster but **less accurate** than arrows ([Frontiers](https://www.frontiersin.org/articles/10.3389/frobt.2019.00106)). Kim et al.'s CHI 2019 study also warns that every extra cue **increased mental effort** without improving co-presence ([UTS](https://opus.lib.uts.edu.au/handle/10453/139912)). A practical cue set is the hand plus one path cue plus voice. More than that adds load.
- **Keep the hand in the phone's narrow view.** Mini-Me resized and reoriented its avatar to stay in the AR user's field of view, which is a direct model for keeping a giant hand visible through a narrow phone screen.
- **Show the evacuee as a frustum plus avatar.** On the Shoulder of the Giant found a **view frustum plus complementary avatar** worked well for showing where the other person is and what they see. Drawing the phone user's live position as a frustum in the dollhouse lets the commander see their heading, not just their location.
- **Use the commander's hands for direct manipulation.** Oda et al. found **demonstrating on a virtual replica was faster than 3D pointing** ([ACM history](https://history.siggraph.org/?p=136589)). That supports starting hazards by direct manipulation in the dollhouse rather than through menus.
- **Do not count on the reconstruction for social presence.** Teo et al. found 360 video beat 3D reconstruction alone on search performance and social presence ([dblp](https://dblp.org/rec/conf/chi/TeoLLBA19)), so a splat dollhouse may feel less "present" than live video. Voice and the live frustum have to carry co-presence.
- **Do not lean on the avatar for task performance.** Avatars mainly raise social presence, not task performance, and Le Chénéchal dropped the avatar on purpose. The giant hand should be justified as a *wayfinding* cue, with presence as a side benefit.

The evidence has a gap for this project: nearly all cue studies used HMDs on both sides, so how cues behave on a phone-sized field of view is untested.

## A pilot of eight to twelve fits the 2-page format

The recent contest calls ask for a 2-page paper covering the solution, the "closest related work and how the system is novel," and "how they iterated upon the design," plus a 3–5 minute video and a live demo. Judging covers efficiency, the complexity of the collaborative interaction, novelty and fun, and the 2025 call **does not require a user study** ([IEEE VR 3DUI contest](https://ieeevr.org/dev/contribute/3dui-contest)). Older calls asked for a pilot with **at least two pairs**, measuring completion time and ease-of-use ratings, and judged "rigor of the evaluation" ([2011 call](https://web3d.org/pipermail/x3d-public_web3d.org/2011-October/001825.html)). The 2027 call has not been checked, so confirm its rules first. Comparable full papers use 16–36 participants (Mini-Me 16; Grandi 36). The contest version needs one paragraph and one small table.

A clean small design separates the two roles rather than running full real pairs:

- **Part A: participant as evacuee.** A trained experimenter acts as commander with a fixed script, and the cue varies within subjects: **voice only, giant hand plus voice, giant hand plus ray plus voice**. Voice-only is the conventional baseline, mirroring the cue comparisons in Bai et al. (CHI 2020) ([PDF](https://researchgate.net/profile/Prasanth-Sasikumar/publication/341692993_A_User_Study_on_Mixed_Reality_Remote_Collaboration_with_Eye_Gaze_and_Hand_Gesture_Sharing/links/5f017c00299bf18816037898/A-User-Study-on-Mixed-Reality-Remote-Collaboration-with-Eye-Gaze-and-Hand-Gesture-Sharing.pdf)).
- **Part B: participant as commander.** The participant uses the dollhouse while a confederate walks a fixed route, so the command view and hazard injection get rated without partner variance.
- **Order and learning effects.** Counterbalance cue order and vary hazard placement and blocked exits between trials, because repeating the same home invites learning.
- **Sample size.** About 8–12 participants (or 4–6 pairs). Report medians with Wilcoxon or Friedman tests and call the results preliminary.

| Role | Measures | Grounding |
|---|---|---|
| Evacuee (phone) | Pre-movement time (alarm to first step), evacuation time, wrong turns and dead ends, path length vs shortest path, exit choice when one exit is blocked, hazard-zone entries, all logged from phone pose | VR evacuation outcomes in [Feng et al. review](https://arxiv.org/pdf/1805.09138); decision time and route choice in [Fu et al. 2024](https://www.cise.ufl.edu/~eragan/papers/Fu2024.pdf) |
| Both roles | Raw NASA-TLX; a few Networked Minds co-presence items; ease-of-use and fun ratings (or UEQ-S) | Standard in Mini-Me and Bai 2020; fun is a contest criterion |
| Commander (Quest) | Time to locate the evacuee, re-orientation count, gesture vs speech counts, short SSQ | WIM and cue literature; SSQ because the commander views a scaled world |
| Communication | Deictic words ("here", "this way") and clarification repairs, coded from audio | Cheap test of "the hand reduces verbal effort" (no precedent citation found) |
| Iteration | 2–3 design changes from pilot feedback | Required by the contest call |

Two optional add-ons would strengthen a later full paper. One is a pre/post home-exit knowledge quiz plus self-efficacy items, Lovreglio-style; VR beat video and self-efficacy held for 3–4 weeks ([Lovreglio et al. 2021](https://link.springer.com/article/10.1007/s10055-020-00447-5/fulltext.html)). The other is an own-room vs generic-room comparison. Familiarity shortens evacuation decisions (Fu 2024), but nobody has tested drilling in one's own space against a generic one, so even a small result would be new evidence. SAGAT/SART situation-awareness probes would be new to this literature, since no AR–VR guidance paper found used them. They could be used, but not cited as convention. Do not claim real-world transfer: that evidence is thin even for VR.

### Safety and ethics mitigations

VR fire studies justify themselves as low-risk yet report "some stress" ([Lund ForensicVR](https://lup.lub.lu.se/search/files/55029056/ForensicVR_Final_Report.pdf)). Physiological checks have confirmed that VR fires induce situation-relevant anxiety ([UConn PDF](https://msl.engr.uconn.edu/paper_2020update/148_TuckeAndrew_TheEffectsOfInformationAndHazardOnEvacueeBehaviorInVirtualReality_1-s2.0-S0379711217300152-main.pdf)). Phone AR at home adds two risks VR studies do not have: **walking while looking at a screen**, and **confusing a simulated fire with a real one**. No retrieved source gives an IRB protocol for AR fire drills, so the following mitigations are proposed rather than drawn from precedent:

- Screen out people with fire-related trauma or anxiety, and let anyone opt out at any time.
- Brief participants beforehand that the hazard is simulated.
- Keep a **persistent "DRILL / SIMULATION" marker** on the phone, and style the hazards so they cannot pass for real smoke.
- Use no real alarm sounds and never trigger household smoke detectors.
- Clear the walking path and have an experimenter walk alongside as a spotter.
- Give the commander a stop button, and keep drills to a few minutes.
- Take a single-item 0–10 anxiety rating before and after, plus SSQ after.
- Debrief everyone, and get explicit consent for capturing and storing a home reconstruction.

## Citations still to verify

| Item | Issue |
|---|---|
| Danyluk et al. CHI 2021 | Full text not read: which surveyed WIMs depict captured real places, and the listed open gaps |
| GaussianNexus UIST 2025 | Authors and any overview or miniature mode unconfirmed (ACM 403); could narrow claim (a) |
| Stafford et al. ISMAR 2006 | Whether the indoor table showed a 3D miniature of the real site or a map |
| Snow Dome, CHI EA 2018 | Mechanics recalled from memory ("VR user shrinks inside a reconstruction"); no abstract retrieved |
| Dollhouse VR | Whether occupants saw the designer's hands or a giant presence; no study results found |
| Le Chénéchal "When the Giant meets the Ant" (3DCVE 2016) and Vishnu (3DCVE 2016) | Venue and content cited second-hand |
| Pausch et al. SIGGRAPH 1995; Wingrave et al. 3DUI 2006 (scaled and scrolling WIM) | Not found in search |
| Teo et al. CHI 2019 | Exact finding that 360 video beats reconstruction; which paper the later summary refers to |
| Mini-Me, Bai 2020, Grandi 2019 | Exact questionnaires, confederate use and statistics (PDFs not parsed) |
| Moon et al. IEEE Access 2024 | Local device type unconfirmed |
| Sand on Fire | Year and venue |
| Frontiers in VR 2021 review: instructor-controlled fire example | Original source paper not traced |
| Kinateder FedCSIS 2014 "ecological validity" quote; Tucker/UConn Fire Safety Journal 2017 | Attribution from snippets |
| Standard instruments (NASA-TLX, SUS, Networked Minds, SSQ, IPQ, SAGAT/SART) | Cited from memory |
| Madary and Metzinger 2016 VR ethics code | Candidate citation, not retrieved |
| 2027 3DUI contest call | Theme and evaluation rules not checked |
| HoloBots (UIST 2023) and CHI/ISMAR 2025–2026 digital-twin WIM work | Not searched; final targeted check needed |

## Conclusion

Reviewers will not reward the parts that look novel at first glance. The dollhouse, the giant hand, the handheld AR user and the splat of a real room each have a named ancestor. What we found no precedent for is the *role*: one person who holds a photoreal miniature of someone else's actual home, sets it on fire, and then reaches into that home at full scale to lead the occupant out. That role is new as a framing, and it is also what makes the system useful. It fixes the remote guide's missing environmental knowledge that the guidance literature keeps reporting.

The same literature also says where the design could fail. A hand seen from an independent viewpoint is hard to read, so the hand should be pitched as an attention-grabbing, presence-building cue sitting on top of a precise ray or arrow, not as the wayfinding cue itself. A small pilot that tests exactly that (voice vs hand vs hand plus ray) would give the contest paper both a defensible novelty claim and an empirical point no one has published: whether a giant guide's hand helps someone on a phone get out of their own home.
