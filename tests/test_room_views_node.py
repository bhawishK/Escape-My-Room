"""The room renderer runs the Node set in ESCAPE_ROOM_NODE, as physics does. #223's pictures
failed under the server's service, which found an old system Node on its path."""

import sys

import pytest

from backend import room_views
from backend.room_views import RenderFailure, View, render_views

SPLAT_ROOM = room_views.FRONTEND.parent / "assets" / "splat-room"
VIEW = View(position=(0.0, 1.0, 2.0), look_at=(0.0, 0.5, 0.0))
OLD_NODE_ERROR = "SyntaxError: Unexpected reserved word"


def stand_in_node(folder, ran):
    """A Node that notes it ran, then fails as an old Node does on the render script."""
    if sys.platform == "win32":
        fake = folder / "fake-node.cmd"
        script = f'@echo off\necho ran> "{ran}"\necho {OLD_NODE_ERROR} 1>&2\nexit /b 1\n'
        fake.write_text(script.replace("\n", "\r\n"))
    else:
        fake = folder / "fake-node"
        fake.write_text(f'#!/bin/sh\necho ran > "{ran}"\necho "{OLD_NODE_ERROR}" >&2\nexit 1\n')
        fake.chmod(0o755)
    return fake


def test_the_node_in_the_setting_is_the_one_run(monkeypatch, tmp_path):
    if not (room_views.FRONTEND / "dist" / "render.html").is_file():
        pytest.skip("the render page is not built")
    ran = tmp_path / "ran.txt"
    monkeypatch.setenv("ESCAPE_ROOM_NODE", str(stand_in_node(tmp_path, ran)))
    with pytest.raises(RenderFailure, match="Unexpected reserved word"):
        render_views(SPLAT_ROOM, [VIEW])
    assert ran.is_file()
