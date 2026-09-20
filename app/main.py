"""The FastAPI application for the yt-dlp web page."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (FastAPI, HTTPException, Request, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import (auth, cleanup, config, cookiestore, downloader, jobs,
               limits, urlguard)

# uvicorn runs this application, and this is the logger it formats and
# sends to its own output. A logger of our own would reach the journal
# without a level in front of it.
log = logging.getLogger("uvicorn.error")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# A wrong password costs a second. This slows a guesser, and a person who
# types the password wrongly does not notice one second.
FAILED_LOGIN_DELAY = 1.0

# These paths answer without a cookie. Everything else needs one.
PUBLIC_PATHS = frozenset({"/login", "/api/login", "/api/logout"})


class ProbeRequest(BaseModel):
    url: str


class JobRequest(BaseModel):
    url: str
    mode: str
    format_id: str | None = None
    max_height: int | None = None


class LoginRequest(BaseModel):
    password: str


class CookieRequest(BaseModel):
    text: str


def content_disposition(filename: str) -> str:
    """Build a header that holds an ASCII name and a UTF-8 name.

    RFC 5987 defines the second form. A title can hold a character that
    is not ASCII, and an old browser reads the first form only.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    ascii_name = ascii_name.replace('"', "_").replace("\\", "_")
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/static/")


def client_key(request: Request) -> str:
    """Return the address to count failed logins against.

    Behind the proxy the real address arrives in X-Forwarded-For. A client
    that talks to this server directly can write that header itself, so
    this value slows a guesser but does not identify anybody.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def warn_about_the_js_runtime() -> None:
    """Say what runs the JavaScript that YouTube needs, or that nothing does.

    yt-dlp answers the signature challenge of YouTube in JavaScript, and
    it looks for deno alone. Without a runtime it throws away every
    format that carries a signature, and the download then finds none.
    It only warns, because every other site keeps working.
    """
    trouble = downloader.js_runtime_trouble()
    if trouble:
        log.warning(
            "%s, so YouTube will serve this server almost nothing. Install "
            "deno, or install a version of node that yt-dlp supports and set "
            "%s=node.", trouble, config.JS_RUNTIME_ENV)
        return
    found = downloader.js_runtime_auto()
    if found and not config.js_runtimes():
        log.info("no deno on PATH, so yt-dlp runs YouTube with %s.",
                 ", ".join(found))


def create_app(store: jobs.JobStore | None = None) -> FastAPI:
    root = config.temp_root()
    root.mkdir(parents=True, exist_ok=True)
    job_store = store or jobs.JobStore(root, config.job_ttl())
    slots = limits.JobSlots(config.max_jobs())
    limiter = auth.LoginLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.check_startup()
        config.check_cookies()
        config.check_js_runtimes()
        downloader.check_player_clients()
        warn_about_the_js_runtime()
        # Wrap the socket layer once, so a redirect to a private address
        # is caught at connection time and not only before the request.
        urlguard.install()
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg is not on PATH. Install ffmpeg, then start the server again.")
        job_store.attach_loop(asyncio.get_running_loop())
        task = asyncio.create_task(cleanup.janitor(
            job_store, root, config.job_ttl(),
            config.CLEANUP_INTERVAL_SECONDS))
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="yt-dlp web", lifespan=lifespan)
    app.state.store = job_store
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        secret = config.password()
        if secret is None or is_public_path(request.url.path):
            return await call_next(request)
        if auth.check_cookie(request.cookies.get(auth.COOKIE_NAME), secret):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "log in first"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def page_config() -> dict:
        """Tell the page whether a login is in use.

        The session cookie is HttpOnly, so the page cannot read it and
        cannot work this out by itself.
        """
        return {"login": config.require_login()}

    @app.get("/login")
    def login_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "login.html")

    @app.post("/api/login")
    def login(body: LoginRequest, request: Request):
        secret = config.password()
        if secret is None:
            return JSONResponse({"ok": True})
        key = client_key(request)
        if not limiter.allow(key):
            raise HTTPException(status_code=429,
                                detail="too many attempts, wait and try again")
        if not auth.check_password(body.password, secret):
            limiter.record_failure(key)
            if FAILED_LOGIN_DELAY:
                time.sleep(FAILED_LOGIN_DELAY)
            raise HTTPException(status_code=401, detail="wrong password")
        limiter.record_success(key)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            auth.COOKIE_NAME, auth.make_cookie(secret),
            max_age=auth.SESSION_SECONDS, httponly=True, samesite="lax",
            # A Secure cookie never crosses plain HTTP. On a loopback
            # binding there is no TLS, so the flag would block the cookie.
            secure=not config.is_loopback_host(config.host()), path="/")
        return response

    @app.post("/api/logout")
    def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return response

    @app.get("/api/cookies")
    def cookie_status() -> dict:
        """Say what cookies the server holds, and never what they are."""
        return cookiestore.status()

    @app.put("/api/cookies")
    def save_cookies(body: CookieRequest) -> dict:
        try:
            return cookiestore.save(body.text)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except OSError:
            raise HTTPException(
                status_code=500,
                detail="the server cannot write the cookie file. Check that "
                       "the service user owns the folder it goes in.")

    @app.delete("/api/cookies")
    def clear_cookies() -> dict:
        cookiestore.clear()
        return cookiestore.status()

    @app.post("/api/probe")
    async def probe(request: ProbeRequest) -> dict:
        try:
            return await asyncio.to_thread(downloader.probe, request.url)
        except Exception as error:
            raise HTTPException(status_code=400, detail=str(error))

    @app.post("/api/jobs")
    async def start_job(request: JobRequest) -> dict:
        if request.mode not in downloader.MODES:
            raise HTTPException(status_code=400,
                                detail="mode must be video, audio, or format")
        if request.mode == "format" and not request.format_id:
            raise HTTPException(status_code=400,
                                detail="mode 'format' needs a format_id")
        if request.max_height is not None and request.max_height <= 0:
            raise HTTPException(status_code=400,
                                detail="max_height must be more than zero")
        if not limits.has_room(root, config.min_free_bytes()):
            raise HTTPException(status_code=507,
                                detail="not enough free disk space for a download")
        if not slots.take():
            raise HTTPException(
                status_code=429,
                detail="a download is already running, try again when it ends")

        job = job_store.create(request.url, request.mode, request.format_id,
                               request.max_height)

        async def run_and_free() -> None:
            try:
                await asyncio.to_thread(downloader.run, job, job_store)
            finally:
                slots.give_back()

        asyncio.create_task(run_and_free())
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def job_state(job_id: str) -> dict:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        return job.public()

    @app.get("/api/jobs/{job_id}/file")
    def job_file(job_id: str) -> FileResponse:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        if job.state != jobs.READY or not job.file_path:
            raise HTTPException(status_code=409,
                                detail=f"the job is {job.state}")
        path = Path(job.file_path)
        if not path.is_file():
            raise HTTPException(status_code=410, detail="the file is gone")

        def cleanup_after_send() -> None:
            jobs.delete_workdir(job)
            job_store.remove(job_id)

        return FileResponse(
            path,
            media_type="application/octet-stream",
            headers={"Content-Disposition": content_disposition(path.name)},
            background=BackgroundTask(cleanup_after_send),
        )

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> dict:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        job_store.update(job_id, cancelled=True)
        if job.state in jobs.TERMINAL_STATES:
            jobs.delete_workdir(job)
            job_store.remove(job_id)
        return {"cancelled": True}

    @app.websocket("/ws/{job_id}")
    async def job_progress(websocket: WebSocket, job_id: str) -> None:
        # The HTTP middleware does not see a WebSocket, so the cookie is
        # checked here. The browser sends cookies on the handshake.
        secret = config.password()
        if secret is not None and not auth.check_cookie(
                websocket.cookies.get(auth.COOKIE_NAME), secret):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        job = job_store.get(job_id)
        if job is None:
            await websocket.close(code=4404)
            return
        queue = job_store.queue_for(job_id)
        try:
            await websocket.send_json(job.public())
            if job.state in jobs.TERMINAL_STATES:
                await websocket.close()
                return
            while True:
                payload = await queue.get()
                await websocket.send_json(payload)
                if payload.get("state") in jobs.TERMINAL_STATES:
                    break
            await websocket.close()
        except WebSocketDisconnect:
            # The page went away. The job keeps running.
            return

    return app


app = create_app()
