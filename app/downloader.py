"""Every call into yt-dlp lives here."""

from __future__ import annotations

import functools
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from yt_dlp import YoutubeDL

from . import config, cookiestore, jobs, urlguard

# yt-dlp writes these while a download runs. They are never the result.
SKIP_SUFFIXES = (".part", ".ytdl", ".temp")

MODES = ("video", "audio", "format")

# YouTube writes this when it wants a signed in visitor. The apostrophe in
# "you're" is a curly one in the real message, so the marks go around it.
BOT_CHECK_MARKS = ("sign in to confirm", "not a bot")

# And this when the client it picks for a signed in visitor is one it has
# stopped serving. The cookie that answers the check above brings this one
# in with it, because yt-dlp asks a different set of clients as soon as
# cookies are in play.
RELOAD_MARKS = ("page needs to be reloaded",)

# And this when nothing it served can be downloaded. A signature that
# nothing could read takes the format out of the list, so the list runs
# out and this is what the chooser says at the end of it.
FORMAT_MARKS = ("requested format is not available",)

# The client in that set which YouTube is refusing. Dropping it leaves the
# rest of the signed in set, which is what the yt-dlp issue recommends.
REFUSED_CLIENT = "tv_downgraded"

# 150 bytes keeps the whole path under the Windows limit.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"


def build_opts(mode: str, workdir: str, format_id: str | None = None,
               max_height: int | None = None,
               max_filesize: int | None = None,
               progress_hook=None, postprocessor_hook=None) -> dict:
    """Return the yt-dlp options for one job."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    if mode == "format" and not format_id:
        raise ValueError("mode 'format' needs a format_id")
    if max_height is not None:
        # bool is a subclass of int, so it needs its own check.
        if isinstance(max_height, bool) or not isinstance(max_height, int):
            raise ValueError("max_height must be a whole number")
        if max_height <= 0:
            raise ValueError("max_height must be more than zero")

    opts: dict = {
        "outtmpl": str(Path(workdir) / OUTPUT_TEMPLATE),
        "paths": {"home": str(workdir), "temp": str(workdir)},
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "progress_hooks": [progress_hook] if progress_hook else [],
        "postprocessor_hooks": [postprocessor_hook] if postprocessor_hook else [],
    }

    if max_filesize:
        # yt-dlp stops the download when a stream passes this size.
        opts["max_filesize"] = max_filesize

    if mode == "video":
        if max_height:
            # The last branch is a safety fallback. The page only offers a
            # height that the video has, so it should never run. It stops an
            # odd site from turning a quality choice into a hard failure.
            opts["format"] = (f"bv*[height<={max_height}]+ba/"
                              f"b[height<={max_height}]/bv*+ba/b")
        else:
            opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"
        # faststart moves the MP4 index to the front, so the file seeks fast.
        opts["postprocessor_args"] = {"merger": ["-movflags", "+faststart"]}
    elif mode == "audio":
        opts["format"] = "ba/b"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        # yt-dlp tries the format with the best audio first. If the format
        # already holds audio, that attempt fails and the fallback runs.
        opts["format"] = f"{format_id}+ba/{format_id}"

    return opts


@contextmanager
def site_opts() -> Iterator[dict]:
    """Yield the yt-dlp options that say who this server is to the site.

    That is the cookies, the YouTube client to ask, and the JavaScript
    runtime that answers the signature challenge of YouTube.

    yt-dlp writes the jar back to the cookie file when it closes, and two
    jobs can run at the same time, so each call reads its own copy. The
    file the operator placed is never written, which also lets it live on
    a read-only path.

    The copy is not thrown away unread. A site rotates a cookie as it is
    used, and the old value dies soon after, so what yt-dlp wrote to the
    copy goes back into the store that the page owns.
    """
    opts: dict = {}
    # What the operator asked for, or the runtime that is installed when
    # they asked for nothing. Without one, YouTube throws away every
    # format that carries a signature and the download finds none.
    runtimes = config.js_runtimes() or js_runtime_auto()
    if runtimes:
        opts["js_runtimes"] = runtimes
    clients = config.player_clients()
    if clients:
        opts["extractor_args"] = {"youtube": {"player_client": clients}}
    browser = config.cookies_from_browser()
    if browser:
        opts["cookiesfrombrowser"] = browser
    source = config.cookie_file()
    if source is None:
        yield opts
        return
    root = config.temp_root()
    root.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=config.COOKIE_COPY_PREFIX,
                                    suffix=".txt", dir=root)
    os.close(handle)
    copy = Path(name)
    try:
        stamp = source.stat().st_mtime
        shutil.copyfile(source, copy)
        opts["cookiefile"] = str(copy)
        yield opts
    finally:
        # yt-dlp writes the jar back when it closes, and a site rotates a
        # cookie as it is used. The new values are in the copy, so they go
        # back to the store before the copy goes.
        if source == config.cookie_store():
            cookiestore.refresh(copy, stamp)
        copy.unlink(missing_ok=True)


@functools.cache
def runtime_info(name: str, path: str | None = None):
    """Ask yt-dlp about one JavaScript runtime, or None when it cannot.

    The answer says where the runtime is, which version it is, and
    whether yt-dlp supports that version. node is the one that catches
    people: yt-dlp wants 22 or later, and a server carrying 20 has a
    node that counts for nothing.

    Finding out runs the binary, so the answer is kept. A runtime that
    is installed while the server runs is picked up at the restart.
    """
    try:
        from yt_dlp.globals import supported_js_runtimes

        runtime = supported_js_runtimes.value.get(name)
        return runtime(path=path).info if runtime else None
    except Exception:  # pragma: no cover - only on a changed yt-dlp
        return None


def _supported(name: str, path: str | None = None) -> bool:
    info = runtime_info(name, path)
    return bool(info and info.supported)


def js_runtime_auto() -> dict[str, dict] | None:
    """Return the runtime to enable when the operator named none.

    yt-dlp enables deno and nothing else, so a server that carries node
    and no deno would run YouTube with no runtime at all, and YouTube
    then serves it almost nothing. Naming the runtime that is there
    fixes that, and it changes nothing where deno is installed.
    """
    for name in config.JS_RUNTIMES:
        if _supported(name):
            # yt-dlp reaches deno by itself, so there is nothing to say.
            return None if name == "deno" else {name: {}}
    return None


def js_runtime_ready() -> bool:
    """Return True when a runtime that yt-dlp supports will be used."""
    asked = config.js_runtimes()
    if asked is None:
        return any(_supported(name) for name in config.JS_RUNTIMES)
    return any(_supported(name, spec.get("path") or None)
               for name, spec in asked.items())


def _minimum(name: str) -> str | None:
    """Return the oldest version of a runtime that yt-dlp supports."""
    try:
        from yt_dlp.globals import supported_js_runtimes

        runtime = supported_js_runtimes.value.get(name)
        version = getattr(runtime, "MIN_SUPPORTED_VERSION", None)
        return ".".join(str(part) for part in version) if version else None
    except Exception:  # pragma: no cover - only on a changed yt-dlp
        return None


def js_runtime_trouble() -> str | None:
    """Return what is wrong with the runtime, in one line, or None.

    A runtime that is installed but too old is the trap. It looks right
    on the server and counts for nothing, so the line names the version
    that is there and the version that is wanted.
    """
    if js_runtime_ready():
        return None
    asked = config.js_runtimes()
    for name in (asked or config.JS_RUNTIMES):
        path = (asked or {}).get(name, {}).get("path") or None
        info = runtime_info(name, path)
        if not info:
            continue
        minimum = _minimum(name)
        if minimum:
            return (f"{name} {info.version} is installed, and yt-dlp needs "
                    f"{minimum} or later")
        return f"yt-dlp does not support the {name} that is installed"
    return "no JavaScript runtime is installed"


def known_player_clients() -> tuple[str, ...]:
    """Return the client names that this yt-dlp knows, or nothing.

    The table is internal to yt-dlp, so an upgrade can move it. The empty
    answer turns the check below off rather than stopping the server.
    """
    try:
        from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS
    except ImportError:  # pragma: no cover - only on a changed yt-dlp
        return ()
    return tuple(name for name in INNERTUBE_CLIENTS if not name.startswith("_"))


def check_player_clients() -> None:
    """Refuse to start when a client name is not one yt-dlp knows.

    yt-dlp skips an unknown name with a warning and carries on with the
    default. This application turns warnings off, so the typo would be
    silent and the setting would look as if it did nothing.
    """
    known = known_player_clients()
    if not known:
        return
    for name in config.player_clients() or []:
        # yt-dlp reads these three forms as well as a client name.
        if name in ("default", "all") or name.startswith("-"):
            continue
        if name not in known:
            raise RuntimeError(
                f"{config.PLAYER_CLIENT_ENV} names {name}, which yt-dlp does "
                f"not know. The names are: {', '.join(sorted(known))}.")


def _matches(error: Exception, marks: tuple[str, ...]) -> bool:
    lowered = str(error).lower()
    return all(mark in lowered for mark in marks)


def retry_opts(error: Exception) -> dict | None:
    """Return the options for a second attempt, or None for no second try.

    YouTube refuses one of the clients that yt-dlp picks for a signed in
    visitor, and the refusal comes and goes. Asking the rest of that set
    costs one request and answers most of them.

    An operator who named the clients has said what to ask, so their
    choice stands and nothing is retried.
    """
    if not _matches(error, RELOAD_MARKS) or config.player_clients():
        return None
    return {"extractor_args": {
        "youtube": {"player_client": ["default", f"-{REFUSED_CLIENT}"]}}}


def runtime_advice() -> str:
    """Return the sentence that sends a person to a working runtime."""
    return (f"{js_runtime_trouble()}. YouTube needs one to read the streams "
            "it serves. Install deno, or install a version of node that "
            f"yt-dlp supports and set {config.JS_RUNTIME_ENV}=node.")


def explain(error: Exception, mode: str | None = None) -> str:
    """Return the message for the page, in place of the yt-dlp one.

    A person can act on these failures, and the yt-dlp text tells them
    to pass a command line option that this application has no command
    line for.
    """
    text = str(error)
    if _matches(error, RELOAD_MARKS):
        if not js_runtime_ready():
            return ("YouTube refused every client it was asked, and "
                    f"{runtime_advice()}")
        return ("YouTube refused the client that yt-dlp asks for a signed in "
                "visitor, and it refused the rest of them as well. This one "
                "comes and goes, so try again in a minute.")
    if _matches(error, FORMAT_MARKS):
        if not js_runtime_ready():
            return ("YouTube served nothing that this server can download. "
                    "Without a runtime it throws away every stream that "
                    "carries a signature, which is most of them. "
                    f"{runtime_advice()}")
        if mode == "format":
            return ("that format is gone. The list came from an earlier "
                    "look at the page, and YouTube serves a different list "
                    "to each of the clients it answers. Press Check again "
                    "and take the format from the new list, or use the "
                    "Video MP4 button, which takes what is there.")
        return ("YouTube served nothing that this server can download. It "
                "does this to a signed in visitor at times, and it passes. "
                "Try again in a minute.")
    if not _matches(error, BOT_CHECK_MARKS):
        return text
    if config.cookie_file() or config.cookies_from_browser():
        return ("the site refused the cookies of this server. Export them "
                "again from a browser that is signed in to the site, replace "
                "the cookie file, and restart the server.")
    return ("the site asks this server to sign in and prove it is not a "
            "robot. Export the cookies of a signed in browser to a "
            f"cookies.txt file, set {config.COOKIE_FILE_ENV} to that file, "
            "and restart the server. docs/cookies.md holds the steps.")


def _extract(opts: dict, url: str, download: bool) -> dict | None:
    """Run one yt-dlp call. Every call in this module goes through here."""
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def find_output(workdir: str | Path) -> Path | None:
    """Return the finished file in a work folder, or None."""
    folder = Path(workdir)
    if not folder.is_dir():
        return None
    finished = [item for item in folder.iterdir()
                if item.is_file() and not item.name.endswith(SKIP_SUFFIXES)]
    if not finished:
        return None
    return max(finished, key=lambda item: item.stat().st_size)


def _size(item: dict) -> int | None:
    """Return the reported size of one format, exact or approximate."""
    return item.get("filesize") or item.get("filesize_approx")


def _is_audio_only(item: dict) -> bool:
    vcodec = item.get("vcodec") or "none"
    acodec = item.get("acodec") or "none"
    return vcodec == "none" and acodec != "none"


def _is_real_height(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def build_qualities(formats: list[dict]) -> list[dict]:
    """Return one entry per video height, largest height first.

    The size is an estimate. It adds the largest video of that height to
    the largest audio the site reports. A site that reports no size gives
    an entry with no size, and the page then shows the height alone.
    """
    best_audio = 0
    for item in formats or []:
        if _is_audio_only(item):
            size = _size(item) or 0
            best_audio = max(best_audio, size)

    largest: dict[int, int | None] = {}
    for item in formats or []:
        if (item.get("vcodec") or "none") == "none":
            continue
        height = item.get("height")
        if not _is_real_height(height):
            continue
        size = _size(item)
        current = largest.get(height)
        if height not in largest or (size or 0) > (current or 0):
            largest[height] = size

    return [{"height": height,
             "label": f"{height}p",
             "filesize": (largest[height] + best_audio) if largest[height] else None}
            for height in sorted(largest, reverse=True)]


def _format_row(item: dict) -> dict:
    """Turn one yt-dlp format entry into the fields the page shows."""
    width = item.get("width")
    height = item.get("height")
    resolution = item.get("resolution")
    if not resolution:
        resolution = f"{width}x{height}" if width and height else "audio only"
    return {
        "format_id": item.get("format_id"),
        "ext": item.get("ext"),
        "resolution": resolution,
        "fps": item.get("fps"),
        "vcodec": item.get("vcodec"),
        "acodec": item.get("acodec"),
        "filesize": item.get("filesize") or item.get("filesize_approx"),
        "note": item.get("format_note") or "",
    }


def probe(url: str) -> dict:
    """Read the video data without a download."""
    allow_private = not config.block_private_addresses()
    urlguard.check_url(url, allow_private=allow_private)
    # The guard stays on for the whole call, so a redirect to a private
    # address is refused at connection time as well.
    with site_opts() as extra:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "noplaylist": True, **extra}
        try:
            with urlguard.guarded(allow_private=allow_private):
                info = _extract(opts, url, download=False)
        except Exception as error:  # yt-dlp raises many types
            retry = retry_opts(error)
            if retry is None:
                message = explain(error)
                if message == str(error):
                    raise
                raise ValueError(message) from error
            try:
                with urlguard.guarded(allow_private=allow_private):
                    info = _extract({**opts, **retry}, url, download=False)
            except Exception as second:
                raise ValueError(explain(second)) from second
    if info is None:
        raise ValueError("this URL gives no video")
    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not entries:
            raise ValueError("this URL holds no video")
        info = entries[0]
    formats = [_format_row(item) for item in (info.get("formats") or [])
               if item.get("format_id")]
    return {
        "title": info.get("title") or "video",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "formats": formats,
        "qualities": build_qualities(info.get("formats") or []),
    }


def run(job: jobs.Job, store: jobs.JobStore) -> None:
    """Download one job. This function blocks, so call it in a thread."""

    def send() -> None:
        current = store.get(job.id)
        if current is not None:
            store.publish(job.id, current.public())

    def progress_hook(data: dict) -> None:
        current = store.get(job.id)
        if current is None or current.cancelled:
            raise jobs.JobCancelled()
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            done = data.get("downloaded_bytes") or 0
            percent = (done / total * 100) if total else 0.0
            store.update(job.id, state=jobs.DOWNLOADING,
                         percent=round(percent, 1), speed=data.get("speed"),
                         eta=data.get("eta"))
        elif status == "finished":
            store.update(job.id, state=jobs.CONVERTING, percent=100.0,
                         speed=None, eta=None)
        send()

    def postprocessor_hook(data: dict) -> None:
        # ffmpeg gives no percent, so the page only shows the state.
        store.update(job.id, state=jobs.CONVERTING, speed=None, eta=None)
        send()

    allow_private = not config.block_private_addresses()
    opts = build_opts(job.mode, job.workdir, job.format_id,
                      max_height=job.max_height,
                      max_filesize=config.max_filesize(),
                      progress_hook=progress_hook,
                      postprocessor_hook=postprocessor_hook)
    try:
        urlguard.check_url(job.url, allow_private=allow_private)
        with site_opts() as extra:
            with urlguard.guarded(allow_private=allow_private):
                try:
                    info = _extract({**opts, **extra}, job.url, download=True)
                except jobs.JobCancelled:
                    raise
                except Exception as error:  # yt-dlp raises many types
                    retry = retry_opts(error)
                    if retry is None:
                        raise
                    info = _extract({**opts, **extra, **retry}, job.url,
                                    download=True)
    except jobs.JobCancelled:
        jobs.delete_workdir(job)
        store.remove(job.id)
        return
    except Exception as error:  # yt-dlp raises many types
        store.update(job.id, state=jobs.ERROR, error=explain(error, job.mode))
        send()
        jobs.delete_workdir(job)
        return

    output = find_output(job.workdir)
    if output is None:
        store.update(job.id, state=jobs.ERROR,
                     error="the download produced no file")
    else:
        store.update(job.id, state=jobs.READY, percent=100.0, speed=None,
                     eta=None, title=(info or {}).get("title"),
                     filename=output.name, file_path=str(output))
    send()
