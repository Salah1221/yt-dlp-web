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
3. Pick a quality in the list beside Video MP4, or leave it on Best quality.
4. Press Video MP4, or Audio MP3, or Choose a format.
5. Watch the bar. The state goes from Downloading to Converting.
6. Press Download. Your browser saves the file.

The size beside each quality is an estimate. It comes from what the site reports,
it leaves out the container overhead, and a site that reports no size shows the
height alone.

The page works on a phone. In local mode the server binds to `127.0.0.1`, so a
phone cannot reach it. See the two modes below.

The server deletes its copy after the browser download completes. A download
that you never collect is deleted after 30 minutes.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

The tests use no video site. A fixture makes a one second MP4 with ffmpeg and
serves it on the loopback address.

## Two modes

| | Local mode | Public mode |
|---|---|---|
| Host | `127.0.0.1` | any other address, behind a proxy |
| Password | none | `YTDLP_WEB_PASSWORD` is required |
| Outbound address guard | off | on |
| Who can reach it | this machine only | anyone with the password |

The application refuses to start in the one unsafe combination: a host that is not loopback with no password set. It prints the reason and exits.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `YTDLP_WEB_PASSWORD` | none | the login password. Setting it turns the login on |
| `YTDLP_WEB_HOST` | `127.0.0.1` | the address to bind |
| `YTDLP_WEB_PORT` | `8000` | the port to bind |
| `YTDLP_WEB_TEMP_ROOT` | the system temporary folder | where a job works |
| `YTDLP_WEB_MAX_FILESIZE` | no limit | the largest file, in bytes |
| `YTDLP_WEB_MAX_JOBS` | 2 | how many downloads run together |
| `YTDLP_WEB_TTL` | 1800 | seconds before an uncollected file is deleted |

### The outbound address guard

In public mode the application checks every URL before yt-dlp sees it. It rejects any scheme that is not `http` or `https`, and it rejects a host that resolves to a loopback, private, link-local, reserved, multicast, or unspecified address. Link-local covers `169.254.169.254`, the cloud metadata service, which hands out instance credentials to anything on the machine.

The check runs a second time at connection time, so a redirect to a private address is also refused. That second layer wraps Python's socket layer. **Do not install `curl_cffi`.** An HTTP backend written in C opens its sockets inside the C library and never reaches the wrapper, which turns the second layer off without any warning.

In local mode the guard is off, so fetching from a device on your own network still works.

## Deploy on a server

See `deploy/README.md`. It holds the systemd unit, the nginx site file, and the steps in order.

## Limits

- In local mode the loopback binding is the only access control. Do not put
  local mode behind a tunnel or a reverse proxy, because that removes it. To
  reach the application from another machine, use public mode, which needs a
  password and a TLS proxy.
- A 4K video needs the video stream, the audio stream, and the merged output on
  the disk at the same time. Plan for about 2.5 times the size of the final file.
- The job records live in memory. A restart of the server loses every job.
- There is no queue, no playlist support, and no history.
- Download only the material that you have the right to download.
