"""Every call into yt-dlp lives here."""

from __future__ import annotations

from pathlib import Path

from yt_dlp import YoutubeDL

from . import jobs

# yt-dlp writes these while a download runs. They are never the result.
SKIP_SUFFIXES = (".part", ".ytdl", ".temp")

MODES = ("video", "audio", "format")

# 150 bytes keeps the whole path under the Windows limit.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"


def build_opts(mode: str, workdir: str, format_id: str | None = None,
               progress_hook=None, postprocessor_hook=None) -> dict:
    """Return the yt-dlp options for one job."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    if mode == "format" and not format_id:
        raise ValueError("mode 'format' needs a format_id")

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

    if mode == "video":
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
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
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

    opts = build_opts(job.mode, job.workdir, job.format_id,
                      progress_hook, postprocessor_hook)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(job.url, download=True)
    except jobs.JobCancelled:
        jobs.delete_workdir(job)
        store.remove(job.id)
        return
    except Exception as error:  # yt-dlp raises many types
        store.update(job.id, state=jobs.ERROR, error=str(error))
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
