import time

import pytest

from app import jobs


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=60)


def test_create_makes_a_record_and_a_folder(store, tmp_path):
    job = store.create("https://example.com/v", "audio")
    assert len(job.id) == 32
    assert job.state == jobs.QUEUED
    assert job.mode == "audio"
    assert job.percent == 0.0
    assert (tmp_path / job.id).is_dir()
    assert job.workdir == str(tmp_path / job.id)


def test_two_jobs_get_different_folders(store):
    first = store.create("https://example.com/a", "audio")
    second = store.create("https://example.com/b", "audio")
    assert first.id != second.id
    assert first.workdir != second.workdir


def test_get_returns_none_for_an_unknown_id(store):
    assert store.get("0" * 32) is None


def test_update_changes_the_fields_and_returns_the_record(store):
    job = store.create("https://example.com/v", "video")
    updated = store.update(job.id, state=jobs.DOWNLOADING, percent=42.5)
    assert updated.state == jobs.DOWNLOADING
    assert updated.percent == 42.5
    assert store.get(job.id).percent == 42.5


def test_update_returns_none_for_an_unknown_id(store):
    assert store.update("0" * 32, state=jobs.ERROR) is None


def test_remove_deletes_the_record(store):
    job = store.create("https://example.com/v", "audio")
    store.remove(job.id)
    assert store.get(job.id) is None


def test_expired_ids_reports_only_the_old_job(store):
    old = store.create("https://example.com/old", "audio")
    new = store.create("https://example.com/new", "audio")
    store.update(old.id, created_at=time.monotonic() - 120)
    expired = store.expired_ids()
    assert old.id in expired
    assert new.id not in expired


def test_public_hides_the_server_paths(store):
    job = store.create("https://example.com/v", "audio")
    store.update(job.id, file_path="C:/secret/song.mp3", cancelled=True)
    data = store.get(job.id).public()
    assert data["id"] == job.id
    assert data["state"] == jobs.QUEUED
    assert "file_path" not in data
    assert "workdir" not in data
    assert "cancelled" not in data
