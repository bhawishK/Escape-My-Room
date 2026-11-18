# Room refinement experiment (#206)

Can an LLM agent refine a reconstructed room's splat into one with a proper floor and walls,
using everything the pipeline produced, without changing its calibration? Inputs are copied from
the desktop into `data/refine/<room>/` (git-ignored): `room.ply`, `room-phone.ply`, `manifest.json`,
`report.json`, the COLMAP model (`best/`) and the frames.

| Script | What it does |
| --- | --- |
| `splat.py` | Reads and writes splat PLY files; places them in room metres as the manifest says |
| `cameras.py` | The frames' cameras from COLMAP's binary model, in room metres (the report's cameras are in the splat's own frame) |
| `look.py` | The room from above and the side, and splats by height |
| `fix_floor.py` | Puts the floor on the real floor and rescales from the camera height; only the placement changes |
| `walls.py` | A first, automatic guess at the four walls (fooled by beds; judged by hand after) |
| `refine.py` | Removes floaters, flattens the floor, fills floor and walls with discs coloured from the frames, adds wall entities |
| `compare.py` | Splats drawn as dots through the frames' cameras (misleading: misses faint splats) |
| `render.py` | Spark renders of rooms from filmed views and from above, beside the frames |
| `holes.py` | Where the room is see-through, as Spark draws it, from the filmed path, standing spots and the dollhouse's views |

Findings and the plan are on #206.
