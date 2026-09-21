from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .theme import ACCENT, MUTED, OK, ERR, TEXT


class HeaderComponent(ctk.CTkFrame):
    """Header bar with application title, network server IP chip, and Kubernetes status."""

    def __init__(
        self,
        master,
        *,
        on_check_k8s: Callable[[], None],
        on_refresh_system: Callable[[], None],
        on_copy_clipboard: Callable[[str], None],
        initial_ip: str = "127.0.0.1",
        initial_port: int = 5890,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_check_k8s = on_check_k8s
        self.on_refresh_system = on_refresh_system
        self.on_copy_clipboard = on_copy_clipboard
        self._current_ip = initial_ip
        self._current_port = initial_port

        self._build_ui()

    def _build_ui(self) -> None:
        titles = ctk.CTkFrame(self, fg_color="transparent")
        titles.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            titles,
            text="Resource Sharing Manager",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w")

        ctk.CTkLabel(
            titles,
            text="Kubernetes Compute Sharing  ·  Local & Cross-Wi-Fi (Cloudflare)",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(anchor="w")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(side="right")

        # Network Server status chip
        self.server_chip = ctk.CTkLabel(
            actions,
            text=f"  IP: {self._current_ip}:{self._current_port}  ",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e293b",
            text_color=ACCENT,
            corner_radius=8,
        )
        self.server_chip.pack(side="left", padx=(0, 6), ipady=4)

        ctk.CTkButton(
            actions,
            text="Copy IP",
            width=65,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            command=self._handle_copy_ip,
        ).pack(side="left", padx=(0, 10))

        # Kubernetes Status Chip & Recheck Button
        self.backend_chip = ctk.CTkLabel(
            actions,
            text="  CHECKING KUBERNETES...  ",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            text_color=MUTED,
            corner_radius=8,
        )
        self.backend_chip.pack(side="left", padx=(0, 6), ipady=4)

        ctk.CTkButton(
            actions,
            text="Check K8s",
            width=80,
            height=28,
            fg_color="#1d4ed8",
            hover_color="#1e40af",
            command=self.on_check_k8s,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions,
            text="Refresh",
            width=70,
            height=28,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.on_refresh_system,
        ).pack(side="left")

    def _handle_copy_ip(self) -> None:
        self.on_copy_clipboard(f"{self._current_ip}:{self._current_port}")

    def update_server_info(self, ip: str, port: int) -> None:
        self._current_ip = ip
        self._current_port = port
        self.server_chip.configure(text=f"  IP: {ip}:{port}  ")

    def update_k8s_status(self, is_k8s: bool, ok: bool) -> None:
        if is_k8s and ok:
            self.backend_chip.configure(
                text="  ● KUBERNETES READY  ",
                fg_color="#14532d",
                text_color=OK,
            )
        else:
            self.backend_chip.configure(
                text="  ● KUBERNETES OFFLINE  ",
                fg_color="#7f1d1d",
                text_color=ERR,
            )
