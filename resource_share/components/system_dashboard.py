from __future__ import annotations

import customtkinter as ctk

from ..models import HostInventory, ResourceSpec
from .metric_card import MetricCard
from .theme import ACCENT, CARD, CARD_ALT, CPU_COLOR, DISK_COLOR, ERR, GPU_COLOR, MUTED, OK, RAM_COLOR, TEXT


class SystemDashboardComponent(ctk.CTkFrame):
    """Component displaying physical host inventory and live system resource cards."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=CARD, corner_radius=16, **kwargs)
        self._build_ui()

    def _build_ui(self) -> None:
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            title_row,
            text="Physical Host  ·  Live System Stats",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")

        self.live_dot = ctk.CTkLabel(
            title_row,
            text="● live",
            font=ctk.CTkFont(size=12),
            text_color=OK,
        )
        self.live_dot.pack(side="right")

        identity = ctk.CTkFrame(self, fg_color=CARD_ALT, corner_radius=12)
        identity.pack(fill="x", padx=16, pady=(0, 10))

        self.host_name = ctk.CTkLabel(
            identity,
            text="Loading host…",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
        )
        self.host_name.pack(anchor="w", padx=14, pady=(10, 0))

        self.host_meta = ctk.CTkLabel(
            identity,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            justify="left",
            wraplength=900,
        )
        self.host_meta.pack(anchor="w", padx=14, pady=(2, 10))

        metrics = ctk.CTkFrame(self, fg_color="transparent")
        metrics.pack(fill="x", padx=16, pady=(0, 14))
        metrics.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.cpu_card = MetricCard(metrics, "HOST CPU", CPU_COLOR)
        self.ram_card = MetricCard(metrics, "HOST MEMORY", RAM_COLOR)
        self.disk_card = MetricCard(metrics, "HOST DISK", DISK_COLOR)
        self.gpu_card = MetricCard(metrics, "HOST GPU", GPU_COLOR)

        self.cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.disk_card.grid(row=0, column=2, sticky="nsew", padx=4)
        self.gpu_card.grid(row=0, column=3, sticky="nsew", padx=(4, 0))

        self.reserved_banner = ctk.CTkLabel(
            self,
            text="No resources reserved for VMs yet.",
            font=ctk.CTkFont(size=12),
            text_color=ACCENT,
        )
        self.reserved_banner.pack(anchor="w", padx=18, pady=(0, 12))

    def update_error(self, err_text: str) -> None:
        self.live_dot.configure(text="● error", text_color=ERR)
        self.host_meta.configure(text=err_text)

    def update_host(
        self,
        host: HostInventory,
        reserved: ResourceSpec,
        remaining: ResourceSpec,
    ) -> None:
        user = host.username or "local user"
        self.host_name.configure(text=f"{host.hostname}   ·   {user}")
        self.host_meta.configure(
            text=f"OS {host.os} ({host.architecture})    IP {host.ip}\n{host.cpu_name}"
        )
        self.cpu_card.update_metric(
            f"{host.cpu_usage_percent:.0f}%",
            f"{host.physical_cores} physical  ·  {host.logical_cores} logical  ·  {reserved.cpu_cores:g} reserved",
            host.cpu_usage_percent / 100,
        )
        self.ram_card.update_metric(
            f"{host.ram_available_gb:g} GB free",
            f"{host.ram_used_gb():g} used / {host.ram_total_gb:g} GB  ·  {reserved.ram_gb:g} GB reserved",
            host.ram_percent / 100,
        )
        self.disk_card.update_metric(
            f"{host.disk_free_gb:g} GB free",
            f"{host.disk_used_gb():g} used / {host.disk_total_gb:g} GB  ·  {reserved.disk_gb:g} GB reserved",
            host.disk_percent / 100,
        )
        if host.gpu_count > 0:
            if host.gpu_vram_gb >= 1.0:
                vram_str = f" · {host.gpu_vram_gb:g} GB VRAM"
            elif host.gpu_vram_gb > 0:
                vram_str = f" · {int(round(host.gpu_vram_gb * 1024))} MB VRAM"
            else:
                vram_str = ""
            res_str = f" · {reserved.gpu_count} reserved" if reserved.gpu_count > 0 else ""
            self.gpu_card.update_metric(
                f"{host.gpu_count} Active",
                f"{host.gpu_name or 'GPU'}{vram_str}{res_str}",
                1.0,
            )
        else:
            self.gpu_card.update_metric(
                "No GPU",
                "No compatible GPU adapter found",
                0.0,
            )

        if reserved.cpu_cores or reserved.ram_gb or reserved.disk_gb or reserved.gpu_count:
            gpu_share_text = f", {remaining.gpu_count} GPU" if (host.gpu_count > 0 or reserved.gpu_count > 0) else ""
            self.reserved_banner.configure(
                text=(
                    f"Reserved for VMs: {reserved.label()}    ·    "
                    f"Still shareable: {remaining.cpu_cores:g} CPU, "
                    f"{remaining.ram_gb:g} GB RAM, {remaining.disk_gb:g} GB disk{gpu_share_text}"
                )
            )
        else:
            self.reserved_banner.configure(text="No resources reserved for VMs yet.")

        self.live_dot.configure(text="● live host", text_color=OK)

    def set_wraplength(self, width: int) -> None:
        self.host_meta.configure(wraplength=width)
