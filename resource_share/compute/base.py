from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import ResourceSpec


@dataclass
class WorkloadSpec:
    """Portable workload description. Backends map this to their native objects.

    This is intentionally not a Kubernetes PodSpec, Docker HostConfig, or
    libvirt domain. Those details stay inside each backend adapter.
    """

    name: str
    spec: ResourceSpec
    workspace: str
    labels: dict[str, str] = field(default_factory=dict)
    command: list[str] | None = None


@dataclass
class InstanceHandle:
    instance_id: str
    backend: str
    native_id: str
    status: str
    workspace: str
    connection: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


class ComputeBackend(ABC):
    """Compute abstraction used by the share service.

    Swap backends with RESOURCE_SHARE_BACKEND=local|docker|kubernetes.
    Application code must depend only on this interface.
    """

    name: str

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (ok, reason) so the UI can show why a backend cannot run."""

    @abstractmethod
    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        ...

    @abstractmethod
    def start(self, handle: InstanceHandle) -> InstanceHandle:
        ...

    @abstractmethod
    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        ...

    @abstractmethod
    def status(self, handle: InstanceHandle) -> InstanceHandle:
        ...

    @abstractmethod
    def attach(self, handle: InstanceHandle, consumer_user: str) -> dict[str, Any]:
        """Return connection details for a consumer. Does not expose backend APIs."""

    @abstractmethod
    def destroy(self, handle: InstanceHandle) -> None:
        ...
