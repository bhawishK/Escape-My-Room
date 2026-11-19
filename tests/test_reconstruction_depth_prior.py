"""Depth priors for splat training (#209): a monocular depth model's relative depth, fitted to
metres per frame by the COLMAP points that frame sees, and the needle measure."""

import numpy as np
import pytest

from backend.reconstruction.depth_prior import (
    fit_inverse_depth,
    metric_depth,
    needle_excess,
    seen_points,
)

K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])


def facing_wall(distance: float = 3.0) -> tuple[dict, np.ndarray]:
    """A camera at the origin looking along +z (COLMAP: x right, y down, z forward) at a wall that
    fills its frame."""
    camera = {"K": K, "camera_to_world": np.eye(4), "width": 640, "height": 480}
    rng = np.random.default_rng(0)
    wall = np.column_stack(
        [rng.uniform(-1.8, 1.8, 400), rng.uniform(-1.4, 1.4, 400), np.full(400, distance)]
    )
    return camera, wall


def relative_inverse_depth(
    true_depth: np.ndarray, scale: float = 7.0, shift: float = 0.4
) -> np.ndarray:
    """What a monocular model gives: inverse depth up to an unknown scale and shift."""
    return (1 / true_depth - shift) / scale


def test_the_points_a_frame_sees_land_on_its_pixels_with_their_depth() -> None:
    camera, wall = facing_wall(3.0)
    pixels, depths = seen_points(camera, wall)
    assert len(pixels) == len(wall)
    assert np.allclose(depths, 3.0)
    # A point 1 m right and 0.6 m down is 500 * (1/3) px right and 100 px down of the centre.
    one = seen_points(camera, np.array([[1.0, 0.6, 3.0]]))[0][0]
    assert one == pytest.approx([320 + 500 / 3, 240 + 100])


def test_points_behind_or_outside_the_frame_are_not_seen() -> None:
    camera, _ = facing_wall()
    pixels, _ = seen_points(camera, np.array([[0.0, 0.0, -2.0], [50.0, 0.0, 3.0], [0.0, 0.0, 2.0]]))
    assert len(pixels) == 1


def test_a_relative_depth_map_is_fitted_to_metres_by_the_points_the_frame_sees() -> None:
    # A room seen face on: depth rising from 2 m at the top of the frame to 5 m at the bottom.
    rows = np.linspace(2.0, 5.0, 480)[:, None] * np.ones((1, 640))
    relative = relative_inverse_depth(rows)
    rng = np.random.default_rng(1)
    pixels = np.column_stack([rng.uniform(0, 639, 300), rng.uniform(0, 479, 300)])
    sparse = rows[pixels[:, 1].astype(int), pixels[:, 0].astype(int)]

    fit = fit_inverse_depth(relative, pixels, sparse)
    assert fit is not None
    assert np.allclose(metric_depth(relative, fit), rows, rtol=1e-3)


def test_the_fit_ignores_a_fifth_of_the_points_being_wrong() -> None:
    # COLMAP points hidden behind something nearer, or badly matched, disagree with the image.
    rows = np.linspace(2.0, 5.0, 480)[:, None] * np.ones((1, 640))
    relative = relative_inverse_depth(rows)
    rng = np.random.default_rng(2)
    pixels = np.column_stack([rng.uniform(0, 639, 300), rng.uniform(0, 479, 300)])
    sparse = rows[pixels[:, 1].astype(int), pixels[:, 0].astype(int)].copy()
    sparse[:60] *= rng.uniform(1.5, 3.0, 60)

    fit = fit_inverse_depth(relative, pixels, sparse)
    assert fit is not None
    assert np.allclose(metric_depth(relative, fit), rows, rtol=0.02)


def test_too_few_points_or_a_backwards_fit_give_no_depth_for_that_frame() -> None:
    relative = np.ones((480, 640))
    assert fit_inverse_depth(relative, np.array([[10.0, 10.0]] * 5), np.full(5, 2.0)) is None
    # Nearer points with smaller relative inverse depth: the model and the points disagree.
    rows = np.linspace(2.0, 5.0, 480)[:, None] * np.ones((1, 640))
    pixels = np.column_stack([np.full(100, 300.0), np.linspace(0, 479, 100)])
    backwards = 1 / rows[pixels[:, 1].astype(int), 300]
    assert fit_inverse_depth(relative_inverse_depth(rows), pixels, backwards * 10) is None


def test_metric_depth_is_zero_where_the_fit_gives_no_positive_depth() -> None:
    relative = np.array([[1.0, -10.0]])
    depth = metric_depth(relative, (0.5, 0.0))
    assert depth[0, 0] == pytest.approx(2.0)
    assert depth[0, 1] == 0.0


def test_a_needle_is_a_splat_whose_longest_axis_outgrows_the_next_past_the_limit() -> None:
    # Extents as gsplat keeps them: logs of the three axes, in any order.
    scales = np.log(
        np.array(
            [
                [0.1, 0.1, 0.1],  # round
                [0.5, 0.1, 0.1],  # 5x long: fine
                [0.1, 2.0, 0.1],  # 20x long: a needle, 10 past
                [0.1, 0.1, 0.001],  # a flat disc, as on a wall: wanted, not a needle
                [3.0, 0.2, 0.001],  # a long thin strip: 15x longer than wide, 5 past
            ]
        )
    )
    assert needle_excess(scales, limit=10.0) == pytest.approx([0.0, 0.0, 10.0, 0.0, 5.0])


def test_depth_maps_are_made_at_the_size_training_shrinks_each_frame_to() -> None:
    from backend.reconstruction.depth_prior import training_size

    # A portrait phone frame, 1080 x 1920, trained at 1600 on its long side; smaller frames stay.
    assert training_size(1080, 1920, 1600) == (900, 1600, pytest.approx(1600 / 1920))
    assert training_size(900, 1600, 1600) == (900, 1600, 1.0)


def test_depth_comes_before_training_and_only_its_settings_rerun_it(tmp_path) -> None:
    from dataclasses import replace

    from backend.reconstruction.pipeline import Settings, stage_settings
    from backend.reconstruction.stages import video_to_room

    stages = {stage.name: stage for stage in video_to_room(tmp_path / "video.mov", tmp_path)}
    assert list(stages) == ["frames", "colmap", "level", "depth", "splat", "vps_map", "package"]
    # Turning depth guidance or the needle penalty on retrains the splat, not the frames or COLMAP.
    on = replace(Settings(), depth_weight=0.1, anisotropy_weight=0.1)
    changed = {
        name
        for name, stage in stages.items()
        if stage_settings(stage, on) != stage_settings(stage, Settings())
    }
    assert changed == {"depth", "splat"}
    # Off by default: training is as it was.
    assert Settings().depth_weight == 0 and Settings().anisotropy_weight == 0
