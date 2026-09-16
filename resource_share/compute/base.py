"""Compatibility re-export. Adapters should import from resource_share.ports.compute."""

from ..ports.compute import AccessGrant, ComputePort, InstanceHandle, WorkloadSpec

ComputeBackend = ComputePort

__all__ = ["AccessGrant", "ComputeBackend", "ComputePort", "InstanceHandle", "WorkloadSpec"]
