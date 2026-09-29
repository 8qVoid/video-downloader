"""Local video downloader for links the user is allowed to save."""

from __future__ import annotations

import os
import queue
import re
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

import deno
import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


APP_NAME = "Video Downloader"
DEFAULT_FOLDER = Path.home() / "Downloads" / "Video Downloader"
ALLOWED_HOSTS = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
)


def clean_url(value: str) -> str:
    """Accept only ordinary HTTPS video-page URLs from the supported sites."""
    value = value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise ValueError("Paste a complete video link beginning with https://")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS):
        raise ValueError("Use an Instagram, YouTube, or TikTok link.")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("This link contains an unsupported address or port.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Paste a link to a video, reel, short, or post.")
    return value


def human_bytes(value: float | int | None) -> str:
    if not value:
        return ""
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return ""


def prepare_media_tools() -> str:
    """Expose the bundled binaries under the names yt-dlp expects."""
    deno_bin = Path(deno.find_deno_bin())
    ffmpeg_bin = Path(imageio_ffmpeg.get_ffmpeg_exe())
    alias = deno_bin.parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not alias.exists() or not os.path.samefile(alias, ffmpeg_bin):
        if alias.exists():
            alias.unlink()
        try:
            os.link(ffmpeg_bin, alias)
        except OSError:
            shutil.copy2(ffmpeg_bin, alias)
    os.environ["PATH"] = str(deno_bin.parent) + os.pathsep + os.environ.get("PATH", "")
    return str(ffmpeg_bin)


class QueueLogger:
    def __init__(self, events: queue.Queue):
        self.events = events

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.events.put(("warning", message))

    def error(self, message: str) -> None:
        self.events.put(("warning", message))


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.folder = tk.StringVar(value=str(DEFAULT_FOLDER))
        self.url = tk.StringVar()
        self.browser = tk.StringVar(value="None")
        self.status = tk.StringVar(value="Ready to download")
        self.detail = tk.StringVar(value="Paste a link to a public video, reel, or short.")
        self._setup_style()
        self._build_ui()
        self.root.after(100, self._process_events)

    def _setup_style(self) -> None:
        self.root.title(APP_NAME)
        self.root.geometry("690x485")
        self.root.minsize(560, 440)
        self.root.configure(bg="#101827")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#101827")
        style.configure("TLabel", background="#101827", foreground="#e8edf5", font=("Segoe UI", 10))
        style.configure("Hint.TLabel", foreground="#a9b7ca", font=("Segoe UI", 9))
        style.configure("Title.TLabel", foreground="#ffffff", font=("Segoe UI Semibold", 23))
        style.configure("TEntry", fieldbackground="#1d2939", foreground="#ffffff", insertcolor="#ffffff", borderwidth=1, padding=9)
        style.configure("TCombobox", fieldbackground="#1d2939", foreground="#ffffff", padding=6)
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(14, 9))
        style.configure("Download.TButton", background="#65d6c2", foreground="#0b1722")
        style.map("Download.TButton", background=[("active", "#8be5d4"), ("disabled", "#597c79")])
        style.configure("Horizontal.TProgressbar", troughcolor="#263346", background="#65d6c2", borderwidth=0)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=27)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Video Downloader", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Instagram  ·  YouTube  ·  TikTok", style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 24))

        ttk.Label(frame, text="Video link").grid(row=2, column=0, sticky="w")
        self.url_entry = ttk.Entry(frame, textvariable=self.url)
        self.url_entry.grid(row=3, column=0, sticky="ew", pady=(7, 17))
        self.url_entry.focus_set()
        self.url_entry.bind("<Return>", lambda _event: self.start())

        ttk.Label(frame, text="Save to").grid(row=4, column=0, sticky="w")
        folder_row = ttk.Frame(frame)
        folder_row.grid(row=5, column=0, sticky="ew", pady=(7, 17))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = ttk.Button(folder_row, text="Browse", command=self.browse)
        self.browse_button.grid(row=0, column=1, padx=(8, 0))

        options = ttk.Frame(frame)
        options.grid(row=6, column=0, sticky="ew")
        ttk.Label(options, text="Browser login (optional)").pack(side="left")
        self.browser_box = ttk.Combobox(options, textvariable=self.browser, values=("None", "Chrome", "Edge", "Firefox", "Brave"), state="readonly", width=12)
        self.browser_box.pack(side="left", padx=(12, 0))
        ttk.Label(frame, text="Choose a browser only if the site asks you to log in. Your login stays on this computer.", style="Hint.TLabel", wraplength=610).grid(row=7, column=0, sticky="w", pady=(6, 17))

        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, sticky="w")
        self.download_button = ttk.Button(buttons, text="Download video", style="Download.TButton", command=self.start)
        self.download_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.stop, state="disabled")
        self.cancel_button.pack(side="left", padx=(10, 0))
        ttk.Button(buttons, text="Open folder", command=self.open_folder).pack(side="left", padx=(10, 0))

        ttk.Separator(frame).grid(row=9, column=0, sticky="ew", pady=(22, 15))
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI Semibold", 11)).grid(row=10, column=0, sticky="w")
        self.progress = ttk.Progressbar(frame, maximum=100, mode="determinate")
        self.progress.grid(row=11, column=0, sticky="ew", pady=(9, 8))
        ttk.Label(frame, textvariable=self.detail, style="Hint.TLabel", wraplength=610).grid(row=12, column=0, sticky="w")

    def browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if selected:
            self.folder.set(selected)

    def open_folder(self) -> None:
        path = Path(self.folder.get()).expanduser()
        if not path.is_dir():
            messagebox.showinfo(APP_NAME, "The download folder has not been created yet.")
            return
        if os.name == "nt":
            os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", str(path)])

    def start(self) -> None:
        if self.busy:
            return
        try:
            url = clean_url(self.url.get())
            if not self.folder.get().strip():
                raise ValueError("Choose a download folder.")
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if not folder.is_dir():
                raise ValueError("Choose a valid download folder.")
        except (ValueError, OSError) as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return

        self.cancel.clear()
        self.busy = True
        self.progress["value"] = 0
        self.status.set("Connecting…")
        self.detail.set("Checking the link and available formats.")
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.browser_box.configure(state="disabled")
        browser = self.browser.get()
        threading.Thread(target=self._download, args=(url, folder, browser), daemon=True).start()

    def stop(self) -> None:
        self.cancel.set()
        self.status.set("Cancelling…")
        self.detail.set("The current network request may take a moment to stop.")
        self.cancel_button.configure(state="disabled")

    def _download(self, url: str, folder: Path, browser: str) -> None:
        def progress(data: dict) -> None:
            if self.cancel.is_set():
                raise InterruptedError("Download cancelled")
            if data.get("status") == "downloading":
                downloaded = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                percent = min(100, downloaded / total * 100) if total else None
                speed = human_bytes(data.get("speed"))
                label = f"{human_bytes(downloaded)} downloaded"
                if total:
                    label += f" of {human_bytes(total)}"
                if speed:
                    label += f"  ·  {speed}/s"
                self.events.put(("progress", percent, label))
            elif data.get("status") == "finished":
                self.events.put(("processing",))

        try:
            # These packages ship the actual executables, so no separate setup is needed.
            ffmpeg_bin = prepare_media_tools()
            options = {
                "paths": {"home": str(folder)},
                "outtmpl": "%(title).180B [%(id)s].%(ext)s",
                "format": "bv*+ba/b",
                "merge_output_format": "mp4/mkv",
                "ffmpeg_location": ffmpeg_bin,
                "noplaylist": True,
                "progress_hooks": [progress],
                "logger": QueueLogger(self.events),
                "quiet": True,
                "no_warnings": False,
                "retries": 3,
                "fragment_retries": 3,
            }
            if browser != "None":
                options["cookiesfrombrowser"] = (browser.lower(),)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            if self.cancel.is_set():
                self.events.put(("cancelled",))
            else:
                title = info.get("title", "Video") if isinstance(info, dict) else "Video"
                self.events.put(("done", title))
        except (InterruptedError, DownloadError) as exc:
            if self.cancel.is_set():
                self.events.put(("cancelled",))
            else:
                message = str(exc)
                if "DPAPI" in message:
                    message = "Chrome's saved login could not be read. Select None for public videos, or try Firefox for a video that needs login."
                self.events.put(("error", message))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self.status.set("Downloading…")
                    percent = event[1]
                    if percent is not None:
                        self.progress["value"] = percent
                    self.detail.set(event[2])
                elif kind == "processing":
                    self.status.set("Finishing video…")
                    self.detail.set("Combining audio and video when needed.")
                elif kind == "warning":
                    message = re.sub(r"\x1b\[[0-9;]*m", "", event[1]).strip()
                    if message:
                        self.detail.set(message[:230])
                elif kind == "done":
                    self.progress["value"] = 100
                    self.status.set("Download complete")
                    self.detail.set(f"Saved “{event[1]}” to {self.folder.get()}")
                    self._set_idle()
                elif kind == "cancelled":
                    self.status.set("Download cancelled")
                    self.detail.set("You can paste another link and try again.")
                    self._set_idle()
                elif kind == "error":
                    self.status.set("Download failed")
                    self.detail.set(event[1][:280] or "The site did not provide a downloadable video.")
                    self._set_idle()
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _set_idle(self) -> None:
        self.busy = False
        self.download_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.browser_box.configure(state="readonly")


def main() -> None:
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
