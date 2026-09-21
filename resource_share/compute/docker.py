from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..ports.compute import (
    CREATED,
    ERROR,
    MISSING,
    RUNNING,
    STOPPED,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
)
from .base import run_hidden

_DOCKER_STATUS = {
    "created": CREATED,
    "running": RUNNING,
    "paused": STOPPED,
    "restarting": RUNNING,
    "exited": STOPPED,
    "dead": ERROR,
    "removing": STOPPED,
}


class DockerComputeBackend(ComputePort):
    """Optional adapter. Maps WorkloadSpec to a container. Core never imports Docker."""

    name = "docker"

    def __init__(self, instances_root: Path):
        self.instances_root = instances_root
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        docker = shutil.which("docker")
        if not docker:
            return False, "Docker CLI was not found on PATH."
        result = run_hidden(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return False, "Docker is installed but the engine is not running."
        return True, "Docker engine is available."

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)

        vm_dir = Path(workload.workspace)
        vm_dir.mkdir(parents=True, exist_ok=True)
        disk_dir = vm_dir / "virtual-disk"
        disk_dir.mkdir(exist_ok=True)

        name = f"rs-{workload.name}".replace("_", "-")[:60]
        cpus = max(workload.spec.cpu_cores, 0.1)
        memory = f"{max(int(workload.spec.ram_gb * 1024), 128)}m"
        command = [
            "docker",
            "create",
            "--name",
            name,
            "--cpus",
            str(cpus),
            "--memory",
            memory,
        ]
        gpu_cnt = getattr(workload.spec, "gpu_count", 0)
        if gpu_cnt > 0:
            command.extend(["--gpus", f"count={gpu_cnt}"])
        command.extend([
            "-v",
            f"{disk_dir}:/data",
            "python:3.11-alpine",
            "sleep",
            "infinity",
        ])
        created = run_hidden(command, capture_output=True, text=True)
        if created.returncode != 0:
            raise RuntimeError(created.stderr.strip() or "docker create failed.")
        native_id = created.stdout.strip()
        (vm_dir / "docker.json").write_text(
            json.dumps({"container_id": native_id, "name": name}, indent=2),
            encoding="utf-8",
        )
        grant = AccessGrant(
            method="workspace",
            summary="Isolated compute instance created",
            location=str(disk_dir),
            instructions="Use the shared volume folder. Shell access is runtime-specific and stays in adapter details.",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            runtime=self.name,
            native_id=native_id,
            status=CREATED,
            workspace=str(vm_dir),
            connection=grant.as_dict(),
            extra={"name": name},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        result = run_hidden(
            ["docker", "start", handle.native_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "docker start failed.")
        handle.status = RUNNING
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        run_hidden(
            ["docker", "stop", handle.native_id],
            capture_output=True,
            text=True,
        )
        handle.status = STOPPED
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        result = run_hidden(
            ["docker", "inspect", "-f", "{{.State.Status}}", handle.native_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            handle.status = MISSING
            return handle
        handle.status = _DOCKER_STATUS.get(result.stdout.strip().lower(), ERROR)
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> AccessGrant:
        name = handle.extra.get("name", handle.native_id)
        disk = Path(handle.workspace) / "virtual-disk"
        return AccessGrant(
            method="shell",
            summary=f"Attached as {consumer_user}",
            location=str(disk),
            instructions="Use the shared volume folder. Adapter shell commands stay private to this runtime.",
            details={"container": name, "exec": f"docker exec -it {name} sh"},
        )

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)
        run_hidden(
            ["docker", "rm", "-f", handle.native_id],
            capture_output=True,
            text=True,
        )
