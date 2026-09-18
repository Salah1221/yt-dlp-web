"""The job record and the in-memory job store."""

from __future__ import annotations

import asyncio
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

QUEUED = "queued"
DOWNLOADING = "downloading"
CONVERTING = "converting"
READY = "ready"
ERROR = "error"
EXPIRED = "expired"

TERMINAL_STATES = frozenset({READY, ERROR, EXPIRED})

# Fields that stay on the server and never reach the page.
PRIVATE_FIELDS = ("file_path", "workdir", "cancelled")


class JobCancelled(Exception):
    """Raised inside the worker thread to stop a running yt-dlp download."""


@dataclass
class Job:
    id: str
    url: str
    mode: str
    format_id: Optional[str] = None
    state: str = QUEUED
    percent: float = 0.0
    speed: Optional[float] = None
    eta: Optional[int] = None
    title: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    file_path: Optional[str] = None
    workdir: Optional[str] = None
    cancelled: bool = False

    def public(self) -> dict:
        """Return the fields that the page is allowed to see."""
        data = asdict(self)
        for name in PRIVATE_FIELDS:
            data.pop(name, None)
        return data


class JobStore:
    """Hold every job record. Safe to call from any thread."""

    def __init__(self, root: Path, ttl_seconds: int) -> None:
        self._root = Path(root)
        self._ttl = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def create(self, url: str, mode: str, format_id: str | None = None) -> Job:
        job_id = uuid.uuid4().hex
        workdir = self._root / job_id
        workdir.mkdir(parents=True, exist_ok=True)
        job = Job(id=job_id, url=url, mode=mode, format_id=format_id,
                  workdir=str(workdir))
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for name, value in fields.items():
                setattr(job, name, value)
            return job

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._queues.pop(job_id, None)

    def expired_ids(self, now: float | None = None) -> list[str]:
        moment = time.monotonic() if now is None else now
        with self._lock:
            return [job.id for job in self._jobs.values()
                    if moment - job.created_at > self._ttl]

    def known_ids(self) -> set[str]:
        with self._lock:
            return set(self._jobs)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the event loop that serves the WebSocket routes."""
        self._loop = loop

    def queue_for(self, job_id: str) -> asyncio.Queue:
        """Return the progress queue of a job, and make one if needed."""
        with self._lock:
            queue = self._queues.get(job_id)
            if queue is None:
                queue = asyncio.Queue()
                self._queues[job_id] = queue
            return queue

    def publish(self, job_id: str, payload: dict) -> None:
        """Send one progress update. Safe to call from a worker thread.

        An asyncio.Queue is not thread safe, so the update crosses into
        the event loop through call_soon_threadsafe.
        """
        queue = self.queue_for(job_id)
        loop = self._loop
        if loop is None:
            queue.put_nowait(payload)
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            # The loop is closed. The page is gone, so the update is lost.
            pass


def delete_workdir(job: Job) -> bool:
    """Delete the whole work folder of a job.

    Return True when the folder is gone. A delete can fail when another
    program holds a file handle open. The janitor then tries again.
    """
    if not job.workdir:
        return True
    path = Path(job.workdir)
    if not path.exists():
        return True
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()
