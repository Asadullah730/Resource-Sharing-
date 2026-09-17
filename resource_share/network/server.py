from __future__ import annotations

import json
import os
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..service import ResourceShareService


def get_local_ip() -> str:
    """Determine primary LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just triggers routing resolution
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


def get_tailscale_ip() -> str | None:
    """Detect Tailscale mesh IP (100.x.y.z) if active."""
    try:
        import psutil

        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and addr.address.startswith("100."):
                    return addr.address
    except Exception:
        pass
    return None


class ResourceShareRequestHandler(BaseHTTPRequestHandler):
    server: ResourceShareHTTPServer

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/health":
            self._handle_health()
        elif path == "/api/stats":
            self._handle_stats()
        elif path.startswith("/api/session/") and path.endswith("/stats"):
            parts = path.split("/")
            session_id = parts[3]
            self._handle_session_stats(session_id)
        else:
            self._json_response(404, {"status": "error", "message": "Endpoint not found"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        body = self._read_json_body()
        if body is None:
            self._json_response(400, {"status": "error", "message": "Invalid JSON body"})
            return

        if path == "/api/use":
            self._handle_use_resources(body)
        elif path.startswith("/api/session/") and path.endswith("/exec"):
            parts = path.split("/")
            session_id = parts[3]
            self._handle_session_exec(session_id, body)
        else:
            self._json_response(404, {"status": "error", "message": "Endpoint not found"})

    def _handle_health(self) -> None:
        service = self.server.service
        backend_name, ok, reason = service.backend_status()
        self._json_response(
            200,
            {
                "status": "ok",
                "hostname": socket.gethostname(),
                "os": os.name,
                "local_ip": get_local_ip(),
                "backend": backend_name,
                "kubernetes_ready": ok and backend_name == "kubernetes",
                "backend_reason": reason,
            },
        )

    def _handle_stats(self) -> None:
        service = self.server.service
        try:
            inventory = service.inventory(cpu_interval=0.0)
            reserved = service.reserved_spec()
            backend_name, ok, reason = service.backend_status()

            instances = []
            for record in service.list_instances():
                offer = service.get_offer(record.offer_id)
                instances.append(
                    {
                        "instance_id": record.instance_id,
                        "status": record.status,
                        "spec": record.spec.as_dict(),
                        "target_user": offer.target_user if offer else "",
                        "purpose": offer.purpose if offer else "",
                        "consumer_user": record.consumer_user or "",
                        "fingerprint": record.fingerprint,
                    }
                )

            self._json_response(
                200,
                {
                    "status": "ok",
                    "host": inventory.as_dict(),
                    "reserved": reserved.as_dict(),
                    "instances": instances,
                    "backend": backend_name,
                    "kubernetes_ready": ok and backend_name == "kubernetes",
                },
            )
        except Exception as exc:
            self._json_response(500, {"status": "error", "message": str(exc)})

    def _handle_use_resources(self, body: dict[str, Any]) -> None:
        service = self.server.service
        sha_key = body.get("sha_key", "")
        cert_text = body.get("certificate_text", "")
        consumer_user = body.get("consumer_user", "consumer")
        req_dict = body.get("requested", {})

        cpu_text = str(req_dict.get("cpu_cores", "1"))
        ram_text = f"{req_dict.get('ram_gb', '1')} GB"
        disk_text = f"{req_dict.get('disk_gb', '10')} GB"

        try:
            result = service.use_resources(
                ram_text=ram_text,
                disk_text=disk_text,
                cpu_text=cpu_text,
                sha_key=sha_key,
                consumer_user=consumer_user,
                certificate_text=cert_text,
            )
            self._json_response(200, {"status": "ok", "data": result})
        except Exception as exc:
            self._json_response(400, {"status": "error", "message": str(exc)})

    def _handle_session_stats(self, session_id: str) -> None:
        service = self.server.service
        session = service.registry.get_session(session_id) if hasattr(service.registry, "get_session") else None
        inventory = service.inventory(cpu_interval=0.0)
        self._json_response(
            200,
            {
                "status": "ok",
                "host": inventory.as_dict(),
                "session": session.as_dict() if session else None,
            },
        )

    def _handle_session_exec(self, session_id: str, body: dict[str, Any]) -> None:
        service = self.server.service
        command = body.get("command", "").strip()
        if not command:
            self._json_response(400, {"status": "error", "message": "Command is required"})
            return

        try:
            output = service.execute_in_session(session_id, command)
            self._json_response(200, {"status": "ok", "output": output})
        except Exception as exc:
            self._json_response(500, {"status": "error", "message": str(exc)})

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return None

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json_response(self, code: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs
        pass


class ResourceShareHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], service: ResourceShareService):
        self.service = service
        super().__init__(server_address, ResourceShareRequestHandler)


class NetworkServerManager:
    """Manages the lifecycle of the local API server."""

    def __init__(self, service: ResourceShareService, base_port: int = 5890):
        self.service = service
        self.base_port = base_port
        self.actual_port = base_port
        self.httpd: ResourceShareHTTPServer | None = None
        self.server_thread: Thread | None = None
        self.is_running = False

    def start(self) -> int:
        """Start listening on 0.0.0.0 on base_port or next available."""
        if self.is_running:
            return self.actual_port

        for port in range(self.base_port, self.base_port + 20):
            try:
                self.httpd = ResourceShareHTTPServer(("0.0.0.0", port), self.service)
                self.actual_port = port
                break
            except OSError:
                continue

        if self.httpd is None:
            raise RuntimeError(f"Could not bind to any port from {self.base_port} to {self.base_port + 20}")

        self.is_running = True
        self.server_thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        return self.actual_port

    def stop(self) -> None:
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
        self.is_running = False
