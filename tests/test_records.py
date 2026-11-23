"""Durable records (#241): a record being replaced at the moment it is read is still found."""

import re
from pathlib import Path

from backend.records import RecordFolder, StoredRecord


def folder(tmp_path: Path) -> RecordFolder[StoredRecord]:
    return RecordFolder(tmp_path, StoredRecord, re.compile(r"^job_[0-9a-f]+$"), "job")


def test_a_record_refused_for_a_moment_while_it_is_replaced_is_still_read(tmp_path, monkeypatch):
    records = folder(tmp_path)
    (tmp_path / "job_ab12").mkdir()
    records.save(StoredRecord(id="job_ab12", created_at="2026-11-23T00:00:00+00:00"))
    real = Path.read_text
    refusals = iter([True, True, False])

    def busy(self: Path, *args, **kwargs):
        # Windows refuses an open while the file is being replaced.
        if self.name == "job.json" and next(refusals, False):
            raise PermissionError(13, "The process cannot access the file")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", busy)
    found = records.read("job_ab12")
    assert found is not None and found.id == "job_ab12"


def test_a_missing_or_malformed_record_is_none(tmp_path):
    records = folder(tmp_path)
    assert records.read("job_ffff") is None
    assert records.read("../etc") is None
    (tmp_path / "job_cd34").mkdir()
    (tmp_path / "job_cd34" / "job.json").write_text("{not json", encoding="utf-8")
    assert records.read("job_cd34") is None


def test_a_record_refused_for_good_is_none(tmp_path, monkeypatch):
    records = folder(tmp_path)
    (tmp_path / "job_ef56").mkdir()
    records.save(StoredRecord(id="job_ef56", created_at="2026-11-23T00:00:00+00:00"))
    monkeypatch.setattr("backend.records.REPLACE_WAIT_SECONDS", 0.0)

    def refuse(self: Path, *args, **kwargs):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(Path, "read_text", refuse)
    assert records.read("job_ef56") is None
