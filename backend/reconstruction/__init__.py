"""Room video → splat room package, on the GPU desktop (#134, #135).

    python -m backend.reconstruction VIDEO OUT

Stages: frames, COLMAP, levelling, splat training, the positioning map (#133), and the package.
OUT ends up holding `room.ply`, `report.json`, `previews/` and `vps/`, which
`assets/splat-room/build_room.py` turns into a room. Intermediate files are kept in `OUT/work/`, so
a run that was stopped continues from the last finished stage.
"""
