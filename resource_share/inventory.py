from __future__ import annotations

import getpass
import os
import platform
import socket

import psutil

from .models import HostInventory


def _primary_disk_path() -> str:
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:")
        return drive + "\\"
    return "/"


import json
import subprocess


def _detect_windows_dxgi() -> tuple[str, int, float] | None:
    """Query DirectX Graphics Infrastructure (DXGI) directly via ctypes for exact dedicated video memory."""
    try:
        import ctypes
        from ctypes import POINTER, Structure, byref, c_size_t, c_void_p, c_wchar, wintypes
        import uuid

        class DXGI_ADAPTER_DESC(Structure):
            _fields_ = [
                ("Description", c_wchar * 128),
                ("VendorId", wintypes.UINT),
                ("DeviceId", wintypes.UINT),
                ("SubSysId", wintypes.UINT),
                ("Revision", wintypes.UINT),
                ("DedicatedVideoMemory", c_size_t),
                ("DedicatedSystemMemory", c_size_t),
                ("SharedSystemMemory", c_size_t),
                ("AdapterLuid", wintypes.ULARGE_INTEGER),
            ]

        dxgi = ctypes.windll.dxgi
        IID_IDXGIFactory1 = uuid.UUID("{770aae78-f26f-4dba-a829-253c83d1b387}").bytes_le

        class GUID(Structure):
            _fields_ = [("Data", ctypes.c_byte * 16)]

        guid = GUID()
        for i, b in enumerate(IID_IDXGIFactory1):
            guid.Data[i] = b

        factory = c_void_p()
        if dxgi.CreateDXGIFactory1(byref(guid), byref(factory)) != 0:
            return None

        vtable = ctypes.cast(factory.value, POINTER(POINTER(c_void_p))).contents
        EnumAdapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, wintypes.UINT, POINTER(c_void_p))(vtable[12])
        Release = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(vtable[2])

        names: list[str] = []
        total_vram_gb = 0.0
        idx = 0
        adapter = c_void_p()

        while EnumAdapters1(factory, idx, byref(adapter)) == 0:
            avtable = ctypes.cast(adapter.value, POINTER(POINTER(c_void_p))).contents
            GetDesc = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(DXGI_ADAPTER_DESC))(avtable[8])
            aRelease = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)(avtable[2])
            desc = DXGI_ADAPTER_DESC()
            if GetDesc(adapter, byref(desc)) == 0:
                name = desc.Description.strip()
                if name and "basic render" not in name.lower() and "microsoft" not in name.lower():
                    names.append(name)
                    total_vram_gb += desc.DedicatedVideoMemory / (1024**3)
            aRelease(adapter)
            idx += 1

        Release(factory)
        if names:
            return ", ".join(names), len(names), round(total_vram_gb, 3)
        return None
    except Exception:
        return None


def detect_host_gpus() -> tuple[str, int, float]:
    """Detect GPU name, count, and approximate VRAM in GB."""
    # 1. Try nvidia-smi for dedicated NVIDIA GPUs
    nvsmi_paths = [
        "nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for p in nvsmi_paths:
        try:
            res = subprocess.run(
                [p, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
                names = []
                total_vram = 0.0
                for line in lines:
                    parts = line.split(",")
                    names.append(parts[0].strip())
                    if len(parts) > 1:
                        try:
                            total_vram += float(parts[1].strip()) / 1024.0
                        except ValueError:
                            pass
                return ", ".join(names), len(lines), round(total_vram, 2)
        except Exception:
            pass

    # 2. On Windows, query DXGI directly via ctypes for exact dedicated video memory
    if os.name == "nt":
        dxgi_result = _detect_windows_dxgi()
        if dxgi_result is not None and dxgi_result[1] > 0:
            return dxgi_result

        # Fallback to Win32_VideoController if DXGI query fails
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                valid_gpus = []
                total_vram = 0.0
                for g in data:
                    name = g.get("Name", "")
                    if name and "remote" not in name.lower() and "virtual" not in name.lower():
                        valid_gpus.append(name)
                        ram = g.get("AdapterRAM") or 0
                        if ram > 0:
                            total_vram += ram / (1024**3)
                if valid_gpus:
                    return ", ".join(valid_gpus), len(valid_gpus), round(total_vram, 3)
        except Exception:
            pass

    # 3. On Linux, check lspci / sysfs
    if os.name == "posix":
        try:
            res = subprocess.run(["lspci"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                gpus = [
                    line.split(":", 2)[-1].strip()
                    for line in res.stdout.split("\n")
                    if "vga" in line.lower() or "3d" in line.lower()
                ]
                if gpus:
                    return ", ".join(gpus), len(gpus), 0.0
        except Exception:
            pass

    return "", 0, 0.0


def collect_host_inventory(cpu_interval: float = 0.2) -> HostInventory:
    hostname = socket.gethostname()
    try:
        ip_addr = socket.gethostbyname(hostname)
    except OSError:
        ip_addr = "127.0.0.1"
    try:
        username = getpass.getuser()
    except Exception:
        username = ""

    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(_primary_disk_path())
    gpu_name, gpu_count, gpu_vram_gb = detect_host_gpus()

    return HostInventory(
        hostname=hostname,
        ip=ip_addr,
        os=f"{platform.system()} {platform.release()}",
        architecture=platform.machine(),
        cpu_name=platform.processor() or "Unknown CPU",
        physical_cores=psutil.cpu_count(logical=False) or 0,
        logical_cores=psutil.cpu_count(logical=True) or 0,
        cpu_usage_percent=round(psutil.cpu_percent(interval=cpu_interval), 1),
        ram_total_gb=round(ram.total / (1024**3), 2),
        ram_available_gb=round(ram.available / (1024**3), 2),
        disk_total_gb=round(disk.total / (1024**3), 2),
        disk_free_gb=round(disk.free / (1024**3), 2),
        username=username,
        ram_percent=round(ram.percent, 1),
        disk_percent=round(disk.percent, 1),
        gpu_name=gpu_name,
        gpu_count=gpu_count,
        gpu_vram_gb=gpu_vram_gb,
    )


def parse_quantity(text: str) -> float:
    """Parse values such as '4 GB', '2 Cores', or '8'."""
    cleaned = text.strip().lower().replace(",", "")
    if not cleaned:
        raise ValueError("Resource value is empty.")
    number = ""
    for char in cleaned:
        if char.isdigit() or char in ".-":
            number += char
        elif number:
            break
    if not number:
        raise ValueError(f"Could not parse a number from '{text}'.")
    value = float(number)
    if value <= 0:
        raise ValueError("Resource values must be greater than zero.")
    return value
