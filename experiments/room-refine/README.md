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
| `make_room.py` | A room from a retrained splat, with a calibrated room's placement (#209) |
| `retrain_variants.sh` | On the desktop: retrain the live room four ways (as now, needle penalty, depth guidance, both) and build each into a room (#209) |
| `export_points.py` | A room as a z-up point cloud in metres, for SpatialLM |

## After the desktop's reboot

1. **Retrain (#209):** in a worktree of the branch, so the server's checkout is untouched:
   ```bash
   git -C ~/escape-my-room fetch
   git -C ~/escape-my-room worktree add ~/escape-my-room-209 origin/issue-209-depth-training
   bash ~/escape-my-room-209/experiments/room-refine/retrain_variants.sh
   ```
   About 10 minutes per variant. Each prints its held-out PSNR, splat and needle counts; rooms land in `data/refine-209/<A-D>/room`.
2. **Compare:** copy the four rooms to the laptop and run `holes.py` on each, and `render.py` across them.
3. **SpatialLM (#206 step 2):** install per its README (Python 3.11, CUDA 12.4 toolkit, `poe install-sonata`), export with `export_points.py`, then
   `python inference.py --point_cloud room-zup.ply --output layout.txt --model_path manycore-research/SpatialLM1.1-Qwen-0.5B`,
   and compare its walls with the hand-judged ones (`data/refine/walls-v8.json`: 4.0 × 2.87 m).

Findings and the plan are on #206.
