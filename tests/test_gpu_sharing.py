import unittest
from pathlib import Path
import tempfile
import shutil

from resource_share.models import ResourceSpec, HostInventory
from resource_share.inventory import detect_host_gpus, collect_host_inventory
from resource_share.certificate import issue_certificate, encode_pem, decode_pem
from resource_share.service import ResourceShareService
from resource_share.compute.local import LocalComputeBackend
from resource_share.ports.compute import WorkloadSpec
from resource_share.compute.kubernetes import _POD_TEMPLATE


class TestGPUSharing(unittest.TestCase):

    def test_host_gpu_detection(self):
        name, count, vram = detect_host_gpus()
        self.assertIsInstance(name, str)
        self.assertIsInstance(count, int)
        self.assertIsInstance(vram, float)
        self.assertGreaterEqual(count, 0)
        self.assertGreaterEqual(vram, 0.0)

    def test_resource_spec_gpu(self):
        spec1 = ResourceSpec(cpu_cores=4, ram_gb=16, disk_gb=100, gpu_count=2)
        spec2 = ResourceSpec(cpu_cores=2, ram_gb=8, disk_gb=50, gpu_count=1)
        spec3 = ResourceSpec(cpu_cores=2, ram_gb=8, disk_gb=50, gpu_count=3)

        self.assertTrue(spec2.fits_inside(spec1))
        self.assertFalse(spec3.fits_inside(spec1))

        rem = spec1.remaining_after(spec2)
        self.assertEqual(rem.gpu_count, 1)
        self.assertEqual(rem.cpu_cores, 2)
        self.assertEqual(rem.ram_gb, 8)
        self.assertEqual(rem.disk_gb, 50)

        self.assertIn("1 GPU", spec2.label())

    def test_certificate_pem_roundtrip_with_gpu(self):
        allocated = ResourceSpec(cpu_cores=2, ram_gb=8, disk_gb=20, gpu_count=1)
        cert = issue_certificate(
            offer_id="off-1",
            instance_id="inst-1",
            issuer_host="hostA",
            provider_user="alice",
            target_user="Bob",
            purpose="Deep Learning",
            allocated=allocated,
            issued_at="2026-09-21T00:00:00Z",
            expires_at="2026-09-22T00:00:00Z",
            secret=b"secret-key-32-bytes-long-padding!",
            issuer_address="http://192.168.1.100:5890",
        )
        self.assertEqual(cert.allocated.gpu_count, 1)

        pem = encode_pem(cert)
        decoded = decode_pem(pem)
        self.assertEqual(decoded.target_user, "Bob")
        self.assertEqual(decoded.purpose, "Deep Learning")
        self.assertEqual(decoded.allocated.gpu_count, 1)
        self.assertEqual(decoded.allocated.cpu_cores, 2)
        self.assertEqual(decoded.allocated.ram_gb, 8)
        self.assertEqual(decoded.allocated.disk_gb, 20)

    def test_kubernetes_pod_manifest_gpu(self):
        spec_with_gpu = ResourceSpec(cpu_cores=2, ram_gb=4, disk_gb=10, gpu_count=2)
        gpu_entry = f'\n          nvidia.com/gpu: "{spec_with_gpu.gpu_count}"'
        manifest = _POD_TEMPLATE.format(
            name="test-pod",
            offer="offer-123",
            cpu="2",
            memory="4096Mi",
            disk="10Gi",
            gpu_request=gpu_entry,
            gpu_limit=gpu_entry,
        )
        self.assertIn('nvidia.com/gpu: "2"', manifest)

        # When GPU is 0
        manifest_no_gpu = _POD_TEMPLATE.format(
            name="test-pod",
            offer="offer-123",
            cpu="2",
            memory="4096Mi",
            disk="10Gi",
            gpu_request="",
            gpu_limit="",
        )
        self.assertNotIn("nvidia.com/gpu", manifest_no_gpu)

    def test_service_share_and_use_flow(self):
        from resource_share.bootstrap import build_service
        temp_dir = Path(tempfile.mkdtemp())
        try:
            service = build_service(data_root=temp_dir, runtime_name="local", start_server=False)

            # Check remaining shareable
            host = service.inventory(cpu_interval=0.0)
            # If host has GPU, we can share 1 GPU. If not, test that sharing more than remaining raises error
            if host.gpu_count > 0:
                result = service.share_resources(
                    ram_text="1 GB",
                    disk_text="2 GB",
                    cpu_text="1",
                    gpu_text="1",
                    target_user="Bob",
                    purpose="ML Test",
                )
                self.assertEqual(result["instance"]["spec"]["gpu_count"], 1)
                self.assertEqual(result["guest"]["gpu"], 1)

                # Now use resources with GPU
                use_res = service.use_resources(
                    ram_text="1 GB",
                    disk_text="2 GB",
                    cpu_text="1",
                    gpu_text="1",
                    sha_key=result["sha_key"],
                    consumer_user="Bob",
                    certificate_text=result["pem"],
                )
                self.assertEqual(use_res["requested"]["gpu_count"], 1)
            else:
                # Host has 0 GPU -> sharing 1 GPU should be rejected by _validate_against_host
                with self.assertRaises(ValueError):
                    service.share_resources(
                        ram_text="1 GB",
                        disk_text="2 GB",
                        cpu_text="1",
                        gpu_text="1",
                        target_user="Bob",
                    )
                # Sharing 0 GPU should succeed
                result = service.share_resources(
                    ram_text="1 GB",
                    disk_text="2 GB",
                    cpu_text="1",
                    gpu_text="0",
                    target_user="Bob",
                )
                self.assertEqual(result["instance"]["spec"]["gpu_count"], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
