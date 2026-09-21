from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..ports.compute import (
    CREATED,
    ERROR,
    MISSING,
    PENDING,
    RUNNING,
    STOPPED,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
)
from .base import run_hidden

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
      image: python:3.11-alpine
      command: ["sh", "-c", "trap : TERM INT; sleep infinity & wait"]
      resources:
        requests:
          cpu: "{cpu}"
          memory: "{memory}"
          ephemeral-storage: "{disk}"{gpu_request}
        limits:
          cpu: "{cpu}"
          memory: "{memory}"
          ephemeral-storage: "{disk}"{gpu_limit}
"""

_PHASE_STATUS = {
    "Running": RUNNING,
    "Pending": PENDING,
    "Succeeded": STOPPED,
    "Failed": ERROR,
    "Unknown": MISSING,
}


class KubernetesAdapter(ComputePort):
    """Optional adapter. Kubernetes is a compute target, not the application architecture."""

    name = "kubernetes"

    def __init__(self, instances_root: Path, namespace: str = "default"):
        self.instances_root = instances_root
        self.namespace = namespace
        self.instances_root.mkdir(parents=True, exist_ok=True)

    def available(self) -> tuple[bool, str]:
        if not shutil.which("kubectl"):
            return False, "kubectl was not found on PATH."
        result = run_hidden(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False, "kubectl is installed but no cluster is reachable."
        return True, "Kubernetes cluster is reachable via kubectl."

    def _cluster_has_nvidia_gpu(self) -> bool:
        """Check if any node in the Kubernetes cluster has allocatable nvidia.com/gpu."""
        try:
            res = run_hidden(
                ["kubectl", "get", "nodes", "-o", "jsonpath={.items[*].status.allocatable['nvidia\\.com/gpu']}"],
                capture_output=True,
                text=True,
                timeout=6,
            )
            val = res.stdout.strip()
            return bool(val and any(int(x) > 0 for x in val.split() if x.isdigit()))
        except Exception:
            return False

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)

        vm_dir = Path(workload.workspace)
        vm_dir.mkdir(parents=True, exist_ok=True)
        name = f"rs-{workload.name}".replace("_", "-").lower()[:40]
        memory = f"{max(int(workload.spec.ram_gb * 1024), 128)}Mi"
        disk = f"{max(int(workload.spec.disk_gb), 1)}Gi"
        gpu_cnt = getattr(workload.spec, "gpu_count", 0)
        gpu_entry = ""
        if gpu_cnt > 0:
            if self._cluster_has_nvidia_gpu():
                gpu_entry = f'\n          nvidia.com/gpu: "{gpu_cnt}"'
            else:
                # Node has no nvidia.com/gpu plugin (e.g. Intel Iris Xe / standard Docker Desktop).
                # Omitting nvidia.com/gpu limit prevents the Pod from getting permanently stuck in Pending.
                pass

        yaml_text = _POD_TEMPLATE.format(
            name=name,
            offer=workload.labels.get("offer_id", "none"),
            cpu=str(workload.spec.cpu_cores),
            memory=memory,
            disk=disk,
            gpu_request=gpu_entry,
            gpu_limit=gpu_entry,
        )
        manifest = vm_dir / "pod.yaml"
        manifest.write_text(yaml_text, encoding="utf-8")
        applied = run_hidden(
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
        grant = AccessGrant(
            method="workspace",
            summary="Isolated compute instance created",
            location=str(vm_dir),
            instructions="Use the shared instance location. Cluster commands stay private to this runtime.",
        )
        return InstanceHandle(
            instance_id=vm_dir.name,
            runtime=self.name,
            native_id=name,
            status=CREATED,
            workspace=str(vm_dir),
            connection=grant.as_dict(),
            extra={"pod": name, "namespace": self.namespace},
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        try:
            result = run_hidden(
                [
                    "kubectl",
                    "wait",
                    "--for=condition=Ready",
                    f"pod/{handle.native_id}",
                    "-n",
                    handle.extra.get("namespace", self.namespace),
                    "--timeout=15s",
                ],
                capture_output=True,
                text=True,
                timeout=18,
            )
            if result.returncode == 0:
                handle.status = RUNNING
            else:
                # Fast diagnostic if pod could not start
                desc = run_hidden(
                    ["kubectl", "describe", "pod", handle.native_id, "-n", handle.extra.get("namespace", self.namespace)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                diag = desc.stdout or ""
                reason = "Pod not Ready in 15s"
                if "Insufficient nvidia.com/gpu" in diag:
                    reason = "Node lacks nvidia.com/gpu resource"
                elif "FailedScheduling" in diag:
                    reason = "Failed scheduling on Kubernetes node"
                elif "ImagePullBackOff" in diag or "ErrImagePull" in diag:
                    reason = "Container image pull failed"
                handle.status = ERROR
                raise RuntimeError(f"Kubernetes Pod {handle.native_id} failed to start ({reason}).")
        except Exception as exc:
            handle.status = ERROR
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"Failed to start pod {handle.native_id}: {exc}") from exc
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        try:
            run_hidden(
                [
                    "kubectl",
                    "--request-timeout=5s",
                    "delete",
                    "pod",
                    handle.native_id,
                    "-n",
                    handle.extra.get("namespace", self.namespace),
                    "--ignore-not-found=true",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, Exception):
            pass
        handle.status = STOPPED
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        try:
            result = run_hidden(
                [
                    "kubectl",
                    "--request-timeout=5s",
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
                timeout=8,
            )
            if result.returncode != 0:
                handle.status = MISSING
                return handle
            handle.status = _PHASE_STATUS.get(result.stdout.strip(), MISSING)
            return handle
        except (subprocess.TimeoutExpired, Exception):
            handle.status = MISSING
            return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> AccessGrant:
        ns = handle.extra.get("namespace", self.namespace)
        pod = handle.native_id
        return AccessGrant(
            method="shell",
            summary=f"Attached as {consumer_user}",
            location=handle.workspace,
            instructions="Use the shared instance location. Adapter shell commands stay private to this runtime.",
            details={
                "pod": pod,
                "namespace": ns,
                "exec": f"kubectl exec -it -n {ns} {pod} -- sh",
            },
        )

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)

    def execute(self, handle: InstanceHandle, command: str) -> str:
        ns = handle.extra.get("namespace", self.namespace)
        pod = handle.native_id
        cmd = ["kubectl", "exec", "-n", ns, pod, "--", "sh", "-c", command]
        try:
            res = run_hidden(cmd, capture_output=True, text=True, timeout=120)
            stdout = res.stdout or ""
            stderr = res.stderr or ""
            output = stdout
            if stderr:
                output = f"{output}\n{stderr}" if output else stderr
            return output.strip() or f"(command completed with exit code {res.returncode})"
        except subprocess.TimeoutExpired:
            return "Execution timed out after 120 seconds."
        except Exception as exc:
            return f"Execution error: {exc}"


KubernetesComputeBackend = KubernetesAdapter
