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
