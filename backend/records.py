"""Folders of durable JSON records: one `<id>/<name>.json` per record, written atomically."""

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from backend.protocol import WireModel


def now() -> str:
    """The current UTC time as an ISO string; microseconds keep rapid records in order."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def seconds_between(start: str, end: str) -> float:
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)


def write_json(path: Path, record: BaseModel) -> None:
    """Replace the file in one step, so a reader never sees a half-written record."""
    pending = path.with_suffix(".json.tmp")
    pending.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    pending.replace(path)


class StoredRecord(WireModel):
    id: str
    created_at: str


class RecordFolder[T: StoredRecord]:
    def __init__(self, root: Path, model: type[T], id_pattern: re.Pattern[str], name: str) -> None:
        self.root = root
        self.model = model
        self.id_pattern = id_pattern
        self.name = name

    def path(self, record_id: str) -> Path:
        return self.root / record_id / f"{self.name}.json"

    def read(self, record_id: str) -> T | None:
        if not self.id_pattern.match(record_id):
            return None
        try:
            return self.model.model_validate_json(self.path(record_id).read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None

    def save(self, record: T) -> None:
        write_json(self.path(record.id), record)

    def newest_first(self) -> list[T]:
        if not self.root.is_dir():
            return []
        found = (self.read(folder.name) for folder in self.root.iterdir())
        records = [record for record in found if record is not None]
        return sorted(records, key=lambda record: record.created_at, reverse=True)
