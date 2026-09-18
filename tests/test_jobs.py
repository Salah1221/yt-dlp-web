import asyncio
import threading
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


def test_publish_without_a_loop_puts_the_payload_in_the_queue(store):
    job = store.create("https://example.com/v", "audio")
    store.publish(job.id, {"state": jobs.DOWNLOADING})
    queue = store.queue_for(job.id)
    assert queue.get_nowait() == {"state": jobs.DOWNLOADING}


def test_queue_for_returns_the_same_queue_every_time(store):
    job = store.create("https://example.com/v", "audio")
    assert store.queue_for(job.id) is store.queue_for(job.id)


def test_publish_from_a_worker_thread_reaches_the_loop(store):
    async def scenario():
        job = store.create("https://example.com/v", "audio")
        store.attach_loop(asyncio.get_running_loop())
        queue = store.queue_for(job.id)
        thread = threading.Thread(
            target=store.publish, args=(job.id, {"state": jobs.READY}))
        thread.start()
        payload = await asyncio.wait_for(queue.get(), timeout=2)
        thread.join()
        return payload

    assert asyncio.run(scenario()) == {"state": jobs.READY}


def test_remove_drops_the_queue_too(store):
    job = store.create("https://example.com/v", "audio")
    first = store.queue_for(job.id)
    store.remove(job.id)
    assert store.queue_for(job.id) is not first


def test_delete_workdir_removes_the_folder(store, tmp_path):
    job = store.create("https://example.com/v", "audio")
    (tmp_path / job.id / "song.mp3").write_bytes(b"data")
    assert jobs.delete_workdir(job) is True
    assert not (tmp_path / job.id).exists()


def test_delete_workdir_is_safe_when_the_folder_is_already_gone(store, tmp_path):
    job = store.create("https://example.com/v", "audio")
    jobs.delete_workdir(job)
    assert jobs.delete_workdir(job) is True


def test_delete_workdir_is_safe_when_there_is_no_folder():
    job = jobs.Job(id="x" * 32, url="https://example.com/v", mode="audio")
    assert jobs.delete_workdir(job) is True
