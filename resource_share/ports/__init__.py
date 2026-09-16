"""Application ports. Core flow depends on these contracts, not on Kubernetes."""

from .compute import (
    INACTIVE_STATUSES,
    STARTABLE_STATUSES,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
)
from .registry import RegistryPort

__all__ = [
    "INACTIVE_STATUSES",
    "STARTABLE_STATUSES",
    "AccessGrant",
    "ComputePort",
    "InstanceHandle",
    "RegistryPort",
    "WorkloadSpec",
]
