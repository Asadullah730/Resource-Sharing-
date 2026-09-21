from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .models import ResourceSpec, ShareCertificate

CERT_BEGIN = "-----BEGIN RESOURCE SHARE CERTIFICATE-----"
CERT_END = "-----END RESOURCE SHARE CERTIFICATE-----"
CERT_VERSION = "1.0"


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_or_create_issuer_secret(secret_path: Path) -> bytes:
    if secret_path.exists():
        return secret_path.read_bytes()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    secret_path.write_bytes(secret)
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return secret


def fingerprint_payload(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def sign_payload(payload: dict, secret: bytes) -> str:
    return hmac.new(secret, _canonical_json(payload), hashlib.sha256).hexdigest()


def issue_certificate(
    *,
    offer_id: str,
    instance_id: str,
    issuer_host: str,
    provider_user: str,
    target_user: str,
    purpose: str,
    allocated: ResourceSpec,
    issued_at: str,
    expires_at: str,
    secret: bytes,
    issuer_address: str = "",
) -> ShareCertificate:
    draft = ShareCertificate(
        version=CERT_VERSION,
        offer_id=offer_id,
        instance_id=instance_id,
        issuer_host=issuer_host,
        provider_user=provider_user,
        target_user=target_user,
        purpose=purpose,
        allocated=allocated,
        issued_at=issued_at,
        expires_at=expires_at,
        fingerprint="",
        signature="",
        issuer_address=issuer_address,
    )
    payload = draft.payload_for_hash()
    draft.fingerprint = fingerprint_payload(payload)
    draft.signature = sign_payload(payload, secret)
    return draft


def verify_certificate(cert: ShareCertificate, secret: bytes) -> None:
    payload = cert.payload_for_hash()
    expected_fp = fingerprint_payload(payload)
    if not hmac.compare_digest(expected_fp, cert.fingerprint):
        raise ValueError("Certificate fingerprint does not match the signed payload.")
    expected_sig = sign_payload(payload, secret)
    if not hmac.compare_digest(expected_sig, cert.signature):
        raise ValueError("Certificate signature is invalid. This SHA key was not issued here.")


def encode_pem(cert: ShareCertificate) -> str:
    raw = _canonical_json(cert.as_dict())
    b64 = base64.b64encode(raw).decode("ascii")
    wrapped = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    addr_line = f"\nIssuer Address: {cert.issuer_address}" if cert.issuer_address else ""
    return f"{CERT_BEGIN}\n{wrapped}\n{CERT_END}\nSHA-256 Fingerprint: {cert.fingerprint}{addr_line}\n"


def decode_pem(text: str) -> ShareCertificate:
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    if CERT_BEGIN not in lines or CERT_END not in lines:
        raise ValueError("Not a Resource Share certificate (missing PEM headers).")
    start = lines.index(CERT_BEGIN) + 1
    end = lines.index(CERT_END)
    body = "".join(lines[start:end])
    try:
        payload = json.loads(base64.b64decode(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Certificate body is not valid Base64 JSON.") from exc

    cert = certificate_from_dict(payload)
    # Check if Issuer Address was in trailer
    for line in lines[end + 1 :]:
        if line.lower().startswith("issuer address:"):
            addr = line.split(":", 1)[1].strip()
            if addr and not cert.issuer_address:
                cert.issuer_address = addr
    return cert


def certificate_from_dict(data: dict) -> ShareCertificate:
    allocated = data.get("allocated") or {}
    return ShareCertificate(
        version=str(data.get("version", CERT_VERSION)),
        offer_id=data["offer_id"],
        instance_id=data["instance_id"],
        issuer_host=data["issuer_host"],
        provider_user=data["provider_user"],
        target_user=data["target_user"],
        purpose=data.get("purpose", ""),
        allocated=ResourceSpec(
            cpu_cores=float(allocated["cpu_cores"]),
            ram_gb=float(allocated["ram_gb"]),
            disk_gb=float(allocated["disk_gb"]),
            gpu_count=int(allocated.get("gpu_count", 0)),
        ),
        issued_at=data["issued_at"],
        expires_at=data["expires_at"],
        fingerprint=data["fingerprint"],
        signature=data["signature"],
        issuer_address=str(data.get("issuer_address", "")),
    )
