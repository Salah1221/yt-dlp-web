"""Settings for the local yt-dlp web page."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
JOB_TTL_SECONDS = 1800
CLEANUP_INTERVAL_SECONDS = 60

TEMP_ROOT_ENV = "YTDLP_WEB_TEMP_ROOT"


def temp_root() -> Path:
    """Return the folder that holds one sub-folder per job.

    The environment variable YTDLP_WEB_TEMP_ROOT overrides the default.
    The tests use that override to keep every file inside tmp_path.
    """
    override = os.environ.get(TEMP_ROOT_ENV)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "ytdlp-web"
