from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .base import ComputeBackend, InstanceHandle, WorkloadSpec

_POD_TEMPLATE = """apiVersion: v1
kind: Pod
metadata:
  name: {name}
  labels:
    app: resource-share
    offer: "{offer}"
spec:
  restartPolicy: Never
  containers:
    - name: guest
      image: alpine:3.20
      command: ["sleep", "infinity"]
      resources:
        requests:
          cpu: "{cpu}"
          memory: "{memory}"
        limits:
          cpu: "{cpu}"
          memory: "{memory}"
      volumeMounts:
        - name: shared-disk
          mountPath: /data
  volumes:
    - name: shared-disk
      emptyDir:
        sizeLimit: {disk}
"""


class KubernetesComputeBackend(ComputeBackend):
    """Optional adapter. Translates WorkloadSpec into a Pod and applies it with kubectl.

    Kubernetes is one compute target, not the application architecture. Switching
    RESOURCE_SHARE_BACKEND away from kubernetes removes all cluster coupling.
    """

    name = "kubernetes"

    def __init__(self, instances_root: Path, namespace: str = "default"):
        self.instances_root = instances_root
        self.namespace = namespace
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        if not shutil.which("kubectl"):
            return False, "kubectl was not found on PATH."
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False, "kubectl is installed but no cluster is reachable."
        return True, "Kubernetes cluster is reachable via kubectl."

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)

        vm_dir = Path(workload.workspace)
        vm_dir.mkdir(parents=True, exist_ok=True)
        name = f"rs-{workload.name}".replace("_", "-").lower()[:40]
        memory = f"{max(int(workload.spec.ram_gb * 1024), 128)}Mi"
        disk = f"{max(int(workload.spec.disk_gb), 1)}Gi"
        yaml_text = _POD_TEMPLATE.format(
            name=name,
            offer=workload.labels.get("offer_id", "none"),
            cpu=str(workload.spec.cpu_cores),
            memory=memory,
            disk=disk,
        )
        manifest = vm_dir / "pod.yaml"
        manifest.write_text(yaml_text, encoding="utf-8")
        applied = subprocess.run(
            ["kubectl", "apply", "-n", self.namespace, "-f", str(manifest)],
            capture_output=True,
            text=True,
        )
        if applied.returncode != 0:
            raise RuntimeError(applied.stderr.strip() or "kubectl apply failed.")
        (vm_dir / "kubernetes.json").write_text(
            json.dumps({"pod": name, "namespace": self.namespace}, indent=2),
            encoding="utf-8",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            backend=self.name,
            native_id=name,
            status="created",
            workspace=str(vm_dir),
            connection={
                "kind": "kubernetes",
                "pod": name,
                "namespace": self.namespace,
            },
            extra={"pod": name, "namespace": self.namespace},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        # A created Pod is already scheduled; "start" waits until Running.
        result = subprocess.run(
            [
                "kubectl",
                "wait",
                "--for=condition=Ready",
                f"pod/{handle.native_id}",
                "-n",
                handle.extra.get("namespace", self.namespace),
                "--timeout=60s",
            ],
            capture_output=True,
            text=True,
        )
        handle.status = "running" if result.returncode == 0 else "pending"
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        subprocess.run(
            [
                "kubectl",
                "delete",
                "pod",
                handle.native_id,
                "-n",
                handle.extra.get("namespace", self.namespace),
                "--ignore-not-found=true",
            ],
            capture_output=True,
            text=True,
        )
        handle.status = "stopped"
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pod",
                handle.native_id,
                "-n",
                handle.extra.get("namespace", self.namespace),
                "-o",
                "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
        )
        handle.status = result.stdout.strip() if result.returncode == 0 else "missing"
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> dict:
        ns = handle.extra.get("namespace", self.namespace)
        pod = handle.native_id
        return {
            "kind": "kubernetes",
            "pod": pod,
            "namespace": ns,
            "exec": f"kubectl exec -it -n {ns} {pod} -- sh",
            "consumer": consumer_user,
        }

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)
