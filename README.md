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
| Host | `127.0.0.1` | `127.0.0.1` behind a proxy, or any other address |
| Password | none | `YTDLP_WEB_PASSWORD` is set |
| Outbound address guard | off | on |
| Who can reach it | this machine only | anyone with the password |

The mode is decided by two things, and either one turns public mode on: the password is set, or the binding is not loopback. The password is the one that matters behind a proxy. A proxied server binds to `127.0.0.1` and the internet still reaches it, so the binding on its own cannot decide this.

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
| `YTDLP_WEB_COOKIES` | none | a `cookies.txt` file to send to the site |
| `YTDLP_WEB_COOKIE_STORE` | beside the work folders | where the Settings panel saves the cookies |
| `YTDLP_WEB_COOKIES_FROM_BROWSER` | none | a browser profile on this machine to read the cookies from |
| `YTDLP_WEB_PLAYER_CLIENT` | none | the YouTube clients to ask, in order, such as `tv,web_safari` |
| `YTDLP_WEB_JS_RUNTIMES` | `deno` | the JavaScript runtimes yt-dlp may use, such as `node` |

### "Sign in to confirm you're not a bot"

A site answers that way when it wants a signed in visitor. It asks a server
more often than a home connection, because many people share one server
address.

Export the cookies of a browser that is signed in, press **Settings** on the
page, choose the file, and press Save. The next download uses them, and
nothing restarts. The box empties the moment it has the text, so nothing a
person can read or copy again stays on the page. The panel shows how many
cookies it holds and when the first one expires, and it never shows the
cookies themselves. Remove deletes them.

`YTDLP_WEB_COOKIES` does the same thing from the environment file, for a
server that must come up with cookies already in place. A file saved in the
panel wins over that one. `docs/cookies.md` holds the steps for both, and
the page says what to do when the message arrives.

On your own machine, `YTDLP_WEB_COOKIES_FROM_BROWSER=firefox` reads the
browser profile instead, and no export is needed.

The cookie file holds a live session of your account. Give it mode 640 and
keep it out of the code folder.

Two settings can help without a cookie, and neither always works:

- `YTDLP_WEB_JS_RUNTIMES`. yt-dlp answers the signature challenge of YouTube
  in JavaScript, and it looks for deno alone by itself. With no runtime it
  falls back to the one client that needs none, which gives fewer formats and
  meets the check more often. Install deno, or name the runtime you have:
  `YTDLP_WEB_JS_RUNTIMES=node`. The server writes a warning at startup when it
  finds none. The list replaces the default, so naming `node` turns deno off.
- `YTDLP_WEB_PLAYER_CLIENT`. YouTube serves the same video to a phone, a
  television, and a browser, and it applies the check to each differently.
  `YTDLP_WEB_PLAYER_CLIENT=tv,web_safari` asks them in that order. Which
  client answers changes from month to month, so treat it as something to
  try, not as a fix.

The check follows the address more than anything else. The same URL that
fails on a rented server often works from a home connection, where this
application was made to run.

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
