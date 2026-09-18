"""The FastAPI application for the local yt-dlp web page."""

from __future__ import annotations

import asyncio
import shutil
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import cleanup, config, downloader, jobs

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class ProbeRequest(BaseModel):
    url: str


class JobRequest(BaseModel):
    url: str
    mode: str
    format_id: str | None = None
    max_height: int | None = None


def content_disposition(filename: str) -> str:
    """Build a header that holds an ASCII name and a UTF-8 name.

    RFC 5987 defines the second form. A title can hold a character that
    is not ASCII, and an old browser reads the first form only.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    ascii_name = ascii_name.replace('"', "_").replace("\\", "_")
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def create_app(store: jobs.JobStore | None = None) -> FastAPI:
    root = config.temp_root()
    root.mkdir(parents=True, exist_ok=True)
    job_store = store or jobs.JobStore(root, config.JOB_TTL_SECONDS)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg is not on PATH. Install ffmpeg, then start the server again.")
        job_store.attach_loop(asyncio.get_running_loop())
        task = asyncio.create_task(cleanup.janitor(
            job_store, root, config.JOB_TTL_SECONDS,
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

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
        job = job_store.create(request.url, request.mode, request.format_id,
                               request.max_height)
        asyncio.create_task(asyncio.to_thread(downloader.run, job, job_store))
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
