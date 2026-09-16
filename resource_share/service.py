from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path

from .certificate import (
    decode_pem,
    encode_pem,
    issue_certificate,
    verify_certificate,
)
from .inventory import collect_host_inventory, parse_quantity
from .matching import assert_not_expired, assert_resources_fit
from .models import (
    AccessSession,
    HostInventory,
    InstanceRecord,
    ResourceSpec,
    ShareCertificate,
    ShareOffer,
    iso,
    utc_now,
)
from .ports.compute import (
    INACTIVE_STATUSES,
    STARTABLE_STATUSES,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
)
from .ports.registry import RegistryPort


class ResourceShareService:
    """Application use-cases. Depends only on ports, never on Kubernetes or Docker."""

    def __init__(
        self,
        data_root: Path,
        registry: RegistryPort,
        compute: ComputePort,
        secret: bytes,
    ):
        self.data_root = data_root
        self.registry = registry
        self.compute = compute
        self.secret = secret

    def runtime_status(self) -> tuple[str, bool, str]:
        ok, reason = self.compute.available()
        return self.compute.name, ok, reason

    def backend_status(self) -> tuple[str, bool, str]:
        return self.runtime_status()

    def inventory(self, cpu_interval: float = 0.2) -> HostInventory:
        return collect_host_inventory(cpu_interval=cpu_interval)

    def get_offer(self, offer_id: str) -> ShareOffer | None:
        return self.registry.get_offer(offer_id)

    def share_resources(
        self,
        *,
        ram_text: str,
        disk_text: str,
        cpu_text: str,
        target_user: str,
        provider_user: str = "",
        purpose: str = "shared-vm",
        ttl_days: int = 7,
    ) -> dict:
        host = collect_host_inventory()
        allocated = ResourceSpec(
            cpu_cores=parse_quantity(cpu_text),
            ram_gb=parse_quantity(ram_text),
            disk_gb=parse_quantity(disk_text),
        )
        self._validate_against_host(allocated, host)

        offer_id = uuid.uuid4().hex[:12]
        instance_id = f"vm-{offer_id}"
        created = utc_now()
        expires = created + timedelta(days=ttl_days)
        provider = provider_user.strip() or host.hostname
        target = target_user.strip()
        if not target:
            raise ValueError("Target user is required.")

        workspace = self.data_root / "vm-runtime" / instance_id
        workload = WorkloadSpec(
            name=instance_id,
            spec=allocated,
            workspace=str(workspace),
            labels={
                "offer_id": offer_id,
                "target_user": target,
                "purpose": purpose.strip() or "shared-vm",
            },
        )
        handle = self.compute.create_instance(workload)
        handle = self.compute.start(handle)
        grant = AccessGrant.from_dict(handle.connection)

        cert = issue_certificate(
            offer_id=offer_id,
            instance_id=instance_id,
            issuer_host=host.hostname,
            provider_user=provider,
            target_user=target,
            purpose=purpose.strip() or "shared-vm",
            allocated=allocated,
            issued_at=iso(created),
            expires_at=iso(expires),
            secret=self.secret,
        )
        json_path, pem_path = self.registry.save_certificate(cert)

        offer = ShareOffer(
            offer_id=offer_id,
            provider_user=provider,
            target_user=target,
            purpose=cert.purpose,
            allocated=allocated,
            host=host,
            created_at=iso(created),
            expires_at=iso(expires),
            fingerprint=cert.fingerprint,
            instance_id=instance_id,
            backend=self.compute.name,
            status="active",
        )
        self.registry.save_offer(offer)

        record = InstanceRecord(
            instance_id=instance_id,
            offer_id=offer_id,
            fingerprint=cert.fingerprint,
            backend=self.compute.name,
            name=workload.name,
            spec=allocated,
            status=handle.status,
            workspace=handle.workspace,
            created_at=iso(created),
            handle=_handle_to_dict(handle),
        )
        self.registry.save_instance(record)
        guest = self._write_guest_system(workspace, record, target, cert.purpose)

        return {
            "offer": offer.as_dict(),
            "certificate": cert.as_dict(),
            "sha_key": cert.fingerprint,
            "pem": encode_pem(cert),
            "pem_path": str(pem_path),
            "json_path": str(json_path),
            "instance": record.as_dict(),
            "connection": grant.as_dict(),
            "guest": guest,
        }

    def use_resources(
        self,
        *,
        ram_text: str,
        disk_text: str,
        cpu_text: str,
        sha_key: str,
        consumer_user: str,
        certificate_text: str = "",
    ) -> dict:
        requested = ResourceSpec(
            cpu_cores=parse_quantity(cpu_text),
            ram_gb=parse_quantity(ram_text),
            disk_gb=parse_quantity(disk_text),
        )
        cert = self._resolve_certificate(sha_key, certificate_text)
        verify_certificate(cert, self.secret)
        assert_not_expired(cert)
        assert_resources_fit(requested, cert.allocated)

        record = self.registry.get_instance(cert.instance_id)
        if record is None:
            raise ValueError("Certificate is valid but the virtual machine record is missing.")

        handle = _handle_from_record(record)
        handle = self.compute.status(handle)
        if handle.status in STARTABLE_STATUSES:
            handle = self.compute.start(handle)
        live = self.compute.status(handle)
        grant = self.compute.attach(live, consumer_user.strip() or "guest")

        record.status = live.status
        record.consumer_user = consumer_user.strip() or "guest"
        record.handle = _handle_to_dict(live)
        self.registry.save_instance(record)

        session = AccessSession(
            session_id=uuid.uuid4().hex[:12],
            instance_id=record.instance_id,
            fingerprint=cert.fingerprint,
            consumer_user=record.consumer_user,
            requested=requested,
            attached_at=iso(utc_now()),
            workspace=record.workspace,
            connection=grant.as_dict(),
        )
        self.registry.save_session(session)
        return {
            "session": session.as_dict(),
            "instance": record.as_dict(),
            "allocated": cert.allocated.as_dict(),
            "requested": requested.as_dict(),
            "sha_key": cert.fingerprint,
            "connection": grant.as_dict(),
        }

    def list_instances(self) -> list[InstanceRecord]:
        records = []
        for record in self.registry.list_instances():
            handle = self.compute.status(_handle_from_record(record))
            if handle.status != record.status:
                record.status = handle.status
                record.handle = _handle_to_dict(handle)
                self.registry.save_instance(record)
            records.append(record)
        return records

    def reserved_spec(self) -> ResourceSpec:
        cpu = ram = disk = 0.0
        for record in self.list_instances():
            if record.status in INACTIVE_STATUSES:
                continue
            cpu += record.spec.cpu_cores
            ram += record.spec.ram_gb
            disk += record.spec.disk_gb
        return ResourceSpec(cpu_cores=round(cpu, 2), ram_gb=round(ram, 2), disk_gb=round(disk, 2))

    def remaining_shareable(self, host: HostInventory) -> ResourceSpec:
        capacity = ResourceSpec(
            cpu_cores=float(host.logical_cores),
            ram_gb=host.ram_available_gb,
            disk_gb=host.disk_free_gb,
        )
        return capacity.remaining_after(self.reserved_spec())

    def _write_guest_system(
        self, workspace: Path, record: InstanceRecord, target_user: str, purpose: str
    ) -> dict:
        guest = {
            "role": "guest-vm",
            "hostname": record.instance_id,
            "os": "Resource Share Guest",
            "architecture": "virtual",
            "ip": "10.0.0.2",
            "vcpu": record.spec.cpu_cores,
            "memory_gb": record.spec.ram_gb,
            "disk_gb": record.spec.disk_gb,
            "cpu_usage_percent": 0.0,
            "ram_used_gb": 0.0,
            "disk_used_gb": 0.0,
            "state": record.status,
            "target_user": target_user,
            "purpose": purpose,
            "fingerprint": record.fingerprint,
            "runtime": record.backend,
        }
        path = workspace / "guest-system.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(guest, indent=2), encoding="utf-8")
        guest["path"] = str(path)
        return guest

    def _resolve_certificate(self, sha_key: str, certificate_text: str) -> ShareCertificate:
        text = certificate_text.strip()
        if text:
            cert = decode_pem(text)
            if sha_key.strip() and sha_key.strip().lower() != cert.fingerprint.lower():
                raise ValueError("The SHA key does not match the pasted certificate.")
            return cert
        key = sha_key.strip().lower()
        if not key:
            raise ValueError("Enter the SHA key, or paste the certificate.")
        cert = self.registry.find_certificate(key)
        if cert is None:
            raise ValueError(
                "No certificate found for that SHA key. Paste the PEM certificate "
                "if you received it from another machine."
            )
        return cert

    def _validate_against_host(self, allocated: ResourceSpec, host: HostInventory) -> None:
        remaining = self.remaining_shareable(host)
        reserved = self.reserved_spec()
        extra = ""
        if reserved.cpu_cores or reserved.ram_gb or reserved.disk_gb:
            extra = f" Already reserved by other VMs: {reserved.label()}."
        if allocated.cpu_cores > remaining.cpu_cores:
            raise ValueError(
                f"Cannot share {allocated.cpu_cores:g} cores; only {remaining.cpu_cores:g} remain.{extra}"
            )
        if allocated.ram_gb > remaining.ram_gb:
            raise ValueError(
                f"Cannot share {allocated.ram_gb:g} GB RAM; only {remaining.ram_gb:g} GB remain.{extra}"
            )
        if allocated.disk_gb > remaining.disk_gb:
            raise ValueError(
                f"Cannot share {allocated.disk_gb:g} GB disk; only {remaining.disk_gb:g} GB remain.{extra}"
            )


def _handle_to_dict(handle: InstanceHandle) -> dict:
    return {
        "instance_id": handle.instance_id,
        "runtime": handle.runtime,
        "backend": handle.runtime,
        "native_id": handle.native_id,
        "status": handle.status,
        "workspace": handle.workspace,
        "connection": handle.connection,
        "extra": handle.extra,
    }


def _handle_from_record(record: InstanceRecord) -> InstanceHandle:
    raw = record.handle or {}
    return InstanceHandle(
        instance_id=record.instance_id,
        runtime=str(raw.get("runtime") or raw.get("backend") or record.backend),
        native_id=raw.get("native_id", record.instance_id),
        status=record.status,
        workspace=record.workspace,
        connection=raw.get("connection") or {},
        extra=raw.get("extra") or {},
    )
