from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@dataclass
class ResourceSpec:
    cpu_cores: float
    ram_gb: float
    disk_gb: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def fits_inside(self, other: ResourceSpec) -> bool:
        return (
            self.cpu_cores <= other.cpu_cores
            and self.ram_gb <= other.ram_gb
            and self.disk_gb <= other.disk_gb
        )

    def label(self) -> str:
        return f"{self.cpu_cores:g} CPU, {self.ram_gb:g} GB RAM, {self.disk_gb:g} GB disk"

    def remaining_after(self, reserved: ResourceSpec) -> ResourceSpec:
        return ResourceSpec(
            cpu_cores=round(max(self.cpu_cores - reserved.cpu_cores, 0), 2),
            ram_gb=round(max(self.ram_gb - reserved.ram_gb, 0), 2),
            disk_gb=round(max(self.disk_gb - reserved.disk_gb, 0), 2),
        )


@dataclass
class HostInventory:
    hostname: str
    ip: str
    os: str
    architecture: str
    cpu_name: str
    physical_cores: int
    logical_cores: int
    cpu_usage_percent: float
    ram_total_gb: float
    ram_available_gb: float
    disk_total_gb: float
    disk_free_gb: float
    username: str = ""
    ram_percent: float = 0.0
    disk_percent: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ram_used_gb(self) -> float:
        return round(max(self.ram_total_gb - self.ram_available_gb, 0), 2)

    def disk_used_gb(self) -> float:
        return round(max(self.disk_total_gb - self.disk_free_gb, 0), 2)

    def summary_text(self) -> str:
        user = f"  |  User: {self.username}" if self.username else ""
        return (
            f"OS: {self.os} ({self.architecture})\n"
            f"Hostname: {self.hostname}  |  IP: {self.ip}{user}\n"
            f"Processor: {self.cpu_name}\n"
            f"CPU Cores: {self.physical_cores} physical, {self.logical_cores} logical"
            f"  |  Usage: {self.cpu_usage_percent}%\n"
            f"RAM: {self.ram_available_gb} GB available / {self.ram_total_gb} GB total"
            f" ({self.ram_percent}%)\n"
            f"Disk: {self.disk_free_gb} GB free / {self.disk_total_gb} GB total"
            f" ({self.disk_percent}%)"
        )


@dataclass
class ShareOffer:
    offer_id: str
    provider_user: str
    target_user: str
    purpose: str
    allocated: ResourceSpec
    host: HostInventory
    created_at: str
    expires_at: str
    fingerprint: str
    instance_id: str
    backend: str
    status: str = "offered"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allocated"] = self.allocated.as_dict()
        data["host"] = self.host.as_dict()
        return data


@dataclass
class ShareCertificate:
    version: str
    offer_id: str
    instance_id: str
    issuer_host: str
    provider_user: str
    target_user: str
    purpose: str
    allocated: ResourceSpec
    issued_at: str
    expires_at: str
    fingerprint: str
    signature: str

    def payload_for_hash(self) -> dict[str, Any]:
        """Fields covered by the SHA fingerprint (signature excluded).

        Runtime names (local, docker, kubernetes) are not part of the ticket.
        """
        return {
            "allocated": self.allocated.as_dict(),
            "expires_at": self.expires_at,
            "instance_id": self.instance_id,
            "issued_at": self.issued_at,
            "issuer_host": self.issuer_host,
            "offer_id": self.offer_id,
            "provider_user": self.provider_user,
            "purpose": self.purpose,
            "target_user": self.target_user,
            "version": self.version,
        }

    def as_dict(self) -> dict[str, Any]:
        data = self.payload_for_hash()
        data["fingerprint"] = self.fingerprint
        data["signature"] = self.signature
        return data


@dataclass
class InstanceRecord:
    instance_id: str
    offer_id: str
    fingerprint: str
    backend: str
    name: str
    spec: ResourceSpec
    status: str
    workspace: str
    created_at: str
    handle: dict[str, Any] = field(default_factory=dict)
    consumer_user: str | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spec"] = self.spec.as_dict()
        return data


@dataclass
class AccessSession:
    session_id: str
    instance_id: str
    fingerprint: str
    consumer_user: str
    requested: ResourceSpec
    attached_at: str
    workspace: str
    connection: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requested"] = self.requested.as_dict()
        return data
