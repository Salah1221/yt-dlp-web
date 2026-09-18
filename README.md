# yt-dlp web

A local web page that downloads a video from a URL. It gives a merged MP4, an
MP3, or a format that you select. The page shows live progress. The server
keeps no file after your browser download completes.

## Requirements

- Python 3.11 or later
- ffmpeg on PATH

## Install

```powershell
python -m pip install -r requirements.txt
```

## Start

```powershell
.\run.ps1
```

Then open <http://127.0.0.1:8000>.

## Use

1. Paste a video URL.
2. Press Check. The page shows the title and the length.
3. Press Video MP4, or Audio MP3, or Choose a format.
4. Watch the bar. The state goes from Downloading to Converting.
5. Press Download. Your browser saves the file.

The server deletes its copy after the browser download completes. A download
that you never collect is deleted after 30 minutes.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

The tests use no video site. A fixture makes a one second MP4 with ffmpeg and
serves it on the loopback address.

## Limits

- The server binds to `127.0.0.1` only. Do not put it behind a tunnel or a
  reverse proxy. The loopback binding is the only access control, and a proxy
  removes it.
- A 4K video needs the video stream, the audio stream, and the merged output on
  the disk at the same time. Plan for about 2.5 times the size of the final file.
- The job records live in memory. A restart of the server loses every job.
- There is no queue, no playlist support, and no history.
- Download only the material that you have the right to download.
