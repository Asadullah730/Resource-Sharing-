from __future__ import annotations

import json
import time
from pathlib import Path

from .base import ComputeBackend, InstanceHandle, WorkloadSpec


class LocalComputeBackend(ComputeBackend):
    """Always-available backend: a virtual machine represented as an isolated
    workspace, resource envelope, and run-state file.

    This is the default so the product works on Windows without Docker or a
    cluster. Docker and Kubernetes adapters implement the same contract.
    """

    name = "local"

    def __init__(self, instances_root: Path):
        self.instances_root = instances_root
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        return True, "Local virtual-machine sandbox is ready."

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        vm_dir = Path(workload.workspace)
        vm_dir.mkdir(parents=True, exist_ok=True)
        disk_dir = vm_dir / "virtual-disk"
        disk_dir.mkdir(exist_ok=True)
        (disk_dir / "README.txt").write_text(
            "This folder is the consumer-facing virtual disk for the shared VM.\n"
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
            "state": "created",
            "labels": workload.labels,
        }
        (vm_dir / "machine.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
        (vm_dir / "console.log").write_text(
            f"[local-vm] created {workload.name} with {workload.spec.label()}\n",
            encoding="utf-8",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            backend=self.name,
            native_id=str(vm_dir),
            status="created",
            workspace=str(vm_dir),
            connection={"kind": "workspace", "path": str(disk_dir)},
            extra={"machine_file": str(vm_dir / "machine.json")},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        vm_dir = Path(handle.workspace)
        machine_path = vm_dir / "machine.json"
        machine = json.loads(machine_path.read_text(encoding="utf-8"))
        machine["state"] = "running"
        machine["started_epoch"] = time.time()
        machine_path.write_text(json.dumps(machine, indent=2), encoding="utf-8")
        (vm_dir / "console.log").write_text(
            (vm_dir / "console.log").read_text(encoding="utf-8")
            + f"[local-vm] started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            encoding="utf-8",
        )
        handle.status = "running"
        handle.connection = {
            "kind": "workspace",
            "path": str(vm_dir / "virtual-disk"),
            "console": str(vm_dir / "console.log"),
        }
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        vm_dir = Path(handle.workspace)
        machine_path = vm_dir / "machine.json"
        if machine_path.exists():
            machine = json.loads(machine_path.read_text(encoding="utf-8"))
            machine["state"] = "stopped"
            machine_path.write_text(json.dumps(machine, indent=2), encoding="utf-8")
        handle.status = "stopped"
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        machine_path = Path(handle.workspace) / "machine.json"
        if not machine_path.exists():
            handle.status = "missing"
            return handle
        machine = json.loads(machine_path.read_text(encoding="utf-8"))
        handle.status = machine.get("state", "unknown")
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> dict:
        disk = Path(handle.workspace) / "virtual-disk"
        session_note = disk / f"session-{consumer_user}.txt"
        session_note.write_text(
            f"Attached as {consumer_user}\nWorkspace: {disk}\n",
            encoding="utf-8",
        )
        return {
            "kind": "workspace",
            "path": str(disk),
            "console": str(Path(handle.workspace) / "console.log"),
            "consumer": consumer_user,
            "instructions": (
                "This VM is a local sandbox. Use the virtual-disk folder as the "
                "shared volume. Swap RESOURCE_SHARE_BACKEND to docker or kubernetes "
                "for container/cluster isolation."
            ),
        }

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)
