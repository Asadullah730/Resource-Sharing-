from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .base import ComputeBackend, InstanceHandle, WorkloadSpec


class DockerComputeBackend(ComputeBackend):
    """Optional adapter. Maps WorkloadSpec to a Docker container with CPU/RAM limits.

    The rest of the app never imports the Docker SDK; this backend uses the CLI.
    """

    name = "docker"

    def __init__(self, instances_root: Path):
        self.instances_root = instances_root
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        docker = shutil.which("docker")
        if not docker:
            return False, "Docker CLI was not found on PATH."
        result = subprocess.run(
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
            "-v",
            f"{disk_dir}:/data",
            "alpine:3.20",
            "sleep",
            "infinity",
        ]
        created = subprocess.run(command, capture_output=True, text=True)
        if created.returncode != 0:
            raise RuntimeError(created.stderr.strip() or "docker create failed.")
        native_id = created.stdout.strip()
        (vm_dir / "docker.json").write_text(
            json.dumps({"container_id": native_id, "name": name}, indent=2),
            encoding="utf-8",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            backend=self.name,
            native_id=native_id,
            status="created",
            workspace=str(vm_dir),
            connection={"kind": "docker", "container": name, "mount": str(disk_dir)},
            extra={"name": name},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        result = subprocess.run(
            ["docker", "start", handle.native_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "docker start failed.")
        handle.status = "running"
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        subprocess.run(
            ["docker", "stop", handle.native_id],
            capture_output=True,
            text=True,
        )
        handle.status = "stopped"
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", handle.native_id],
            capture_output=True,
            text=True,
        )
        handle.status = result.stdout.strip() if result.returncode == 0 else "missing"
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> dict:
        name = handle.extra.get("name", handle.native_id)
        return {
            "kind": "docker",
            "container": name,
            "exec": f"docker exec -it {name} sh",
            "mount": str(Path(handle.workspace) / "virtual-disk"),
            "consumer": consumer_user,
        }

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)
        subprocess.run(
            ["docker", "rm", "-f", handle.native_id],
            capture_output=True,
            text=True,
        )
