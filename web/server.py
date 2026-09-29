"""Small single-instance web downloader for public video URLs."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL


BASE = Path(__file__).resolve().parent
MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 5 * 60
MAX_ACTIVE = 1
JOB_LIFETIME = 15 * 60
ALLOWED_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "instagram.com", "tiktok.com")


def validate_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        invalid_address = parsed.username or parsed.password or parsed.port
    except ValueError:
        raise ValueError("Paste a valid HTTPS video link.") from None
    if parsed.scheme != "https" or not host or invalid_address:
        raise ValueError("Paste a valid HTTPS video link.")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS):
        raise ValueError("Use an Instagram, YouTube, or TikTok link.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Paste a link to a specific video, reel, short, or post.")
    parts = [part for part in parsed.path.split("/") if part]
    if host == "youtu.be" or host.endswith(".youtu.be"):
        single_video = len(parts) == 1
    elif host == "youtube.com" or host.endswith(".youtube.com") or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com"):
        single_video = (parts[0] == "watch" and bool(parse_qs(parsed.query).get("v"))) or (len(parts) == 2 and parts[0] in ("shorts", "live", "embed"))
    elif host == "instagram.com" or host.endswith(".instagram.com"):
        single_video = (len(parts) == 2 and parts[0] in ("p", "reel", "tv")) or (len(parts) == 3 and parts[1] in ("p", "reel", "tv"))
    else:
        single_video = (len(parts) >= 3 and parts[0].startswith("@") and parts[1] == "video") or (len(parts) == 2 and parts[0] == "t") or (host.startswith(("vm.", "vt.")) and len(parts) == 1)
    if not single_video:
        raise ValueError("Paste a link to one video, not a profile or playlist.")
    return value


class DownloadRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2048)


@dataclass
class Job:
    id: str
    url: str
    folder: Path
    created: float = field(default_factory=time.monotonic)
    status: str = "queued"
    progress: float = 0
    message: str = "Checking video…"
    title: str = ""
    filename: str = ""
    file_path: Path | None = None


app = FastAPI(title="Video Downloader", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


def cleanup_expired() -> None:
    now = time.monotonic()
    expired: list[Job] = []
    with jobs_lock:
        for job_id, job in list(jobs.items()):
            if now - job.created > JOB_LIFETIME and job.status not in ("queued", "downloading", "processing"):
                expired.append(jobs.pop(job_id))
    for job in expired:
        shutil.rmtree(job.folder, ignore_errors=True)


def job_payload(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "progress": round(job.progress, 1),
        "message": job.message,
        "title": job.title,
        "filename": job.filename,
    }


def download(job: Job) -> None:
    def progress(data: dict) -> None:
        if time.monotonic() - job.created > MAX_SECONDS:
            raise TimeoutError("This download took too long for the free service.")
        if data.get("status") == "downloading":
            received = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if received > MAX_BYTES or (total and total > MAX_BYTES):
                raise ValueError("This video exceeds the 100 MB limit of the free service.")
            with jobs_lock:
                job.status = "downloading"
                job.progress = min(99, received * 100 / total) if total else 0
                job.message = "Downloading video…"
        elif data.get("status") == "finished":
            with jobs_lock:
                job.status = "processing"
                job.message = "Finishing video…"

    try:
        with jobs_lock:
            job.status = "downloading"
        options = {
            "paths": {"home": str(job.folder)},
            "outtmpl": "%(title).150B [%(id)s].%(ext)s",
            "format": "bv*+ba/b",
            "merge_output_format": "mp4/mkv",
            "noplaylist": True,
            "max_filesize": MAX_BYTES,
            "progress_hooks": [progress],
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "fragment_retries": 2,
            "socket_timeout": 20,
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(job.url, download=True)

        files = [p for p in job.folder.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not files:
            raise RuntimeError("The site did not provide a downloadable video file.")
        video = max(files, key=lambda p: p.stat().st_size)
        if video.stat().st_size > MAX_BYTES:
            raise ValueError("This video exceeds the 100 MB limit of the free service.")
        with jobs_lock:
            job.file_path = video
            job.filename = video.name
            job.title = info.get("title", "Video") if isinstance(info, dict) else "Video"
            job.progress = 100
            job.status = "ready"
            job.message = "Ready to save"
    except Exception as exc:
        with jobs_lock:
            job.status = "error"
            job.message = str(exc).removeprefix("ERROR: ")[:240] or "Download failed."
        shutil.rmtree(job.folder, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((BASE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/jobs")
def create_job(body: DownloadRequest) -> JSONResponse:
    cleanup_expired()
    try:
        url = validate_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    with jobs_lock:
        active = sum(job.status in ("queued", "downloading", "processing") for job in jobs.values())
        if active >= MAX_ACTIVE:
            raise HTTPException(status_code=429, detail="Another download is running. Try again in a moment.")
        folder = Path(tempfile.mkdtemp(prefix="video-download-"))
        job = Job(id=secrets.token_urlsafe(18), url=url, folder=folder)
        jobs[job.id] = job
    threading.Thread(target=download, args=(job,), daemon=True).start()
    return JSONResponse(job_payload(job), status_code=202, headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    cleanup_expired()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download expired. Paste the link again.")
        payload = job_payload(job)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/file")
def get_file(job_id: str, background: BackgroundTasks) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.status != "ready" or not job.file_path or not job.file_path.is_file():
            raise HTTPException(status_code=404, detail="The video is not ready or has expired.")
        jobs.pop(job_id, None)
        path = job.file_path
        filename = job.filename
        folder = job.folder
    background.add_task(shutil.rmtree, folder, ignore_errors=True)
    return FileResponse(path, filename=filename, media_type="application/octet-stream", background=background)
