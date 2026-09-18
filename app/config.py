"""Settings for the local yt-dlp web page."""

from __future__ import annotations

import ipaddress
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


def _text(name: str) -> str | None:
    """Return an environment value, or None when it is absent or blank."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _number(name: str, default: int) -> int:
    """Return a whole number from the environment, or the default."""
    value = _text(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        # A typed setting must never stop the server. The default is safe.
        return default


def password() -> str | None:
    """Return the login password, or None when the login is off."""
    return _text("YTDLP_WEB_PASSWORD")


def require_login() -> bool:
    return password() is not None


def host() -> str:
    return _text("YTDLP_WEB_HOST") or HOST


def port() -> int:
    return _number("YTDLP_WEB_PORT", PORT)


def job_ttl() -> int:
    return _number("YTDLP_WEB_TTL", JOB_TTL_SECONDS)


def max_jobs() -> int:
    return max(1, _number("YTDLP_WEB_MAX_JOBS", 2))


def max_filesize() -> int | None:
    """Return the size limit in bytes. Zero or absent means no limit."""
    value = _number("YTDLP_WEB_MAX_FILESIZE", 0)
    return value if value > 0 else None


def min_free_bytes() -> int:
    """Return the free space a job needs before it may start.

    A job holds the video stream, the audio stream, the merged output, and
    the faststart rewrite at the same time. Three times the size limit
    covers that peak.
    """
    limit = max_filesize()
    return limit * 3 if limit else 0


def is_loopback_host(name: str) -> bool:
    """Return True when this address reaches only the local machine."""
    if name in ("localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def block_private_addresses() -> bool:
    """Return True when the outbound address guard must be active.

    Two conditions turn it on, and either one is enough.

    The binding is not loopback, so other machines reach the server
    directly. Or a password is set, which means the operator expects
    people other than themselves to use it.

    The second condition is the important one. A server behind a reverse
    proxy binds to loopback and is still reachable from the internet, so
    the binding on its own cannot decide this.

    With no password and a loopback binding, only this machine can reach
    the server, and fetching from a device on the local network is a fair
    thing to do. The guard then stays off.
    """
    return require_login() or not is_loopback_host(host())


def check_startup() -> None:
    """Refuse the one combination that is never safe."""
    if block_private_addresses() and not require_login():
        raise RuntimeError(
            f"the host is {host()}, which is not loopback, and no password is "
            "set. Set YTDLP_WEB_PASSWORD, or bind to 127.0.0.1.")
