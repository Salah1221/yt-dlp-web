import asyncio
import os
import time

import pytest

from app import cleanup, jobs


@pytest.fixture()
def store(tmp_path):
    return jobs.JobStore(tmp_path, ttl_seconds=60)


def test_sweep_keeps_a_fresh_job(store, tmp_path):
    job = store.create("http://x/y.mp4", "audio")
    assert cleanup.sweep(store) == 0
    assert store.get(job.id) is not None
    assert (tmp_path / job.id).is_dir()


def test_sweep_removes_an_old_job_and_its_folder(store, tmp_path):
    job = store.create("http://x/y.mp4", "audio")
    (tmp_path / job.id / "song.mp3").write_bytes(b"x")
    store.update(job.id, created_at=time.monotonic() - 120)
    assert cleanup.sweep(store) == 1
    assert store.get(job.id) is None
    assert not (tmp_path / job.id).exists()


def test_sweep_orphans_removes_an_old_unknown_folder(tmp_path):
    orphan = tmp_path / ("a" * 32)
    orphan.mkdir()
    old = time.time() - 7200
    os.utime(orphan, (old, old))
    assert cleanup.sweep_orphans(tmp_path, 60, set()) == 1
    assert not orphan.exists()


def test_sweep_orphans_keeps_a_known_folder(tmp_path):
    known = tmp_path / ("b" * 32)
    known.mkdir()
    old = time.time() - 7200
    os.utime(known, (old, old))
    assert cleanup.sweep_orphans(tmp_path, 60, {"b" * 32}) == 0
    assert known.exists()


def test_sweep_orphans_keeps_a_fresh_folder(tmp_path):
    fresh = tmp_path / ("c" * 32)
    fresh.mkdir()
    assert cleanup.sweep_orphans(tmp_path, 60, set()) == 0
    assert fresh.exists()


def test_the_janitor_runs_a_sweep_and_then_stops(store, tmp_path):
    job = store.create("http://x/y.mp4", "audio")
    store.update(job.id, created_at=time.monotonic() - 120)

    async def scenario():
        task = asyncio.create_task(
            cleanup.janitor(store, tmp_path, 60, interval=0.01))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert store.get(job.id) is None
