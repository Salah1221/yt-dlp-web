"""The job record and the in-memory job store."""

from __future__ import annotations

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

    def expired_ids(self, now: float | None = None) -> list[str]:
        moment = time.monotonic() if now is None else now
        with self._lock:
            return [job.id for job in self._jobs.values()
                    if moment - job.created_at > self._ttl]
