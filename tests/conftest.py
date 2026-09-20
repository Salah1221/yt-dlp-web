"""Fixtures that serve a small real media file over local HTTP."""

from __future__ import annotations

import functools
import http.server
import shutil
import socket
import subprocess
import threading

import pytest


@pytest.fixture(autouse=True)
def no_token_server_unless_asked(monkeypatch):
    """Keep a token server that happens to be running off the tests.

    Whether one answers on the default port changes what the downloader
    asks YouTube for. A test that wants one says so with its own
    fixture; every other test runs as though there were none.
    """
    monkeypatch.setenv("YTDLP_WEB_POT_SERVER", "off")
    from app import downloader

    monkeypatch.setattr(downloader, "_token_server_seen",
                        {"at": 0.0, "ready": False, "version": None})


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    """Make a one second MP4 with video and audio."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not on PATH")
    folder = tmp_path_factory.mktemp("media")
    target = folder / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(target)],
        check=True, capture_output=True)
    return folder


@pytest.fixture(scope="session")
def media_url(media_dir):
    """Serve the media folder on the loopback address."""
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(media_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/clip.mp4"
    finally:
        server.shutdown()
        server.server_close()
