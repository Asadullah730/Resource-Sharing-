from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = [
    ROOT / "resource_share" / "service.py",
    ROOT / "resource_share" / "models.py",
    ROOT / "resource_share" / "matching.py",
    ROOT / "resource_share" / "certificate.py",
    ROOT / "resource_share" / "inventory.py",
    ROOT / "resource_share" / "registry.py",
    ROOT / "resource_share" / "ui.py",
    ROOT / "resource_share" / "ports" / "compute.py",
    ROOT / "resource_share" / "ports" / "registry.py",
]
FORBIDDEN_IMPORTS = ("kubernetes", "docker", "kubectl")


def _imported_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


class ArchitectureTests(unittest.TestCase):
    def test_core_does_not_import_runtime_adapters(self) -> None:
        for path in CORE_MODULES:
            imported = _imported_names(path)
            for name in imported:
                lowered = name.lower()
                for forbidden in FORBIDDEN_IMPORTS:
                    self.assertNotIn(
                        forbidden,
                        lowered,
                        f"{path.name} imports {name!r}",
                    )
                self.assertFalse(
                    lowered.endswith(".compute.kubernetes")
                    or lowered.endswith(".compute.docker"),
                    f"{path.name} imports adapter {name!r}",
                )

    def test_service_import_does_not_load_kubernetes_adapter(self) -> None:
        for key in list(sys.modules):
            if key.endswith(".compute.kubernetes") or key.endswith(".compute.docker"):
                del sys.modules[key]
        import resource_share.service  # noqa: F401

        loaded = set(sys.modules)
        self.assertNotIn("resource_share.compute.kubernetes", loaded)
        self.assertNotIn("resource_share.compute.docker", loaded)

    def test_default_bootstrap_does_not_load_kubernetes(self) -> None:
        for key in list(sys.modules):
            if key.endswith(".compute.kubernetes") or key.endswith(".compute.docker"):
                del sys.modules[key]
        from resource_share.bootstrap import build_service

        with tempfile.TemporaryDirectory() as tmp:
            build_service(data_root=Path(tmp), runtime_name="local")
        loaded = set(sys.modules)
        self.assertNotIn("resource_share.compute.kubernetes", loaded)
        self.assertNotIn("resource_share.compute.docker", loaded)
        self.assertIn("resource_share.compute.local", loaded)


if __name__ == "__main__":
    unittest.main()
