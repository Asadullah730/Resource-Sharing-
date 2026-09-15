from __future__ import annotations

import os
from pathlib import Path

from .base import ComputeBackend
from .docker import DockerComputeBackend
from .kubernetes import KubernetesComputeBackend
from .local import LocalComputeBackend

BACKENDS = ("local", "docker", "kubernetes")


def selected_backend_name() -> str:
    name = os.environ.get("RESOURCE_SHARE_BACKEND", "local").strip().lower()
    if name not in BACKENDS:
        raise ValueError(
            f"Unknown RESOURCE_SHARE_BACKEND={name!r}. Choose one of: {', '.join(BACKENDS)}"
        )
    return name


def create_backend(instances_root: Path, name: str | None = None) -> ComputeBackend:
    chosen = (name or selected_backend_name()).lower()
    if chosen == "local":
        return LocalComputeBackend(instances_root)
    if chosen == "docker":
        return DockerComputeBackend(instances_root)
    if chosen == "kubernetes":
        return KubernetesComputeBackend(instances_root)
    raise ValueError(f"Unsupported compute backend: {chosen}")
