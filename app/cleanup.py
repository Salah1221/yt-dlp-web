"""The janitor that deletes old work folders."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from . import jobs


def sweep(store: jobs.JobStore) -> int:
    """Delete every job that is older than the TTL. Return the count."""
    removed = 0
    for job_id in store.expired_ids():
        job = store.get(job_id)
        if job is None:
            continue
        store.update(job_id, state=jobs.EXPIRED)
        if jobs.delete_workdir(job):
            store.remove(job_id)
            removed += 1
    return removed


def sweep_orphans(root: Path, ttl_seconds: int, known_ids: set[str]) -> int:
    """Delete a folder that has no record and is older than the TTL.

    This covers the case where the process stopped in the middle of a job.
    """
    root = Path(root)
    if not root.is_dir():
        return 0
    removed = 0
    limit = time.time() - ttl_seconds
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name in known_ids:
            continue
        try:
            if folder.stat().st_mtime > limit:
                continue
        except OSError:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            removed += 1
    return removed


async def janitor(store: jobs.JobStore, root: Path, ttl_seconds: int,
                  interval: float) -> None:
    """Run a sweep every interval, until the task is cancelled."""
    while True:
        await asyncio.sleep(interval)
        try:
            sweep(store)
            sweep_orphans(root, ttl_seconds, store.known_ids())
        except Exception:
            # A sweep must never stop the janitor. The next cycle retries.
            continue
