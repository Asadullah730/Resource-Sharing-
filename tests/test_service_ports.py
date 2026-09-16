from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resource_share.certificate import load_or_create_issuer_secret, verify_certificate
from resource_share.ports.compute import (
    CREATED,
    RUNNING,
    AccessGrant,
    ComputePort,
    InstanceHandle,
    WorkloadSpec,
)
from resource_share.registry import FileRegistry
from resource_share.service import ResourceShareService


class FakeCompute(ComputePort):
    name = "fake"

    def __init__(self) -> None:
        self.created: list[str] = []

    def available(self) -> tuple[bool, str]:
        return True, "Fake runtime is ready."

    def create_instance(self, workload: WorkloadSpec) -> InstanceHandle:
        Path(workload.workspace).mkdir(parents=True, exist_ok=True)
        self.created.append(workload.name)
        grant = AccessGrant(
            method="workspace",
            summary="Fake instance created",
            location=workload.workspace,
            instructions="Open the instance location.",
        )
        return InstanceHandle(
            instance_id=Path(workload.workspace).name,
            runtime=self.name,
            native_id=workload.name,
            status=CREATED,
            workspace=workload.workspace,
            connection=grant.as_dict(),
        )

    def start(self, handle: InstanceHandle) -> InstanceHandle:
        handle.status = RUNNING
        return handle

    def stop(self, handle: InstanceHandle) -> InstanceHandle:
        handle.status = "stopped"
        return handle

    def status(self, handle: InstanceHandle) -> InstanceHandle:
        if not Path(handle.workspace).exists():
            handle.status = "missing"
            return handle
        if handle.status in {"created", "stopped", "pending"}:
            return handle
        handle.status = RUNNING
        return handle

    def attach(self, handle: InstanceHandle, consumer_user: str) -> AccessGrant:
        return AccessGrant(
            method="workspace",
            summary=f"Attached as {consumer_user}",
            location=handle.workspace,
            instructions="Open the instance location.",
        )

    def destroy(self, handle: InstanceHandle) -> None:
        self.stop(handle)


class ServicePortTests(unittest.TestCase):
    def _service(self, root: Path) -> ResourceShareService:
        return ResourceShareService(
            data_root=root,
            registry=FileRegistry(root),
            compute=FakeCompute(),
            secret=load_or_create_issuer_secret(root / ".issuer_secret"),
        )

    def test_share_and_use_with_non_kubernetes_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service(root)
            shared = service.share_resources(
                ram_text="1 GB",
                disk_text="2 GB",
                cpu_text="1",
                target_user="bob",
            )
            self.assertEqual(shared["guest"]["os"], "Resource Share Guest")
            self.assertNotIn("kubernetes", shared["pem"].lower())
            self.assertEqual(shared["connection"]["method"], "workspace")
            cert = service.registry.get_certificate(shared["sha_key"])
            self.assertIsNotNone(cert)
            verify_certificate(cert, service.secret)
            self.assertNotIn("backend", cert.payload_for_hash())

            used = service.use_resources(
                ram_text="1 GB",
                disk_text="1 GB",
                cpu_text="1",
                sha_key=shared["sha_key"],
                consumer_user="bob",
            )
            self.assertEqual(used["connection"]["method"], "workspace")
            self.assertEqual(used["instance"]["status"], RUNNING)
            records = service.list_instances()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, RUNNING)

    def test_list_marks_missing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service(root)
            shared = service.share_resources(
                ram_text="1 GB",
                disk_text="2 GB",
                cpu_text="1",
                target_user="ada",
            )
            workspace = Path(shared["instance"]["workspace"])
            for child in workspace.glob("*"):
                if child.is_file():
                    child.unlink()
            workspace.rmdir()
            records = service.list_instances()
            self.assertEqual(records[0].status, "missing")


if __name__ == "__main__":
    unittest.main()
