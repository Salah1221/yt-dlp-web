"""Every call into yt-dlp lives here."""

from __future__ import annotations

from pathlib import Path

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
