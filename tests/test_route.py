"""A walkable route across the room's floor (#275): round furniture and the fire, to a goal."""

import math

import pytest

from backend.prepared_room import EntitySize, Position, Rotation, SceneEntity
from backend.route import FIRE_CLEARANCE, FloorGrid, length, route


def entity(
    id_: str, x: float, z: float, width: float, depth: float, height: float = 0.5
) -> SceneEntity:
    return SceneEntity(
        id=id_,
        label=id_,
        asset_url="/a.glb",
        node=id_,
        kind="static",
        selectable=False,
        size=EntitySize(width=width, height=height, depth=depth),
        position=Position(x=x, y=0.0, z=z),
        rotation=Rotation(),
    )


# A 4 x 3 m room (floor from x -2..2, z -1.5..1.5), with a bed across its middle, from the left
# wall to x = 0.5, leaving a way round its right end.
FLOOR = entity("floor", 0.0, 0.0, 4.0, 3.0, 0.02)
BED = entity("layout_bed_1", -0.75, 0.0, 2.5, 1.0)
ROOM = [FLOOR, BED]


def crosses(points, box) -> bool:
    """Whether the polyline passes over the box's footprint."""
    x0, x1 = box.position.x - box.size.width / 2, box.position.x + box.size.width / 2
    z0, z1 = box.position.z - box.size.depth / 2, box.position.z + box.size.depth / 2
    for (ax, az), (bx, bz) in zip(points, points[1:], strict=False):
        for i in range(101):
            x, z = ax + (bx - ax) * i / 100, az + (bz - az) * i / 100
            if x0 < x < x1 and z0 < z < z1:
                return True
    return False


def test_the_route_goes_round_the_bed_not_through_it():
    way = route(ROOM, (-1.0, -1.1), (-1.0, 1.1))
    assert way is not None
    assert not crosses(way, BED)
    # Round the bed's free end, past x = 0.5.
    assert max(x for x, _ in way) > 0.5
    assert way[0] == (-1.0, -1.1) and way[-1] == (-1.0, 1.1)


def test_with_nothing_in_the_way_it_is_one_straight_leg():
    way = route([FLOOR], (-1.0, 0.0), (1.0, 0.0))
    assert way == [(-1.0, 0.0), (1.0, 0.0)]
    assert length(way) == pytest.approx(2.0)


def test_the_burning_object_is_kept_further_away():
    fire = entity("layout_desk_1", 0.0, 0.0, 0.8, 0.6)
    grid = FloorGrid([FLOOR, fire], fires={"layout_desk_1"})
    # A point just beyond a person's clearance is still blocked next to a fire.
    assert not grid.free(grid.cell((0.0, 0.3 + 0.4)))
    way = route([FLOOR, fire], (-1.5, 0.0), (1.5, 0.0), fires={"layout_desk_1"})
    assert way is not None
    nearest = min(
        math.dist(point, (0.0, 0.0))
        for (ax, az), (bx, bz) in zip(way, way[1:], strict=False)
        for point in [(ax + (bx - ax) * i / 50, az + (bz - az) * i / 50) for i in range(51)]
    )
    assert nearest >= 0.3 + FIRE_CLEARANCE - 0.15


def test_a_goal_inside_furniture_is_moved_to_the_nearest_free_floor():
    way = route(ROOM, (1.5, -1.0), (-0.75, 0.0))
    assert way is not None and not crosses(way[:-1], BED)


def test_when_the_way_is_closed_there_is_no_route():
    # A wall of furniture right across the room.
    barrier = entity("layout_wardrobe_1", 0.0, 0.0, 4.0, 0.4, 2.0)
    assert route([FLOOR, barrier], (0.0, -1.0), (0.0, 1.0)) is None


def test_flat_things_like_rugs_are_walked_over():
    rug = entity("layout_rug_1", 0.0, 0.0, 2.0, 1.5, 0.01)
    assert route([FLOOR, rug], (-1.0, 0.0), (1.0, 0.0)) == [(-1.0, 0.0), (1.0, 0.0)]
