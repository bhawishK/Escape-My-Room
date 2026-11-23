"""Fires kept for the live room (#235): found again whatever the wording's case or spacing,
listed, deleted, and made in advance so a demo never waits. HTTP seam, real service, fixture
generator."""

import time
from typing import Any

import httpx
from test_drill import cache
from test_hazard_generation import GENERATOR, splat_room

from backend.hazard_generation import normalised_hazard


def library(url: str) -> list[dict[str, Any]]:
    return httpx.get(f"{url}/api/hazards", timeout=5).json()["fires"]


def test_wording_is_compared_without_case_spacing_or_a_final_full_stop():
    assert normalised_hazard("  Catches   Fire. ") == "catches fire"
    assert normalised_hazard("catches fire") == "catches fire"
    assert normalised_hazard("is flooded!") == "is flooded"


def test_the_live_rooms_fires_are_listed_and_one_can_be_deleted(start_service, tmp_path):
    room = splat_room(tmp_path)
    data = tmp_path / "data"
    kept = cache(data, room, "block")
    with start_service(data, **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        (fire,) = library(url)
        assert fire["id"] == kept.id
        assert fire["object"] == "block" and fire["hazard"] == "catches fire"
        assert fire["frames"] == kept.frames and fire["size_bytes"] == kept.size_bytes

        assert httpx.delete(f"{url}/api/hazards/{kept.id}", timeout=5).status_code == 204
        assert library(url) == []
        assert httpx.get(f"{url}/api/hazards/{kept.id}/frames/0.spz", timeout=5).status_code == 404
        assert httpx.delete(f"{url}/api/hazards/{kept.id}", timeout=5).status_code == 404
        assert httpx.delete(f"{url}/api/hazards/not-a-fire", timeout=5).status_code == 404


def test_fires_made_in_advance_skip_those_already_made_and_are_then_listed(start_service, tmp_path):
    room = splat_room(tmp_path)
    data = tmp_path / "data"
    with start_service(data, **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        asked = httpx.post(
            f"{url}/api/hazards/in-advance", json={"objects": ["block"]}, timeout=5
        ).json()
        assert [job["target"] for job in asked["jobs"]] == [{"entity": "block"}]
        assert asked["already"] == []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not library(url):
            time.sleep(0.2)
        (fire,) = library(url)
        assert fire["object"] == "block"

        # Asked again, it is already made: no new job.
        again = httpx.post(
            f"{url}/api/hazards/in-advance",
            json={"objects": ["block"], "hazard": "Catches fire."},
            timeout=5,
        ).json()
        assert again["jobs"] == [] and again["already"] == ["block"]


def test_in_advance_with_no_objects_named_means_every_object_but_floor_and_walls(
    start_service, tmp_path
):
    room = splat_room(tmp_path)
    data = tmp_path / "data"
    cache(data, room, "block")
    with start_service(data, **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        asked = httpx.post(f"{url}/api/hazards/in-advance", json={}, timeout=5).json()
        targets = sorted(job["target"]["entity"] for job in asked["jobs"]) + asked["already"]
        # The splat room's box, the block (already made); never the floor.
        assert sorted(targets) == ["block", "box"]
        assert asked["already"] == ["block"]
        assert (
            httpx.post(
                f"{url}/api/hazards/in-advance", json={"objects": ["nothing_here"]}, timeout=5
            ).status_code
            == 422
        )
