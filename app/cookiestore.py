"""The cookies that somebody pastes into the settings panel.

The file holds a live session of that person's account, so this module
only ever writes it and describes it. Nothing here sends the content
back to the page, and no route does either. A person who can open the
page can replace the cookies and can see whether they are there, and
that is all.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import tempfile
import threading
from pathlib import Path

from yt_dlp.cookies import YoutubeDLCookieJar

from . import config

# The first line of the format. A browser add-on writes it, and a paste
# that lost it still loads once this module puts it back.
HEADER = "# Netscape HTTP Cookie File"

# A real export is tens of kilobytes. This much is already generous, and
# it stays under the one megabyte body that nginx accepts by default.
MAX_BYTES = 256 * 1024

# The page shows this many domains and then says how many are left.
SHOWN_DOMAINS = 6

# Two downloads can end at the same moment, and both may carry cookies
# that the site rotated. One writes the store at a time.
_write_lock = threading.Lock()


def _jar(path: Path) -> YoutubeDLCookieJar:
    """Load a cookie file, with nothing of it reaching the log.

    yt-dlp prints the whole of a line it cannot read, and that line can
    hold a live session. The log of a server is not the place for it.
    """
    jar = YoutubeDLCookieJar(str(path))
    with contextlib.redirect_stderr(io.StringIO()):
        jar.load()
    return jar


def _looks_space_separated(text: str) -> bool:
    """Return True when the lines hold fields but no tab.

    A paste through a field that turns a tab into spaces gives a file
    that loads and holds nothing. The message has to name that, because
    the file looks right to the person who pasted it.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line and len(line.split()) >= 6:
            return True
    return False


def _normalise(text: str) -> str:
    """Return the text as the format wants it, or raise ValueError."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("that is larger than a cookie file ever is")
    body = text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.strip("\n")
    if not body.strip():
        raise ValueError("paste the cookies first")
    first = body.splitlines()[0].strip().lower()
    if not first.startswith("# netscape") and not first.startswith("# http"):
        body = f"{HEADER}\n{body}"
    return body + "\n"


def _describe(jar: YoutubeDLCookieJar, path: Path) -> dict:
    """Return the facts about a jar that the page may show."""
    domains = sorted({cookie.domain.lstrip(".") for cookie in jar})
    expiries = [cookie.expires for cookie in jar if cookie.expires]
    soonest = None
    if expiries:
        soonest = dt.datetime.fromtimestamp(
            min(expiries), dt.timezone.utc).isoformat()
    saved = dt.datetime.fromtimestamp(
        path.stat().st_mtime, dt.timezone.utc).isoformat()
    return {
        "count": len(jar),
        "domains": domains[:SHOWN_DOMAINS],
        "more_domains": max(0, len(domains) - SHOWN_DOMAINS),
        "expires": soonest,
        "saved": saved,
    }


def _values(jar: YoutubeDLCookieJar) -> set:
    """Return what a jar holds, so two of them can be compared."""
    return {(cookie.domain, cookie.path, cookie.name, cookie.value,
             cookie.expires) for cookie in jar}


def _names(jar: YoutubeDLCookieJar) -> set:
    """Return which cookies a jar holds, whatever their values are."""
    return {(cookie.domain, cookie.path, cookie.name) for cookie in jar}


def _place(body: str, store: Path) -> None:
    """Put this text at the store path, readable by nobody else."""
    handle, name = tempfile.mkstemp(prefix=".cookies-", dir=store.parent)
    staged = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body)
        os.chmod(staged, 0o600)
        os.replace(staged, store)
    finally:
        staged.unlink(missing_ok=True)


def refresh(copy: Path, stamp: float) -> bool:
    """Take back the cookies that the site rotated during a download.

    A site hands out a fresh value for a cookie as it is used, and the
    old value stops working soon after. yt-dlp writes the new jar to the
    file it was given, which is a copy of the store, so without this the
    refreshed cookies would go with the copy and the saved ones would
    age out in a few days.

    Only a rotation is taken back. A jar that came back with a cookie
    missing is a sign out, and the saved file stands.

    `stamp` is the time the store carried when the copy was taken. A
    store that changed since then belongs to a download that ended
    later, and the newer one stands.
    """
    with _write_lock:
        store = config.cookie_store()
        try:
            if not store.is_file() or store.stat().st_mtime != stamp:
                return False
            before = _jar(store)
            after = _jar(copy)
            if _names(before) - _names(after):
                # The site took cookies away rather than handing new
                # values for them. That is a sign out, not a rotation,
                # and it is what a site does when it refuses a session.
                # Writing it back would spend the saved cookies on the
                # first download that failed, and every download after
                # it would be a stranger with no way back but another
                # export. The saved file stands.
                return False
            if _values(before) == _values(after):
                return False
            _place(copy.read_text(encoding="utf-8"), store)
        except OSError:
            # A refresh that fails must never fail the download. The
            # cookies that were saved keep working until they expire.
            return False
        except Exception:
            return False
    # The write above changed the time, so the panel would otherwise say
    # that somebody saved the cookies during a download.
    os.utime(store, (stamp, stamp))
    return True


def status() -> dict:
    """Return what the settings panel shows about the cookies in use."""
    store = config.cookie_store()
    empty = {"source": "none", "count": 0, "domains": [], "more_domains": 0,
             "expires": None, "saved": None,
             "writable": _can_write(store)}
    if store.is_file():
        try:
            described = _describe(_jar(store), store)
        except Exception:
            # The file is there and yt-dlp cannot read it. Saying so
            # beats a panel that claims the cookies are in place.
            return {**empty, "source": "broken"}
        return {**empty, "source": "pasted", **described}
    if config.cookie_file() is not None:
        # The operator placed a file and named it in the environment.
        # The panel reports it and does not touch it.
        return {**empty, "source": "file"}
    return empty


def _can_write(store: Path) -> bool:
    """Return True when this user may write the store."""
    if store.exists():
        return os.access(store, os.W_OK)
    parent = store.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def save(text: str) -> dict:
    """Write the pasted cookies. Raise ValueError on anything else."""
    body = _normalise(text)
    store = config.cookie_store()
    store.parent.mkdir(parents=True, exist_ok=True)
    # The write lands on a file of its own and then takes the name in one
    # step, so a download that starts in the middle reads one whole file
    # and never a half written one.
    handle, name = tempfile.mkstemp(prefix=".cookies-", dir=store.parent)
    staged = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body)
        try:
            jar = _jar(staged)
        except Exception as error:
            if "JSON" in str(error):
                raise ValueError(
                    "that is JSON. The add-on has to write the Netscape "
                    "format, which this one calls cookies.txt.") from None
            raise ValueError(
                "this does not read as a cookies.txt file. Export it again "
                "with an add-on that writes the Netscape format.") from None
        if not len(jar):
            if _looks_space_separated(body):
                raise ValueError(
                    "the tabs in the file turned into spaces on the way "
                    "here. Use the file button, which reads the file as it "
                    "is, or paste into a field that keeps tabs.")
            raise ValueError("that file holds no cookie")
        # The file is a credential, so nobody else on the machine reads it.
        os.chmod(staged, 0o600)
        described = _describe(jar, staged)
        os.replace(staged, store)
    finally:
        staged.unlink(missing_ok=True)
    return {**status(), **described, "source": "pasted"}


def clear() -> bool:
    """Delete the stored cookies. Return True when one was there."""
    store = config.cookie_store()
    if not store.is_file():
        return False
    store.unlink(missing_ok=True)
    return True
