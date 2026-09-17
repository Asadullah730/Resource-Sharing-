from __future__ import annotations

import os
import subprocess
from typing import Any

from ..ports.compute import AccessGrant, ComputePort, InstanceHandle, WorkloadSpec

ComputeBackend = ComputePort


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Provide creationflags and startupinfo on Windows to prevent console windows from popping up."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def run_hidden(cmd: list[str] | str, **kwargs: Any) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run that suppresses console popups on Windows."""
    extra = hidden_subprocess_kwargs()
    if "creationflags" in kwargs:
        kwargs["creationflags"] |= extra.get("creationflags", 0)
    elif "creationflags" in extra:
        kwargs["creationflags"] = extra["creationflags"]

    if "startupinfo" not in kwargs and "startupinfo" in extra:
        kwargs["startupinfo"] = extra["startupinfo"]

    return subprocess.run(cmd, **kwargs)


__all__ = [
    "AccessGrant",
    "ComputeBackend",
    "ComputePort",
    "InstanceHandle",
    "WorkloadSpec",
    "hidden_subprocess_kwargs",
    "run_hidden",
]
