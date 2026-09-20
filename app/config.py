"""Settings for the local yt-dlp web page."""

from __future__ import annotations

import ipaddress
import os
import shutil
import tempfile
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
JOB_TTL_SECONDS = 1800
CLEANUP_INTERVAL_SECONDS = 60

TEMP_ROOT_ENV = "YTDLP_WEB_TEMP_ROOT"
COOKIE_FILE_ENV = "YTDLP_WEB_COOKIES"
COOKIE_BROWSER_ENV = "YTDLP_WEB_COOKIES_FROM_BROWSER"
PLAYER_CLIENT_ENV = "YTDLP_WEB_PLAYER_CLIENT"
JS_RUNTIME_ENV = "YTDLP_WEB_JS_RUNTIMES"

# yt-dlp runs a JavaScript runtime to answer the signature challenge of
# YouTube. It enables deno by itself and finds it on PATH. The others it
# uses only when they are named. These are the names it knows, in the
# order it prefers them.
JS_RUNTIMES = ("deno", "node", "quickjs", "bun")

# downloader.cookie_opts writes one file with this prefix for each call
# into yt-dlp, and the janitor sweeps up one that a crash left behind.
COOKIE_COPY_PREFIX = "cookies-"


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


def cookie_file() -> Path | None:
    """Return the cookies.txt file to send to the site, or None.

    A site that asks the server to prove it is not a robot accepts the
    request when it carries the cookies of a signed in browser. The
    operator exports them once and names the file in the environment.
    """
    value = _text(COOKIE_FILE_ENV)
    return Path(value).expanduser() if value else None


def cookies_from_browser() -> tuple[str | None, ...] | None:
    """Return the browser to read cookies from, in the yt-dlp form.

    The value is written the way the yt-dlp command line writes it:
    BROWSER[+KEYRING][:PROFILE][::CONTAINER], for example `firefox` or
    `chrome:Default`. This reads a browser profile on the machine that
    runs the server, so it suits a desktop and not a server.
    """
    value = _text(COOKIE_BROWSER_ENV)
    if value is None:
        return None
    head, _, container = value.partition("::")
    head, _, profile = head.partition(":")
    browser, _, keyring = head.partition("+")
    return (browser.strip().lower(), profile.strip() or None,
            keyring.strip().upper() or None, container.strip() or None)


def player_clients() -> list[str] | None:
    """Return the YouTube clients to ask, in order, or None for the default.

    YouTube serves the same video to a phone, a television, and a
    browser, and it applies the robot check to each of them differently.
    A client that is not asked to sign in sometimes answers when the
    default one does not. The value is a list: `tv,web_safari`.
    """
    value = _text(PLAYER_CLIENT_ENV)
    if value is None:
        return None
    names = [name.strip() for name in value.split(",")]
    return [name for name in names if name] or None


def js_runtimes() -> dict[str, dict] | None:
    """Return the JavaScript runtimes to enable, or None for the default.

    The value names one runtime per comma, with an optional path after a
    colon: `node`, or `node:/usr/bin/node`. yt-dlp enables deno alone by
    itself, and a server that has node and no deno needs this line.
    """
    value = _text(JS_RUNTIME_ENV)
    if value is None:
        return None
    runtimes: dict[str, dict] = {}
    for part in value.split(","):
        name, _, path = part.strip().partition(":")
        if not name:
            continue
        runtimes[name.strip().lower()] = {"path": path.strip()} if path.strip() else {}
    return runtimes or None


def js_runtime_on_path() -> str | None:
    """Return the first JavaScript runtime found on PATH, or None."""
    for name in JS_RUNTIMES:
        # quickjs ships as qjs, and the others carry their own name.
        for binary in (("qjs", "quickjs") if name == "quickjs" else (name,)):
            if shutil.which(binary):
                return name
    return None


def check_js_runtimes() -> None:
    """Refuse to start when a runtime name is not one yt-dlp knows."""
    for name in js_runtimes() or {}:
        if name not in JS_RUNTIMES:
            raise RuntimeError(
                f"{JS_RUNTIME_ENV} names {name}, which yt-dlp does not know. "
                f"The names are: {', '.join(JS_RUNTIMES)}.")


def check_cookies() -> None:
    """Refuse to start when the cookie file is named but unusable.

    A missing file is silent otherwise: yt-dlp sends no cookie and the
    site answers with the robot check, which reads like a fault in the
    application and not like a fault in the setting.
    """
    path = cookie_file()
    if path is None:
        return
    if not path.is_file():
        raise RuntimeError(
            f"{COOKIE_FILE_ENV} is {path}, and no file is there. Export the "
            "cookies again, or clear the variable.")
    if not os.access(path, os.R_OK):
        raise RuntimeError(
            f"{COOKIE_FILE_ENV} is {path}, and this user cannot read it. "
            "Give the service user read access to that file.")


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
