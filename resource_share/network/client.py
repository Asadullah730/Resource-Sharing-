from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def normalize_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = f"http://{url}"
    return url


class RemoteResourceClient:
    """Client for System B to communicate with System A over Cloudflare or direct IP."""

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    def _request(self, method: str, url: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        req_data = None
        headers = {"User-Agent": "ResourceShare-Client/1.0"}
        if data is not None:
            req_data = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                content = response.read().decode("utf-8")
                return json.loads(content)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                raise RuntimeError(err_json.get("message", f"HTTP {exc.code}: {exc.reason}")) from exc
            except json.JSONDecodeError:
                raise RuntimeError(f"HTTP {exc.code}: {err_body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach provider at {url}: {exc.reason}") from exc
        except Exception as exc:
            raise RuntimeError(f"Connection error: {exc}") from exc

    def ping(self, base_url: str) -> dict[str, Any]:
        url = f"{normalize_url(base_url)}/api/health"
        return self._request("GET", url)

    def get_stats(self, base_url: str) -> dict[str, Any]:
        url = f"{normalize_url(base_url)}/api/stats"
        return self._request("GET", url)

    def get_session_stats(self, base_url: str, session_id: str) -> dict[str, Any]:
        url = f"{normalize_url(base_url)}/api/session/{session_id}/stats"
        return self._request("GET", url)

    def use_resources(
        self,
        base_url: str,
        *,
        sha_key: str,
        certificate_text: str,
        consumer_user: str,
        cpu_cores: float,
        ram_gb: float,
        disk_gb: float,
    ) -> dict[str, Any]:
        url = f"{normalize_url(base_url)}/api/use"
        payload = {
            "sha_key": sha_key,
            "certificate_text": certificate_text,
            "consumer_user": consumer_user,
            "requested": {
                "cpu_cores": cpu_cores,
                "ram_gb": ram_gb,
                "disk_gb": disk_gb,
            },
        }
        res = self._request("POST", url, payload)
        if res.get("status") == "ok":
            return res.get("data", {})
        raise RuntimeError(res.get("message", "Failed to use resources"))

    def execute_command(self, base_url: str, session_id: str, command: str) -> str:
        url = f"{normalize_url(base_url)}/api/session/{session_id}/exec"
        res = self._request("POST", url, {"command": command})
        if res.get("status") == "ok":
            return str(res.get("output", ""))
        raise RuntimeError(res.get("message", "Command execution failed"))
