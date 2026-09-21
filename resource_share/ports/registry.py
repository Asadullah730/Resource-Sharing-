from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AccessSession, InstanceRecord, ShareCertificate, ShareOffer


class RegistryPort(ABC):
    """Persistence port. Storage may be local files, a network share, or a database."""

    @abstractmethod
    def save_offer(self, offer: ShareOffer) -> Path:
        ...

    @abstractmethod
    def get_offer(self, offer_id: str) -> ShareOffer | None:
        ...

    @abstractmethod
    def save_certificate(self, cert: ShareCertificate) -> tuple[Path, Path]:
        ...

    @abstractmethod
    def get_certificate(self, fingerprint: str) -> ShareCertificate | None:
        ...

    @abstractmethod
    def find_certificate(self, fingerprint: str) -> ShareCertificate | None:
        ...

    @abstractmethod
    def save_instance(self, record: InstanceRecord) -> Path:
        ...

    @abstractmethod
    def get_instance(self, instance_id: str) -> InstanceRecord | None:
        ...

    @abstractmethod
    def list_instances(self) -> list[InstanceRecord]:
        ...

    @abstractmethod
    def save_session(self, session: AccessSession) -> Path:
        ...

    @abstractmethod
    def delete_instance(self, instance_id: str) -> bool:
        ...

    @abstractmethod
    def delete_offer(self, offer_id: str) -> bool:
        ...

    @abstractmethod
    def delete_certificate(self, fingerprint: str) -> bool:
        ...

    @abstractmethod
    def delete_sessions_for_instance(self, instance_id: str) -> int:
        ...
