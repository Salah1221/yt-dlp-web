"""The two limits that keep a small disk from filling.

A job holds the video stream, the audio stream, the merged output, and the
faststart rewrite at the same time. The peak is near three times the size
of the final file. A server with 20 GB of disk therefore cannot run many
large jobs together, and it must refuse rather than fill the disk.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path


class JobSlots:
    """Count the jobs that run at the same time."""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def take(self) -> bool:
        """Take one slot. Return False when every slot is busy."""
        with self._lock:
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    def give_back(self) -> None:
        """Return one slot. A extra call is safe and does nothing."""
        with self._lock:
            self._used = max(0, self._used - 1)


def free_bytes(path: str | Path) -> int:
    """Return the free space of the disk that holds this path.

    A path that cannot be read reports zero. Zero then refuses the job,
    which is the safe answer when the free space is unknown.
    """
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return 0


def has_room(path: str | Path, needed: int) -> bool:
    """Return True when the disk holds at least the needed bytes."""
    if needed <= 0:
        return True
    return free_bytes(path) >= needed
