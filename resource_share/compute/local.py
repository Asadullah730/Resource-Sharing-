from __future__ import annotations

import json
import time
from pathlib import Path

from ..ports.compute import (
    CREATED,
    MISSING,
    RUNNING,
    STOPPED,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
    coerce_status,
)


class LocalComputeBackend(ComputePort):
    """Default runtime: isolated workspace. No cluster or container engine required."""

    name = "local"

    def __init__(self, instances_root: Path):
        self.instances_root = instances_root
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        return True, "Local isolated runtime is ready."

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        vm_dir = Path(workload.workspace)
        vm_dir.mkdir(parents=True, exist_ok=True)
        disk_dir = vm_dir / "virtual-disk"
        disk_dir.mkdir(exist_ok=True)
        (disk_dir / "README.txt").write_text(
            "This folder is the consumer-facing virtual disk for the shared instance.\n"
            f"Quota: {workload.spec.disk_gb:g} GB\n",
            encoding="utf-8",
        )
        machine = {
            "kind": "local-vm",
            "name": workload.name,
            "vcpu": workload.spec.cpu_cores,
            "memory_gb": workload.spec.ram_gb,
            "disk_gb": workload.spec.disk_gb,
            "created_epoch": time.time(),
            "state": CREATED,
            "labels": workload.labels,
        }
        (vm_dir / "machine.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
        (vm_dir / "console.log").write_text(
            f"[local-runtime] created {workload.name} with {workload.spec.label()}\n",
            encoding="utf-8",
        )
        grant = AccessGrant(
            method="workspace",
            summary="Isolated workspace created",
            location=str(disk_dir),
            instructions="Use the virtual-disk folder as the shared volume for this instance.",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            runtime=self.name,
            native_id=str(vm_dir),
            status=CREATED,
            workspace=str(vm_dir),
            connection=grant.as_dict(),
            extra={"machine_file": str(vm_dir / "machine.json")},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        vm_dir = Path(handle.workspace)
        machine_path = vm_dir / "machine.json"
        if not machine_path.exists():
            handle.status = MISSING
            return handle
        machine = json.loads(machine_path.read_text(encoding="utf-8"))
        machine["state"] = RUNNING
        machine["started_epoch"] = time.time()
        machine_path.write_text(json.dumps(machine, indent=2), encoding="utf-8")
        (vm_dir / "console.log").write_text(
            (vm_dir / "console.log").read_text(encoding="utf-8")
            + f"[local-runtime] started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            encoding="utf-8",
        )
        handle.status = RUNNING
        handle.connection = AccessGrant(
            method="workspace",
            summary="Isolated workspace is running",
            location=str(vm_dir / "virtual-disk"),
            instructions="Use the virtual-disk folder as the shared volume for this instance.",
            details={"console": str(vm_dir / "console.log")},
        ).as_dict()
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        vm_dir = Path(handle.workspace)
        machine_path = vm_dir / "machine.json"
        if machine_path.exists():
            machine = json.loads(machine_path.read_text(encoding="utf-8"))
            machine["state"] = STOPPED
            machine_path.write_text(json.dumps(machine, indent=2), encoding="utf-8")
        handle.status = STOPPED
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        machine_path = Path(handle.workspace) / "machine.json"
        if not machine_path.exists():
            handle.status = MISSING
            return handle
        machine = json.loads(machine_path.read_text(encoding="utf-8"))
        handle.status = coerce_status(machine.get("state"))
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> AccessGrant:
        disk = Path(handle.workspace) / "virtual-disk"
        disk.mkdir(parents=True, exist_ok=True)
        session_note = disk / f"session-{consumer_user}.txt"
        session_note.write_text(
            f"Attached as {consumer_user}\nWorkspace: {disk}\n",
            encoding="utf-8",
        )
        return AccessGrant(
            method="workspace",
            summary=f"Attached as {consumer_user}",
            location=str(disk),
            instructions="Open the shared volume folder. This attach contract is the same for every runtime.",
            details={"console": str(Path(handle.workspace) / "console.log")},
        )

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)

    def execute(self, handle: InstanceHandle, command: str) -> str:
        import subprocess
        from .base import run_hidden

        vm_dir = Path(handle.workspace) / "virtual-disk"
        try:
            res = run_hidden(
                command,
                shell=True,
                cwd=str(vm_dir) if vm_dir.exists() else str(handle.workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = res.stdout
            if res.stderr:
                output += ("\n" if output else "") + res.stderr
            return output or f"(completed with exit code {res.returncode})"
        except subprocess.TimeoutExpired:
            return "Execution timed out after 30 seconds."
        except Exception as exc:
            return f"Execution error: {exc}"
