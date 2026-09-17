"""Kubernetes-agnostic composition root.

This is the only module that may choose a compute adapter. Application
service, certificates, matching, and UI depend on ports, not Kubernetes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .certificate import load_or_create_issuer_secret
from .registry import FileRegistry
from .service import ResourceShareService


def default_data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent / "data"


def build_service(
    data_root: Path | None = None,
    runtime_name: str | None = None,
    start_server: bool = True,
) -> ResourceShareService:
    root = data_root or default_data_root()
    root.mkdir(parents=True, exist_ok=True)
    from .compute.factory import create_backend, selected_backend_name
    from .network.server import NetworkServerManager
    from .network.tunnel import CloudflareTunnelManager

    runtime = runtime_name or selected_backend_name()
    svc = ResourceShareService(
        data_root=root,
        registry=FileRegistry(root),
        compute=create_backend(root / "vm-runtime", runtime),
        secret=load_or_create_issuer_secret(root / ".issuer_secret"),
    )
    svc.server_manager = NetworkServerManager(svc)
    svc.tunnel_manager = CloudflareTunnelManager(root)
    if start_server:
        try:
            svc.server_manager.start()
        except Exception:
            pass
    return svc
