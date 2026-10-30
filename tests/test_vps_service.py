"""Locating a phone frame in the live room (#133): `POST /api/localize` takes a JPEG and its lens
and answers where the camera stood in room metres, carried there by the room's splat placement.
The map is synthetic and the feature models are stand-ins, so no GPU or model is needed."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_splat_room import splat_room

from backend.app import create_app
from backend.vps.service import Positioning, in_room

K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])
SIZE = (640, 480)


def camera_at(position: tuple[float, float, float], yaw_degrees: float) -> np.ndarray:
    """A COLMAP camera (x right, y down, z forward) held level, turned `yaw` from facing +z."""
    yaw = math.radians(yaw_degrees)
    forward = np.array([math.sin(yaw), 0.0, math.cos(yaw)])
    down = np.array([0.0, 1.0, 0.0])
    camera_to_world = np.eye(4)
    camera_to_world[:3, :3] = np.column_stack([np.cross(down, forward), down, forward])
    camera_to_world[:3, 3] = position
    return camera_to_world


def seen(camera_to_world: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The pixels where `points` show, and which of them are in front and in the picture."""
    world_to_camera = np.linalg.inv(camera_to_world)
    in_camera = points @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    pixels = (in_camera @ K.T)[:, :2] / in_camera[:, 2:3]
    inside = (in_camera[:, 2] > 0.1) & (pixels >= 0).all(axis=1) & (pixels < SIZE).all(axis=1)
    return pixels, inside


class Scene:
    """Points on a wall 4 m in front of the map's one frame, each with its own descriptor."""

    def __init__(self) -> None:
        rng = np.random.default_rng(1)
        self.points = np.column_stack(
            [rng.uniform(-3, 3, 400), rng.uniform(-2, 1, 400), rng.uniform(3.5, 4.5, 400)]
        )
        descriptors = rng.normal(size=(400, 256))
        self.descriptors = (
            descriptors / np.linalg.norm(descriptors, axis=1, keepdims=True)
        ).astype(np.float32)
        self.global_descriptor = np.ones(8, dtype=np.float32)

    def write_map(self, folder: Path) -> None:
        camera = camera_at((0.0, 0.0, 0.0), 0)
        pixels, inside = seen(camera, self.points)
        (folder / "frames").mkdir(parents=True)
        np.savez(
            folder / "frames" / "frame_0000.npz",
            keypoints=pixels[inside].astype(np.float32),
            descriptors=self.descriptors[inside],
            scores=np.ones(int(inside.sum()), dtype=np.float32),
            points3d=self.points[inside],
        )
        np.savez(
            folder / "global.npz",
            names=np.array(["frame_0000.jpg"]),
            descriptors=self.global_descriptor[None],
        )
        frame = {
            "name": "frame_0000.jpg",
            "width": SIZE[0],
            "height": SIZE[1],
            "K": K.tolist(),
            "camera_to_world": camera.tolist(),
            "keypoints": int(inside.sum()),
        }
        manifest = {"version": 1, "frame": "splat", "local_model": "test", "global_model": "test"}
        (folder / "map.json").write_text(json.dumps(manifest | {"frames": [frame]}))


class Phone:
    """Stands in for the feature models: the phone's frame shows the scene from `camera`."""

    def __init__(self, scene: Scene, camera: np.ndarray) -> None:
        self.scene = scene
        self.camera = camera
        self.frames: list[bytes] = []

    def local(self, image):
        self.frames.append(image.read())
        pixels, inside = seen(self.camera, self.scene.points)
        scores = np.ones(int(inside.sum()), dtype=np.float32)
        return pixels[inside].astype(np.float32), self.scene.descriptors[inside], scores

    def global_descriptor(self, image):
        return self.scene.global_descriptor


# The room's splat placement: twice the size, turned a quarter left about the vertical, moved.
PLACEMENT = {
    "position": {"x": 1.0, "y": 0.5, "z": -1.0},
    "rotation": {"x": 0.0, "y": math.sin(math.pi / 4), "z": 0.0, "w": math.cos(math.pi / 4)},
    "scale": 2.0,
}


def room_with_map(tmp_path: Path, scene: Scene) -> Path:
    directory = splat_room(tmp_path)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["splat"] |= PLACEMENT
    (directory / "manifest.json").write_text(json.dumps(manifest))
    scene.write_map(directory / "vps")
    return directory


def post_frame(client: TestClient, jpeg: bytes = b"\xff\xd8 a frame"):
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    return client.post(
        "/api/localize",
        files={"image": ("frame.jpg", jpeg, "image/jpeg")},
        data={"fx": fx, "fy": fy, "cx": cx, "cy": cy, "width": SIZE[0], "height": SIZE[1]},
    )


def test_a_frame_is_located_in_room_metres(tmp_path):
    scene = Scene()
    truth = camera_at((0.4, -0.1, 0.6), yaw_degrees=12)
    phone = Phone(scene, truth)
    app = create_app(room_with_map(tmp_path, scene), tmp_path / "data", Positioning(lambda: phone))

    response = post_frame(TestClient(app), b"\xff\xd8 the frame")

    assert response.status_code == 200, response.text
    fix = response.json()
    assert fix["located"] is True
    assert fix["inliers"] >= 30
    assert phone.frames == [b"\xff\xd8 the frame"]
    # Turned a quarter left (x becomes -z), twice as large, then moved.
    assert fix["position"] == pytest.approx(
        {"x": 1.0 + 2 * 0.6, "y": 0.5 + 2 * -0.1, "z": -1.0 - 2 * 0.4}, abs=1e-3
    )
    # The room camera looks down its -z: the map camera's forward turned a quarter left.
    q = fix["orientation"]
    forward = -np.array(
        [
            2 * (q["x"] * q["z"] + q["y"] * q["w"]),
            2 * (q["y"] * q["z"] - q["x"] * q["w"]),
            1 - 2 * (q["x"] ** 2 + q["y"] ** 2),
        ]
    )
    expected = np.array([math.sin(math.radians(12)), 0, math.cos(math.radians(12))])
    assert forward == pytest.approx([expected[2], 0, -expected[0]], abs=1e-3)
    assert fix["room_version"] == 1
    assert set(fix["seconds"]) >= {"features", "matching", "solve", "total"}


def test_a_frame_of_something_else_is_answered_without_a_place(tmp_path):
    scene = Scene()
    # Facing away from every map point.
    phone = Phone(scene, camera_at((0.0, 0.0, 0.0), yaw_degrees=180))
    app = create_app(room_with_map(tmp_path, scene), tmp_path / "data", Positioning(lambda: phone))

    fix = post_frame(TestClient(app)).json()

    assert fix["located"] is False
    assert fix["position"] is None and fix["orientation"] is None
    assert fix["reason"]


def test_a_room_without_a_positioning_map_refuses(tmp_path):
    def no_models():
        raise AssertionError("the models must not load for a room without a map")

    app = create_app(splat_room(tmp_path), tmp_path / "data", Positioning(no_models))

    response = post_frame(TestClient(app))

    assert response.status_code == 404
    assert response.json()["detail"] == "The live room has no positioning map."


def test_a_server_without_the_models_says_so(tmp_path):
    def no_models():
        raise ImportError("No module named 'torch'")

    app = create_app(room_with_map(tmp_path, Scene()), tmp_path / "data", Positioning(no_models))

    response = post_frame(TestClient(app))

    assert response.status_code == 503
    assert "No module named 'torch'" in response.json()["detail"]


def test_an_oversized_frame_is_refused(tmp_path):
    scene = Scene()
    app = create_app(
        room_with_map(tmp_path, scene),
        tmp_path / "data",
        Positioning(lambda: Phone(scene, camera_at((0.0, 0.0, 0.0), 0))),
    )

    assert post_frame(TestClient(app), b"x" * (1024 * 1024 + 1)).status_code == 413


def test_without_a_placement_the_map_frame_is_the_room() -> None:
    camera = camera_at((0.5, -1.4, 2.0), yaw_degrees=0)

    position, orientation = in_room(camera, None)

    assert position == pytest.approx((0.5, -1.4, 2.0))
    # COLMAP's camera has y down and looks down +z; the room camera has y up and looks down -z:
    # it is turned half round about x.
    assert np.abs(orientation) == pytest.approx((1, 0, 0, 0), abs=1e-6)
