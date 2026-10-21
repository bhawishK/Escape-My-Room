# Issue #60: iPhone 8th Wall tracking check

Status: **The 8th Wall engine runs in iPhone Chrome and tracks without its camera image. It lost tracking four times in three minutes, and the page did not yet handle the losses.** The run was free movement, not the tape-mark routine, so it says when tracking works and fails, not how accurate it is in metres.

## Run

- **Date:** 21 October 2026. The room view opened at 18:47:21 UTC.
- **Device:** iPhone (the project's iPhone 16; the browser does not report the model), iOS 26.6.1, Chrome 155.0.8059.37 (`CriOS`). The page was served through a Cloudflare tunnel.
- **Code:** `main` after PRs #70–#72: measured tracking (#59) and the movement log.
- **Movement:** the user walked around freely for about three minutes.
- **Evidence:** the full movement log is [2026-10-21-iphone-8thwall-movement-log.json](device-reports/2026-10-21-iphone-8thwall-movement-log.json). **Send log** was tapped five times in one session, four of them within 5 s; the last log contains all the others.
- **Size:** 3 min 29 s, with 1,760 poses at about 9.4 a second, so the page drew at 10 frames a second or more.
- **Room view:** open 0–182 s, closed for 23 s, reopened at 205 s.

## Engine or fallback

The engine ran for the whole session. The log records a single mode choice, `measured`, and no fallback to step counting.

| Question from #60 | Answer |
| --- | --- |
| Does the engine start in iPhone Chrome? | Yes. The camera was requested at 0.75 s, the stream was ready at 2.93 s, and video at 3.27 s. |
| Does it run without its camera-feed and three.js modules? | Yes. It produced poses with only its tracking module and ours, and our renderer drew the room from them. No follow-up is needed for adopting the engine's scene. |
| Time to the first tracked pose | First engine pose at 3.3 s. `NORMAL` tracking at 14.1 s, after 10.7 s of `LIMITED INITIALIZING`. On reopening, the camera was ready in 0.9 s. |
| Does the room view move with the phone? | Yes, while tracking is `NORMAL`. During losses it flew off; see below. |

## Timeline

Times are seconds since the room view opened. Height is the engine's height above the floor.

| Time | Engine status | Where it put the phone | Verdict |
| --- | --- | --- | --- |
| 0–3.4 | Camera opening | Start, waiting | Fine |
| 3.4–14.1 | `LIMITED INITIALIZING` | Height about 1.0 m, barely moving | Normal start-up, but slow |
| **14.1–36.1** | **`NORMAL`** | Height about 1.3 m, within 2.3 m of the start | **Good**, apart from one frame at 0.20 m high at 14 s |
| 36.1–48.1 | Lost: `LIMITED INITIALIZING` | Height 10–14 m, up to 14.5 m away | Garbage |
| 48.1–100.8 | `NORMAL` | Height 1.7–3.6 m, up to 6.6 m away | Tracking, but about 1 m too high after the loss |
| 100.8–104.3 | Lost | Height 15–18 m, up to 32 m away | Garbage |
| **104.3–159.5** | **`NORMAL`** | Height 0.5–1.3 m (median 0.83), within 4.2 m | **Mostly sensible**; height low, likely offset |
| 159.5–174.5 | Lost | Height 20–38 m, 55 m away; a 56 m jump in 0.1 s | Garbage |
| 174.5–176.9 | `NORMAL` | Height about 4 m | Offset |
| 176.9–182.1 | Lost, then the view was closed | Height 30–40 m | Garbage |
| 205–209 | Reopened and initialising | Start | Restarted cleanly |

**Totals:**
- `NORMAL` for about 132 s of 182 s.
- Initialising or lost for about 50 s.
- Positions were sensible for only about 77 s: 14–36 s and 104–159 s.

## Why it looked unstable

**1. The engine lost tracking four times, each time pointing steeply at the floor and turning fast.**

| Loss at | Tilt down in the 2 s before | Fastest turn |
| --- | --- | --- |
| 36.1 s | up to 79° | 120°/s |
| 100.8 s | up to 60° | 260°/s |
| 159.5 s | up to 81° | 148°/s |
| 176.9 s | up to 69° | 136°/s |

Over the session, the phone pointed down about 43° on average, and more than 45° down 43% of the time. A plain floor gives the camera little detail, and fast turns blur it. Carrying the box by aiming the screen centre at the floor encourages this.

**2. The page passed the engine's garbage straight through.** While the engine was `LIMITED`:
- The room view moved to its positions, so the room flew away.
- Python and the headset were told `tracked` throughout, so the phone marker flew off too.

Holding the view and reporting `lost` is Issue #61, not yet built at the time of the run.

**3. After each recovery the room no longer lined up.** The re-initialised map does not match the old start. Height came back about 1 m too high after the first loss, and low after the second. Nothing re-aligns it yet: Recentre is Issue #62.

**4. Shake while tracking is good is small.** Each pose's distance from the average of its neighbours over about 0.4 s, which includes real hand movement:

| Stretch | Typical | Worst 10% | Tilt |
| --- | --- | --- | --- |
| 14–36 s | 1.7 cm | 6.5 cm | 0.6° |
| 48–100 s | 2.9 cm | 9.4 cm | 0.6° |
| 104–159 s | 1.3 cm | 3.4 cm | 0.5° |

A different renderer, such as Spark.js splats, would not steady the view. It draws from the same pose, and a heavy splat could lower the frame rate.

**Smaller points:**
- Start-up took 14 s in total.
- **Send log** was tapped four times in 5 s, so its confirmation on the status line is easy to miss.

## Next

1. **#61:** hold the view at the last good pose and report `lost` while the engine is `LIMITED`, with a hint to point at something with detail and move slower.
2. **#62:** Recentre, and consider re-aligning automatically when the engine recovers.
3. **Floor aiming:** place objects by aiming a little ahead instead of steeply down, or warn when the phone points down too far.
4. **Optional smoothing** for the remaining 1–3 cm shake, after 1 and 2.
5. **An accuracy run** with the tape-mark routine in [phone tracking](phone-tracking.md#movement-log-for-device-checks), once 1–3 are in.
