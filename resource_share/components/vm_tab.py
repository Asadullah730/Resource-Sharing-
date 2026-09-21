from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from ..ports.compute import ERROR, MISSING, RUNNING
from .theme import CARD, CARD_ALT, ERR, MUTED, OK, WARN


class VMTabComponent(ctk.CTkFrame):
    """Component for managing and viewing created virtual machines and Kubernetes Pods."""

    def __init__(
        self,
        master,
        *,
        service,
        on_vm_deleted: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(master, fg_color=CARD, **kwargs)
        self.service = service
        self.on_vm_deleted_callback = on_vm_deleted

        self._build_ui()

    def _build_ui(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 0))

        ctk.CTkLabel(
            bar,
            text="Created Virtual Machines / Workloads",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            bar,
            text="Refresh list",
            width=120,
            command=self.refresh_vms,
        ).pack(side="right")

        self.vm_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.vm_container.pack(fill="both", expand=True, padx=8, pady=8)

        self.refresh_vms()

    def refresh_vms(self) -> None:
        for child in self.vm_container.winfo_children():
            child.destroy()

        records = self.service.list_instances()
        if not records:
            ctk.CTkLabel(
                self.vm_container,
                text="No virtual machines yet. Share resources to create one.",
                text_color=MUTED,
            ).pack(pady=24)
            return

        for record in records:
            card = ctk.CTkFrame(self.vm_container, fg_color=CARD_ALT, corner_radius=12)
            card.pack(fill="x", pady=6, padx=4)

            status_color = OK if record.status == RUNNING else (ERR if record.status in {MISSING, ERROR} else WARN)
            badge_bg = (
                "#14532d"
                if record.status == RUNNING
                else ("#7f1d1d" if record.status in {MISSING, ERROR} else "#78350f")
            )

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 4))

            ctk.CTkLabel(
                top,
                text=record.instance_id,
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(side="left")

            actions = ctk.CTkFrame(top, fg_color="transparent")
            actions.pack(side="right")

            ctk.CTkLabel(
                actions,
                text=f"  {record.status}  ",
                fg_color=badge_bg,
                text_color=status_color,
                corner_radius=8,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(0, 10))

            del_btn = ctk.CTkButton(
                actions,
                text="Delete VM",
                width=80,
                height=26,
                fg_color="#ef4444",
                hover_color="#dc2626",
                text_color="#ffffff",
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            del_btn.configure(
                command=lambda iid=record.instance_id, b=del_btn: self.delete_vm(iid, b)
            )
            del_btn.pack(side="left")

            offer = self.service.get_offer(record.offer_id)
            guest_line = f"Kubernetes Pod: {record.spec.label()}"
            if offer is not None:
                host = offer.host
                guest_line = (
                    f"Pod Spec: {record.spec.label()}\n"
                    f"Target user: {offer.target_user}  ·  Purpose: {offer.purpose or '—'}\n"
                    f"Hosted on {host.hostname} ({host.os}) — Provider: {offer.issuer_address or host.ip}"
                )
            ctk.CTkLabel(card, text=guest_line, justify="left", text_color=MUTED).pack(
                anchor="w", padx=14
            )
            ctk.CTkLabel(
                card,
                text=f"SHA  {record.fingerprint}\nWorkspace  {record.workspace}\nConsumer  {record.consumer_user or '—'}",
                justify="left",
                font=ctk.CTkFont(family="Consolas", size=12),
                text_color="#cbd5e1",
            ).pack(anchor="w", padx=14, pady=(6, 12))

    def delete_vm(self, instance_id: str, btn: ctk.CTkButton | None = None) -> None:
        if btn is not None:
            btn.configure(state="disabled", text="Deleting...")

        def _worker():
            try:
                self.service.delete_instance(instance_id)
                self.after(0, lambda iid=instance_id: self._handle_vm_deleted(iid))
            except Exception:
                self.after(0, self.refresh_vms)

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_vm_deleted(self, instance_id: str) -> None:
        self.refresh_vms()
        self.on_vm_deleted_callback(instance_id)
