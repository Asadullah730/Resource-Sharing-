from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

CLOUDFLARED_DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
)
TUNNEL_URL_REGEX = re.compile(r"https://(?!(?:api|developers|pkg|blog|www)\.)[a-zA-Z0-9-]+\.trycloudflare\.com")


class CloudflareTunnelManager:
    """Manages an automatic Cloudflare Quick Tunnel for cross-Wi-Fi access."""

    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.bin_dir = data_root / "bin"
        self.process: subprocess.Popen | None = None
        self.tunnel_url: str | None = None
        self._is_starting = False
        self._stop_event = threading.Event()
        atexit.register(self.stop_tunnel)

    def find_binary(self) -> Path | None:
        """Find cloudflared in PATH or data/bin/."""
        on_path = shutil.which("cloudflared")
        if on_path:
            return Path(on_path)
        local_bin = self.bin_dir / "cloudflared.exe"
        if local_bin.exists() and local_bin.stat().st_size > 100000:
            return local_bin
        return None

    def ensure_binary(self, progress_callback: Callable[[str], None] | None = None) -> Path:
        """Ensure cloudflared binary exists, downloading if necessary."""
        existing = self.find_binary()
        if existing:
            return existing

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        target = self.bin_dir / "cloudflared.exe"
        tmp_target = self.bin_dir / "cloudflared.exe.tmp"

        if progress_callback:
            progress_callback("Downloading Cloudflare tunnel helper (one-time setup)...")

        # Download with timeout and user-agent
        req = urllib.request.Request(
            CLOUDFLARED_DOWNLOAD_URL,
            headers={"User-Agent": "ResourceShare-CrossNetwork/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(tmp_target, "wb") as out_file:
            shutil.copyfileobj(response, out_file)

        if tmp_target.exists():
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            tmp_target.rename(target)

        return target

    def start_tunnel(
        self,
        local_port: int = 5890,
        status_callback: Callable[[str, str | None], None] | None = None,
    ) -> None:
        """Start tunnel in a background thread."""
        if self.process is not None and self.process.poll() is None:
            if status_callback and self.tunnel_url:
                status_callback("active", self.tunnel_url)
            return

        self._stop_event.clear()
        self._is_starting = True

        def _worker():
            try:
                if status_callback:
                    status_callback("starting", None)
                binary = self.ensure_binary(
                    progress_callback=lambda msg: status_callback and status_callback(msg, None)
                )

                cmd = [
                    str(binary),
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{local_port}",
                    "--no-autoupdate",
                ]

                # Hide console window on Windows
                startupinfo = None
                creationflags = 0
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                    encoding="utf-8",
                    errors="replace",
                )

                # Monitor output to catch the tunnel URL
                url_found = False
                last_error = ""
                assert self.process.stdout is not None
                for line in iter(self.process.stdout.readline, ""):
                    if self._stop_event.is_set():
                        break
                    line_str = line.strip()
                    if "error" in line_str.lower() or "failed" in line_str.lower() or "timeout" in line_str.lower():
                        last_error = line_str

                    match = TUNNEL_URL_REGEX.search(line)
                    if match and not url_found:
                        cand = match.group(0).strip()
                        sub = cand.replace("https://", "").split(".trycloudflare.com")[0].lower()
                        if sub in ("api", "developers", "pkg", "blog", "www"):
                            continue
                        self.tunnel_url = cand
                        url_found = True
                        self._is_starting = False
                        if status_callback:
                            status_callback("active", self.tunnel_url)

                self.process.wait()
                self.tunnel_url = None
                self._is_starting = False
                if not self._stop_event.is_set() and status_callback:
                    if not url_found or self.process.returncode != 0:
                        msg = last_error or f"Process exited with code {self.process.returncode}"
                        status_callback(f"error: {msg}", None)
                    else:
                        status_callback("offline", None)
            except Exception as exc:
                self._is_starting = False
                self.tunnel_url = None
                if status_callback:
                    status_callback(f"error: {exc}", None)
            finally:
                self._is_starting = False

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def stop_tunnel(self) -> None:
        """Terminate the running tunnel process."""
        self._stop_event.set()
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.tunnel_url = None
        self._is_starting = False

    def is_active(self) -> bool:
        return self.process is not None and self.process.poll() is None and bool(self.tunnel_url)

    def is_starting(self) -> bool:
        return self._is_starting

    def get_url(self) -> str | None:
        return self.tunnel_url if self.is_active() else None
