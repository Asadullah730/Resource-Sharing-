from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .certificate import certificate_from_dict, encode_pem
from .models import AccessSession, InstanceRecord, ResourceSpec, ShareCertificate, ShareOffer
from .ports.registry import RegistryPort


class FileRegistry(RegistryPort):
    """File adapter for RegistryPort. Not part of the Kubernetes runtime."""

    def __init__(self, root: Path):
        self.root = root
        self.offers_dir = root / "offers"
        self.certs_dir = root / "certs"
        self.instances_dir = root / "instances"
        self.sessions_dir = root / "sessions"
        for path in (self.offers_dir, self.certs_dir, self.instances_dir, self.sessions_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_offer(self, offer: ShareOffer) -> Path:
        path = self.offers_dir / f"{offer.offer_id}.json"
        _write_json(path, offer.as_dict())
        return path

    def get_offer(self, offer_id: str) -> ShareOffer | None:
        path = self.offers_dir / f"{offer_id}.json"
        if not path.exists():
            return None
        return _offer_from_dict(_read_json(path))

    def save_certificate(self, cert: ShareCertificate) -> tuple[Path, Path]:
        json_path = self.certs_dir / f"{cert.fingerprint}.json"
        pem_path = self.certs_dir / f"{cert.fingerprint}.pem"
        _write_json(json_path, cert.as_dict())
        pem_path.write_text(encode_pem(cert), encoding="utf-8")
        return json_path, pem_path

    def get_certificate(self, fingerprint: str) -> ShareCertificate | None:
        path = self.certs_dir / f"{fingerprint.strip().lower()}.json"
        if not path.exists():
            return None
        return certificate_from_dict(_read_json(path))

    def find_certificate(self, fingerprint: str) -> ShareCertificate | None:
        wanted = fingerprint.strip().lower()
        for path in self.certs_dir.glob("*.json"):
            data = _read_json(path)
            if str(data.get("fingerprint", "")).lower() == wanted:
                return certificate_from_dict(data)
        return None

    def save_instance(self, record: InstanceRecord) -> Path:
        path = self.instances_dir / f"{record.instance_id}.json"
        _write_json(path, record.as_dict())
        return path

    def get_instance(self, instance_id: str) -> InstanceRecord | None:
        path = self.instances_dir / f"{instance_id}.json"
        if not path.exists():
            return None
        return _instance_from_dict(_read_json(path))

    def list_instances(self) -> list[InstanceRecord]:
        records = []
        for path in sorted(self.instances_dir.glob("*.json")):
            records.append(_instance_from_dict(_read_json(path)))
        return records

    def save_session(self, session: AccessSession) -> Path:
        path = self.sessions_dir / f"{session.session_id}.json"
        _write_json(path, session.as_dict())
        return path

    def get_session(self, session_id: str) -> AccessSession | None:
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = _read_json(path)
        return AccessSession(
            session_id=data["session_id"],
            instance_id=data["instance_id"],
            fingerprint=data["fingerprint"],
            consumer_user=data["consumer_user"],
            requested=ResourceSpec(**data["requested"]),
            attached_at=data["attached_at"],
            workspace=data["workspace"],
            connection=data.get("connection", {}),
        )

    def delete_instance(self, instance_id: str) -> bool:
        path = self.instances_dir / f"{instance_id}.json"
        if path.exists():
            path.unlink(missing_ok=True)
            return True
        return False

    def delete_offer(self, offer_id: str) -> bool:
        path = self.offers_dir / f"{offer_id}.json"
        if path.exists():
            path.unlink(missing_ok=True)
            return True
        return False

    def delete_certificate(self, fingerprint: str) -> bool:
        removed = False
        fp = fingerprint.strip().lower()
        for ext in (".json", ".pem"):
            path = self.certs_dir / f"{fp}{ext}"
            if path.exists():
                path.unlink(missing_ok=True)
                removed = True
        return removed

    def delete_sessions_for_instance(self, instance_id: str) -> int:
        count = 0
        for path in self.sessions_dir.glob("*.json"):
            try:
                data = _read_json(path)
                if data.get("instance_id") == instance_id:
                    path.unlink(missing_ok=True)
                    count += 1
            except Exception:
                pass
        return count


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _offer_from_dict(data: dict[str, Any]) -> ShareOffer:
    from .models import HostInventory

    allocated = data["allocated"]
    host = data["host"]
    return ShareOffer(
        offer_id=data["offer_id"],
        provider_user=data["provider_user"],
        target_user=data["target_user"],
        purpose=data.get("purpose", ""),
        allocated=ResourceSpec(**allocated),
        host=HostInventory(**host),
        created_at=data["created_at"],
        expires_at=data["expires_at"],
        fingerprint=data["fingerprint"],
        instance_id=data["instance_id"],
        backend=data["backend"],
        status=data.get("status", "offered"),
        issuer_address=data.get("issuer_address", ""),
    )


def _instance_from_dict(data: dict[str, Any]) -> InstanceRecord:
    return InstanceRecord(
        instance_id=data["instance_id"],
        offer_id=data["offer_id"],
        fingerprint=data["fingerprint"],
        backend=data["backend"],
        name=data["name"],
        spec=ResourceSpec(**data["spec"]),
        status=data["status"],
        workspace=data["workspace"],
        created_at=data["created_at"],
        handle=data.get("handle") or {},
        consumer_user=data.get("consumer_user"),
        last_error=data.get("last_error"),
    )
