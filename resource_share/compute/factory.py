from __future__ import annotations

import os
from pathlib import Path

from ..ports.compute import ComputePort

RUNTIMES = ("local", "docker", "kubernetes")


def selected_backend_name() -> str:
    name = os.environ.get("RESOURCE_SHARE_BACKEND", "kubernetes").strip().lower()
    if name not in RUNTIMES:
        raise ValueError(
            f"Unknown RESOURCE_SHARE_BACKEND={name!r}. Choose one of: {', '.join(RUNTIMES)}"
        )
    return name


def create_backend(instances_root: Path, name: str | None = None) -> ComputePort:
    """Load one adapter. Kubernetes is imported only when selected."""
    chosen = (name or selected_backend_name()).lower()
    if chosen == "local":
        from .local import LocalComputeBackend

        return LocalComputeBackend(instances_root)
    if chosen == "docker":
        from .docker import DockerComputeBackend

        return DockerComputeBackend(instances_root)
    if chosen == "kubernetes":
        from .kubernetes import KubernetesComputeBackend

        return KubernetesComputeBackend(instances_root)
    raise ValueError(f"Unsupported compute runtime: {chosen}")
