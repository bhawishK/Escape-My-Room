# Locating the phone from Qwen's landmarks (spike #110)

8th Wall moves the phone's view smoothly but drifts, misjudges scale and freezes while it is lost (the hallway walk of 27 October 2026). The question was whether Qwen's object boxes can locate a camera in a splat room well enough to correct it (#101). This spike ran on the laptop only, against the hallway room.

## How it works

- **Boxes.** `backend/boxes.py` reads Qwen's labelled `bbox_2d` answers. It is shared with #33's door boxes.
- **Landmark map.** `backend/landmarks.py` `build_landmarks`:
  1. asks for labelled objects in views rendered round a few spots along the walk;
  2. places each box in the room at the depth of the nearer half of its splats;
  3. merges sightings into landmarks: one label within 0.8 m, or any labels within 0.25 m, so one object Qwen names two ways answers to both.

  The result is written to the room as `landmarks.json`: ID, label, aliases, centre, how often it was seen, and the views it was seen in.
- **Locating.** `solve_pose` fits the camera's position and heading to the landmarks' box centres, with the tilt known (the phone measures it from gravity). The fit is robust:
  - every pair of sightings gives candidate poses, and the one most sightings agree with is refitted on those;
  - three agreeing landmarks fix the pose;
  - two landmarks fit more than one pose exactly, so they fix it only within 1 m of a rough place, such as 8th Wall's pose;
  - `locate` says why there is no fix: fewer than two landmarks, two with no rough place, or no fit.
- **The tool.** `python -m backend.landmarks_check build|evaluate data/splat-room` saves views with the boxes drawn on, and a report, under `data/landmarks/`. It costs about $0.0001 a view.

## Results on the hallway room (27 October 2026)

**Map** (24 views round 3 spots, $0.003):

| Landmark | Seen | Notes |
|---|---|---|
| door | 6 | |
| sink | 7 | |
| cupboard | 4 | also named "door" by Qwen (an alias) |
| vanity cupboard | 2 | |
| waste bin | 2 | |

The mirror was left out: the splats behind a mirror are the reflected room, so its depth is wrong. A sink seen in it was placed 1.3 m too far.

**Evaluation** (16 phone-like views: portrait, 1.4 m up, tilted 15° down, at 4 spots along the walk, looking down the hallway and back; $0.0024):

| | Views fixed | Median error | Worst |
|---|---|---|---|
| Landmarks alone (3 or more agreeing) | 1 of 16 (6%) | 0.10 m | 0.10 m |
| With a rough place 0.5 m off, standing in for 8th Wall | 3 of 16 (19%) | 0.11 m | 0.60 m |

- **Views:** 9 of 16 had two or more map objects in view. The 4 views looking back the way the walk came saw only empty splat.
- **Speed and cost:** 2.7 s and about $0.00015 per fix.
- **Boxes:** Qwen's boxes were mostly within 0.01–0.05 of the view from where the landmarks truly project. Now and then one is off centre (a door half out of view or seen edge-on) or names the wrong object. The robust fit leaves those out.
- **Without the robust fit:** fits from exactly two landmarks were metres off (median 2.4 m), turned 40–170°. Without a rough place they are refused.

## Decision

**Accurate enough, but too rarely available to correct 8th Wall continuously in this hallway.**

- **Accuracy:** when a fix is given it is about 10 cm off, well within the 30 cm aim. The worst, 0.6 m, came from two landmarks where the rough place picked between two poses.
- **Availability:** only 6% of views on their own, 19% with 8th Wall's rough place. A plain hallway has few objects, and a phone's narrow portrait view rarely holds three of them.

So for #101:
1. **Start anywhere:** the person deliberately shows the phone two or three objects at the start. This is the strongest use, and worth building.
2. **Occasional correction:** take a fix whenever two or more landmarks come into view, with 8th Wall's pose as the rough place, and blend it in. Do not expect one every few seconds.
3. **Scale:** two fixes metres apart are needed, so this happens rarely in this room. A scale from the phone's measured height (8th Wall's height against the real one) is a cheaper first step.

## Why these numbers may be optimistic

- **Rendered views, not camera frames.** The test views are rendered from the same splat the map came from. A real phone frame looks different: sharper, different light, people in it. **Test on frames from the phone before building #101's phone part.**
- **Known height and tilt.** The true camera height (1.4 m) equals the solver's gentle height preference, the tilt is given exactly, and roll is zero.
- **Spots near the map.** The test spots lie between the map's spots along the same walk.
- **Small sample.** The rates come from 16 views. For 3 fixes, the 90th percentile is the worst one.

## Not done

- No landmark sizes; centres only.
- No more object types. Wall sockets, switches, pictures or the ceiling light would raise availability.
- The least-squares solver stays in `landmarks.py` until #101 needs it elsewhere.
