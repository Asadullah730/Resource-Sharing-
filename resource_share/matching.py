from __future__ import annotations

from datetime import datetime, timezone

from .models import ResourceSpec, ShareCertificate, utc_now


def assert_not_expired(cert: ShareCertificate, now: datetime | None = None) -> None:
    current = now or utc_now()
    expires = datetime.fromisoformat(cert.expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if current > expires:
        raise ValueError("This SHA certificate has expired.")


def assert_resources_fit(requested: ResourceSpec, allocated: ResourceSpec) -> None:
    if not requested.fits_inside(allocated):
        raise ValueError(
            "Requested resources exceed the certificate allocation.\n"
            f"Allocated: {allocated.label()}\n"
            f"Requested: {requested.label()}"
        )
