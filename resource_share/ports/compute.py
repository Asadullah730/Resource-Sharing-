from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from ..models import ResourceSpec

CREATED = "created"
PENDING = "pending"
RUNNING = "running"
STOPPED = "stopped"
MISSING = "missing"
DESTROYED = "destroyed"
ERROR = "error"

DOMAIN_STATUSES = frozenset(
    {CREATED, PENDING, RUNNING, STOPPED, MISSING, DESTROYED, ERROR}
)
INACTIVE_STATUSES = frozenset({STOPPED, MISSING, DESTROYED, ERROR})
STARTABLE_STATUSES = frozenset({CREATED, STOPPED, PENDING})


def coerce_status(raw: str | None) -> str:
    """Map a value into the domain status set. Adapters must not leak Pod phases."""
    if not raw:
        return MISSING
    value = raw.strip().lower()
    if value in DOMAIN_STATUSES:
        return value
    return ERROR


@dataclass
class WorkloadSpec:
    """Portable workload. Not a PodSpec, HostConfig, or hypervisor domain."""

    name: str
    spec: ResourceSpec
    workspace: str
    labels: dict[str, str] = field(default_factory=dict)
    command: list[str] | None = None


@dataclass
class AccessGrant:
    """How a consumer attaches. Public fields stay runtime-agnostic.

    Adapter-specific commands (kubectl, docker exec) belong in ``details`` only.
    """

    method: str
    summary: str
    location: str
    instructions: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AccessGrant:
        payload = data or {}
        if payload.get("method"):
            return cls(
                method=str(payload.get("method") or "workspace"),
                summary=str(payload.get("summary") or ""),
                location=str(payload.get("location") or payload.get("path") or ""),
                instructions=str(payload.get("instructions") or ""),
                details=dict(payload.get("details") or {}),
            )
        kind = str(payload.get("kind") or "workspace")
        location = str(
            payload.get("path")
            or payload.get("mount")
            or payload.get("location")
            or ""
        )
        return cls(
            method="workspace" if kind == "workspace" else "shell",
            summary="Attached to isolated compute instance",
            location=location,
            instructions=str(payload.get("instructions") or ""),
            details={key: value for key, value in payload.items() if key != "instructions"},
        )

    def display_text(self) -> str:
        lines = [
            f"Method: {self.method}",
            self.summary,
            f"Location: {self.location}" if self.location else "",
            self.instructions,
        ]
        return "\n".join(line for line in lines if line)


@dataclass
class InstanceHandle:
    instance_id: str
    runtime: str
    native_id: str
    status: str
    workspace: str
    connection: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = coerce_status(self.status)


class ComputePort(ABC):
    """Compute runtime port. Core code depends on this, never on Kubernetes."""

    name: str

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (ok, reason) without exposing adapter APIs to the UI."""

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
    def attach(self, handle: InstanceHandle, consumer_user: str) -> AccessGrant:
        ...

    @abstractmethod
    def destroy(self, handle: InstanceHandle) -> None:
        ...

    def execute(self, handle: InstanceHandle, command: str) -> str:
        """Run a command inside the workload envelope."""
        return "Command execution not supported by this compute adapter."


# Backward-compatible name used by older adapter imports.
ComputeBackend = ComputePort
