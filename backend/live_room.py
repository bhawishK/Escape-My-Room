"""Which prepared room is live, and making a reconstructed room live without restarting (#138).

The live room starts as the one the server settings name (`ESCAPE_ROOM_PREPARED_DIR`). Making a
reconstruction live builds it with `assets/splat-room/build_room.py` into a new folder,
`<data>/rooms/<job id>-v<room version>/`, so the room being served is never touched. It records
the room in `<data>/live-room.json`, which a restart reads, so the choice outlasts the process; if
that room's folder has gone, the configured room is served instead. Each change gets a room
version one higher than any before it, so connected devices always see a new version and reload.
Restore makes the room before the live one live again, under a new version; no room's own files
are changed.
"""

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from pydantic import ValidationError

from backend.errors import Refusal
from backend.prepared_room import LoadedRoom, PreparedRoomError, load_prepared_room
from backend.protocol import WireModel
from backend.records import now, write_json


class LiveRoomError(Refusal):
    """The live room cannot be changed; the message is shown to the user."""


class LiveEntry(WireModel):
    directory: str
    room_version: int
    # The reconstruction job it was built from; None for the room the server settings name.
    job_id: str | None
    made_live_at: str


class LiveRoomSummary(WireModel):
    """What is live, for the review page."""

    # The reconstruction job it was built from; None for the room the server settings name.
    job_id: str | None
    room_version: int | None
    made_live_at: str | None
    floor_width_m: float | None
    floor_depth_m: float | None
    scale_source: str | None
    # Whether the room has its map from above (#124), and the positioning map (#133).
    overview_map: bool
    positioning_map: bool
    can_restore: bool


class LiveHistory(WireModel):
    # Oldest first; the last entry is live.
    entries: list[LiveEntry]


class LiveRooms:
    def __init__(self, data: Path, configured: Path) -> None:
        self.path = data / "live-room.json"
        self.rooms = data / "rooms"
        self.configured = configured
        self.history = self._read()

    @property
    def live(self) -> LiveEntry | None:
        """The room made live here, or None while the configured room is live."""
        return self.history.entries[-1] if self.history.entries else None

    @property
    def directory(self) -> Path:
        """The live room's folder; the configured room's, if the live one has gone."""
        if self.live and (Path(self.live.directory) / "manifest.json").is_file():
            return Path(self.live.directory)
        return self.configured

    @property
    def previous(self) -> LiveEntry | None:
        return self.history.entries[-2] if len(self.history.entries) > 1 else None

    def load(self) -> LoadedRoom:
        """The live room, with the room version it was made live under."""
        loaded = load_prepared_room(self.directory)
        if self.live and self.directory != self.configured:
            loaded.room_version = self.live.room_version
        return loaded

    def build(
        self, job_id: str, reconstruction: Path, room_version: int
    ) -> tuple[LoadedRoom, Path]:
        """Build a reconstruction into a new room folder and check it; the live room is not
        changed. Returns the room and its folder."""
        out = self.rooms / f"{job_id}-v{room_version}"
        shutil.rmtree(out, ignore_errors=True)
        try:
            build_room().write_room(
                out, reconstruction / "room.ply", reconstruction / "report.json", room_version
            )
            if (reconstruction / "vps").is_dir():
                # The positioning map (#133), in the splat's frame like the splat itself.
                shutil.copytree(reconstruction / "vps", out / "vps")
            return load_prepared_room(out), out
        except (PreparedRoomError, SystemExit, OSError, ValueError) as exc:
            shutil.rmtree(out, ignore_errors=True)
            message = f"The reconstruction could not be built into a room: {exc}"
            raise LiveRoomError(message, 422) from exc

    def next_version(self, current: int | None) -> int:
        """One higher than the live room's and any room version made live before."""
        versions = [entry.room_version for entry in self.history.entries]
        return max([current or 0, *versions]) + 1

    def record(self, directory: Path, room_version: int, job_id: str | None) -> LiveEntry:
        """Record a room as live, keeping the configured room first in the history to go back to."""
        if not self.history.entries:
            try:
                configured = load_prepared_room(self.configured).room_version
            except PreparedRoomError:
                # Kept to go back to; restoring it is refused while it cannot load.
                configured = 0
            self.history.entries.append(
                LiveEntry(
                    directory=str(self.configured),
                    room_version=configured,
                    job_id=None,
                    made_live_at=now(),
                )
            )
        entry = LiveEntry(
            directory=str(directory), room_version=room_version, job_id=job_id, made_live_at=now()
        )
        self.history.entries.append(entry)
        self.rooms.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.history)
        return entry

    def describe(self, loaded: LoadedRoom | None) -> LiveRoomSummary:
        manifest = self.directory / "manifest.json"
        scale_source: str | None = None
        if manifest.is_file():
            splat = json_object(manifest).get("splat")
            if isinstance(splat, dict):
                found = cast(dict[str, Any], splat).get("scale_source")
                scale_source = found if isinstance(found, str) else None
        floor = next((e for e in loaded.entities if e.id == "floor"), None) if loaded else None
        live = self.live if self.directory != self.configured else None
        return LiveRoomSummary(
            job_id=live.job_id if live else None,
            room_version=loaded.room_version if loaded else None,
            made_live_at=live.made_live_at if live else None,
            floor_width_m=round(floor.size.width, 2) if floor else None,
            floor_depth_m=round(floor.size.depth, 2) if floor else None,
            scale_source=scale_source,
            overview_map=loaded.map is not None if loaded else False,
            positioning_map=(self.directory / "vps" / "map.json").is_file(),
            can_restore=self.previous is not None,
        )

    def _read(self) -> LiveHistory:
        if not self.path.is_file():
            return LiveHistory(entries=[])
        try:
            return LiveHistory.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return LiveHistory(entries=[])


def json_object(path: Path) -> dict[str, Any]:
    found = json.loads(path.read_text(encoding="utf-8"))
    return cast(dict[str, Any], found) if isinstance(found, dict) else {}


def build_room() -> ModuleType:
    """`assets/splat-room/build_room.py`, which is a script rather than part of the package."""
    path = Path(__file__).resolve().parents[1] / "assets" / "splat-room" / "build_room.py"
    spec = importlib.util.spec_from_file_location("splat_build_room", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
