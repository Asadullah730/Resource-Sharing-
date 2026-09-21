from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from ..models import HostInventory
from ..network.server import get_local_ip, get_tailscale_ip
from .metric_card import MetricCard
from .theme import ACCENT, CARD_ALT, CPU_COLOR, DISK_COLOR, ERR, GPU_COLOR, MUTED, OK, RAM_COLOR, TEXT
from .widgets import create_labeled_entry, create_panel, create_scrollable_tab, set_textbox_text


class ProviderTabComponent(ctk.CTkFrame):
    """Component for System A (Provider) allowing resource sharing, tunnel management, and guest VM details."""

    def __init__(
        self,
        master,
        *,
        service,
        get_host: Callable[[], HostInventory | None],
        on_share_completed: Callable[[], None],
        on_copy_clipboard: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.service = service
        self.get_host = get_host
        self.on_share_completed = on_share_completed
        self.on_copy_clipboard = on_copy_clipboard

        self._last_pem_path: str | None = None
        self._last_pem: str = ""
        self._is_sharing: bool = False
        self._share_anim_step: int = 0
        self._share_anim_job: str | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        scroll = create_scrollable_tab(self)

        # Internet Sharing (Cloudflare Quick Tunnel) Card
        tunnel_card = ctk.CTkFrame(scroll, fg_color=CARD_ALT, corner_radius=12)
        tunnel_card.pack(fill="x", padx=12, pady=(8, 10))

        t_row = ctk.CTkFrame(tunnel_card, fg_color="transparent")
        t_row.pack(fill="x", padx=14, pady=10)

        self.tunnel_var = ctk.BooleanVar(value=False)
        self.tunnel_switch = ctk.CTkSwitch(
            t_row,
            text="Enable Internet Sharing (Different Wi-Fi Networks via Cloudflare Tunnel)",
            font=ctk.CTkFont(size=13, weight="bold"),
            variable=self.tunnel_var,
            command=self.toggle_tunnel,
            progress_color="#0284c7",
        )
        self.tunnel_switch.pack(side="left")

        self.tunnel_status_label = ctk.CTkLabel(
            tunnel_card,
            text="Tunnel Offline. System B can connect over the same Wi-Fi using your Local IP.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        self.tunnel_status_label.pack(anchor="w", padx=14, pady=(0, 6))

        self.tunnel_url_row = ctk.CTkFrame(tunnel_card, fg_color="transparent")
        self.tunnel_url_row.pack(fill="x", padx=14, pady=(0, 10))
        self.tunnel_url_entry = ctk.CTkEntry(
            self.tunnel_url_row,
            placeholder_text="Public URL will appear here when enabled...",
            height=32,
            fg_color="#0d141c",
            border_color="#334155",
        )
        self.tunnel_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.tunnel_url_entry.configure(state="disabled")

        ctk.CTkButton(
            self.tunnel_url_row,
            text="Copy URL",
            width=80,
            height=32,
            command=self.copy_tunnel_url,
        ).pack(side="left")

        # Two-column layout
        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=4)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = create_panel(body, "Allocate Kubernetes Resources to Share")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left,
            text="Creates an isolated Kubernetes Pod on System A with exact quotas.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.entry_cpu, self.hint_cpu = create_labeled_entry(left, "CPU cores", "e.g. 2")
        self.entry_ram, self.hint_ram = create_labeled_entry(left, "RAM", "e.g. 4 GB")
        self.entry_disk, self.hint_disk = create_labeled_entry(left, "Disk", "e.g. 20 GB")
        self.entry_gpu, self.hint_gpu = create_labeled_entry(left, "GPU (optional)", "e.g. 0 or 1", "left 0 GPUs")
        self.entry_user, _ = create_labeled_entry(left, "Target user", "Collaborator name")
        self.entry_purpose, _ = create_labeled_entry(left, "Purpose", "Optional project name")

        self.btn_create_share = ctk.CTkButton(
            left,
            text="Create SHA Certificate + Virtual Machine",
            fg_color="#15803d",
            hover_color="#166534",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.create_share,
        )
        self.btn_create_share.pack(fill="x", padx=14, pady=(16, 8))

        # Modern indeterminate loader card (hidden by default, shown while keys & Pod are being created)
        self.share_loader_frame = ctk.CTkFrame(
            left, fg_color="#0d141c", corner_radius=8, border_width=1, border_color="#1e293b"
        )
        loader_header = ctk.CTkFrame(self.share_loader_frame, fg_color="transparent")
        loader_header.pack(fill="x", padx=12, pady=(10, 6))

        self.share_loader_spinner = ctk.CTkLabel(
            loader_header,
            text="⏳",
            font=ctk.CTkFont(size=14),
        )
        self.share_loader_spinner.pack(side="left", padx=(0, 6))

        self.share_loader_label = ctk.CTkLabel(
            loader_header,
            text="Generating SHA-256 keys & provisioning Pod...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#22c55e",
        )
        self.share_loader_label.pack(side="left")

        self.share_progress = ctk.CTkProgressBar(
            self.share_loader_frame,
            height=6,
            mode="indeterminate",
            progress_color="#22c55e",
            fg_color="#1e293b",
            indeterminate_speed=1.5,
        )
        self.share_progress.pack(fill="x", padx=12, pady=(0, 10))

        self.provider_status = ctk.CTkLabel(
            left,
            text="Kubernetes check in progress...",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        )
        self.provider_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = create_panel(body, "Guest VM System Details")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        guest_metrics = ctk.CTkFrame(right, fg_color="transparent")
        guest_metrics.pack(fill="x", padx=10, pady=(0, 8))
        guest_metrics.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.guest_cpu_card = MetricCard(guest_metrics, "GUEST CPU", CPU_COLOR)
        self.guest_ram_card = MetricCard(guest_metrics, "GUEST RAM", RAM_COLOR)
        self.guest_disk_card = MetricCard(guest_metrics, "GUEST DISK", DISK_COLOR)
        self.guest_gpu_card = MetricCard(guest_metrics, "GUEST GPU", GPU_COLOR)
        self.guest_cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.guest_ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.guest_disk_card.grid(row=0, column=2, sticky="nsew", padx=4)
        self.guest_gpu_card.grid(row=0, column=3, sticky="nsew", padx=(4, 0))
        self._reset_guest_cards()

        sha_row = ctk.CTkFrame(right, fg_color="transparent")
        sha_row.pack(fill="x", padx=14, pady=(0, 8))
        self.entry_sha_key = ctk.CTkEntry(
            sha_row,
            placeholder_text="SHA-256 key appears here after you share",
            height=36,
            fg_color="#0d141c",
            border_color="#334155",
        )
        self.entry_sha_key.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(sha_row, text="Copy Key", width=75, command=self.copy_sha_key).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            sha_row,
            text="Copy Cert",
            width=85,
            fg_color="#0e7490",
            hover_color="#155e75",
            command=self.copy_certificate,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            sha_row,
            text="Folder",
            width=70,
            fg_color="#334155",
            hover_color="#475569",
            command=self.open_cert_folder,
        ).pack(side="left")

        self.provider_result = ctk.CTkTextbox(
            right,
            height=240,
            fg_color="#0d141c",
            text_color="#dbeafe",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.provider_result.pack(fill="x", padx=14, pady=(0, 14))
        self.provider_result.insert("1.0", "SHA certificate and VM details will appear here.")
        self.provider_result.configure(state="disabled")

    # ----------------------------------------------------------------------
    # Tunnel Actions
    # ----------------------------------------------------------------------
    def toggle_tunnel(self) -> None:
        tm = self.service.tunnel_manager
        if self.tunnel_var.get():
            self.tunnel_status_label.configure(
                text="Starting Cloudflare Quick Tunnel (no account required)...", text_color=ACCENT
            )
            port = getattr(self.service.server_manager, "actual_port", 5890)

            def _on_status(status: str, url: str | None):
                self.after(0, lambda s=status, u=url: self._update_tunnel_ui(s, u))

            tm.start_tunnel(local_port=port, status_callback=_on_status)
        else:
            tm.stop_tunnel()
            self._update_tunnel_ui("offline", None)

    def _update_tunnel_ui(self, status: str, url: str | None) -> None:
        self.tunnel_url_entry.configure(state="normal")
        self.tunnel_url_entry.delete(0, "end")
        if url:
            self.tunnel_url_entry.insert(0, url)
            self.tunnel_status_label.configure(
                text="● Internet Tunnel Active! Share this URL or certificate across different Wi-Fi networks.",
                text_color=OK,
            )
        elif status == "offline":
            self.tunnel_status_label.configure(
                text="Tunnel Offline. System B can connect over the same Wi-Fi using your Local IP.",
                text_color=MUTED,
            )
        elif status.startswith("error"):
            self.tunnel_status_label.configure(text=f"❌ {status}", text_color=ERR)
            if self.tunnel_var.get():
                self.tunnel_var.set(False)
        elif "retrying" in status.lower():
            display_text = status.replace("retrying: ", "")
            self.tunnel_status_label.configure(text=f"⏳ {display_text}", text_color=WARN)
        elif status == "starting":
            self.tunnel_status_label.configure(
                text="⏳ Requesting Cloudflare Quick Tunnel (IPv4 edge)...", text_color=ACCENT
            )
        else:
            self.tunnel_status_label.configure(text=f"{status}...", text_color=ACCENT)
        self.tunnel_url_entry.configure(state="disabled")

    def copy_tunnel_url(self) -> None:
        url = self.tunnel_url_entry.get().strip()
        if url:
            self.on_copy_clipboard(url)
            self.tunnel_status_label.configure(text="Public URL copied to clipboard!", text_color=ACCENT)

    def _best_provider_address(self) -> str:
        tm = self.service.tunnel_manager
        if tm.is_active() and tm.get_url() and "api.trycloudflare.com" not in tm.get_url():
            return tm.get_url()
        ts_ip = get_tailscale_ip()
        port = getattr(self.service.server_manager, "actual_port", 5890)
        if ts_ip:
            return f"http://{ts_ip}:{port}"
        local_ip = get_local_ip()
        return f"http://{local_ip}:{port}"

    # ----------------------------------------------------------------------
    # Loader Animation & Creation Logic
    # ----------------------------------------------------------------------
    def _start_share_loader(self) -> None:
        self._is_sharing = True
        self._share_anim_step = 0
        self.btn_create_share.configure(
            state="disabled",
            text="⏳ Creating Keys & Virtual Machine...",
            fg_color="#14532d",
        )
        self.share_loader_frame.pack(fill="x", padx=14, pady=(0, 8), before=self.provider_status)
        self.share_progress.start()
        self._tick_share_loader_anim()

    def _tick_share_loader_anim(self) -> None:
        if not self._is_sharing:
            return
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.share_loader_spinner.configure(text=spinners[self._share_anim_step % len(spinners)])
        phases = [
            "Allocating Kubernetes resources...",
            "Provisioning isolated guest Pod...",
            "Generating SHA-256 cryptographic keys...",
            "Signing Resource Share Certificate...",
            "Finalizing secure share offer...",
        ]
        phase_idx = min(len(phases) - 1, self._share_anim_step // 8)
        self.share_loader_label.configure(text=phases[phase_idx])
        self._share_anim_step += 1
        self._share_anim_job = self.after(180, self._tick_share_loader_anim)

    def _stop_share_loader(self) -> None:
        self._is_sharing = False
        if self._share_anim_job:
            self.after_cancel(self._share_anim_job)
            self._share_anim_job = None
        self.share_progress.stop()
        self.share_loader_frame.pack_forget()
        self.btn_create_share.configure(
            state="normal",
            text="Create SHA Certificate + Virtual Machine",
            fg_color="#15803d",
        )
        self.entry_sha_key.configure(placeholder_text="SHA-256 key appears here after you share")

    def _on_share_success(self, result: dict, best_address: str, target: str) -> None:
        self._stop_share_loader()
        self._last_pem_path = result["pem_path"]
        self._last_pem = result["pem"]
        self.entry_sha_key.delete(0, "end")
        self.entry_sha_key.insert(0, result["sha_key"])
        guest = result["guest"]
        allocated = result["instance"]["spec"]
        self._show_guest_cards(guest)
        display_target = target or "Consumer"
        gpu_count = allocated.get("gpu_count", 0)
        gpu_desc = f", {gpu_count} GPU" if gpu_count > 0 else ""

        details = (
            f"KUBERNETES GUEST POD  [{guest['state'].upper()}]\n"
            f"  Pod Name: {guest['hostname']}\n"
            f"  Backend: Kubernetes\n"
            f"  Allocated: {allocated['cpu_cores']:g} CPU cores, {allocated['ram_gb']:g} GB RAM, {allocated['disk_gb']:g} GB Disk{gpu_desc}\n"
            f"  Provider Address: {best_address}\n"
            f"  Target User: {display_target}\n\n"
            f"INSTRUCTIONS FOR SYSTEM B (CONSUMER):\n"
            f"  1. Copy the certificate below (or click Copy SHA key).\n"
            f"  2. On System B, open the 'Use Resources' tab.\n"
            f"  3. Paste the certificate (it will auto-fill Address and SHA key).\n"
            f"  4. Click 'Use Resources' to connect and stream live stats in real time!\n\n"
            f"SHA-256 Fingerprint:\n{result['sha_key']}\n\n"
            f"{result['pem']}"
        )
        set_textbox_text(self.provider_result, details)
        self.provider_status.configure(
            text=f"Kubernetes Pod running ({allocated['cpu_cores']:g} cores, {allocated['ram_gb']:g} GB RAM{gpu_desc}). Share details ready for {display_target}!",
            text_color=OK,
        )
        self.on_share_completed()

    def _on_share_error(self, err_msg: str) -> None:
        self._stop_share_loader()
        self.entry_sha_key.delete(0, "end")
        set_textbox_text(self.provider_result, f"Error generating SHA certificate and VM:\n\n{err_msg}")
        self.provider_status.configure(text=f"❌ {err_msg}", text_color=ERR)

    def create_share(self) -> None:
        if self._is_sharing:
            return

        # Strict Kubernetes Check
        backend, ok, reason = self.service.backend_status()
        if backend.lower() != "kubernetes" or not ok:
            self.provider_status.configure(
                text=f"❌ Cannot share: Kubernetes is required but not active ({reason}). Start your cluster first.",
                text_color=ERR,
            )
            return

        host = self.get_host()
        if host is None:
            self.provider_status.configure(text="Wait for system details to finish loading.", text_color=ERR)
            return

        target_user = self.entry_user.get().strip()
        if not target_user:
            self.provider_status.configure(text="❌ Target user is required.", text_color=ERR)
            return

        best_address = self._best_provider_address()
        ram_text = self.entry_ram.get()
        disk_text = self.entry_disk.get()
        cpu_text = self.entry_cpu.get()
        gpu_text = self.entry_gpu.get().strip() or "0"
        purpose = self.entry_purpose.get()

        # Update UI to active loading state
        self._start_share_loader()
        self.entry_sha_key.delete(0, "end")
        self.entry_sha_key.configure(placeholder_text="Generating SHA-256 key... Please wait")
        set_textbox_text(
            self.provider_result,
            "⏳ Generating SHA-256 certificate and provisioning Kubernetes Pod...\n\n"
            "Please wait while the isolated guest environment and cryptographic keys are being created.",
        )
        self.provider_status.configure(
            text="Provisioning isolated Kubernetes Pod and generating SHA keys...",
            text_color=ACCENT,
        )

        def _worker():
            try:
                result = self.service.share_resources(
                    ram_text=ram_text,
                    disk_text=disk_text,
                    cpu_text=cpu_text,
                    gpu_text=gpu_text,
                    target_user=target_user,
                    purpose=purpose,
                    issuer_address=best_address,
                )
                self.after(0, lambda r=result, addr=best_address, tgt=target_user: self._on_share_success(r, addr, tgt))
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, lambda err=err_msg: self._on_share_error(err))

        threading.Thread(target=_worker, daemon=True).start()

    # ----------------------------------------------------------------------
    # Guest & Key Actions
    # ----------------------------------------------------------------------
    def _reset_guest_cards(self) -> None:
        self.guest_cpu_card.update_metric("—", "Create a VM to see guest cores", 0)
        self.guest_ram_card.update_metric("—", "Create a VM to see guest RAM", 0)
        self.guest_disk_card.update_metric("—", "Create a VM to see guest disk", 0)
        self.guest_gpu_card.update_metric("—", "Create a VM to see guest GPU", 0)

    def _show_guest_cards(self, guest: dict) -> None:
        vcpu = float(guest["vcpu"])
        ram = float(guest["memory_gb"])
        disk = float(guest["disk_gb"])
        gpu = int(guest.get("gpu", 0))
        self.guest_cpu_card.update_metric(
            f"{vcpu:g} vCPU", f"{guest['cpu_usage_percent']}% used inside this VM", 1.0
        )
        self.guest_ram_card.update_metric(
            f"{ram:g} GB", f"{guest['ram_used_gb']:g} GB used of guest allocation", 1.0
        )
        self.guest_disk_card.update_metric(
            f"{disk:g} GB", f"{guest['disk_used_gb']:g} GB used of guest allocation", 1.0
        )
        self.guest_gpu_card.update_metric(
            f"{gpu} GPU", "Allocated to guest VM" if gpu > 0 else "No GPU allocated", 1.0 if gpu > 0 else 0.0
        )

    def copy_sha_key(self) -> None:
        key = self.entry_sha_key.get().strip()
        if not key:
            self.provider_status.configure(text="No SHA key to copy yet.", text_color=ERR)
            return
        self.on_copy_clipboard(key)
        self.provider_status.configure(text="SHA key copied to clipboard.", text_color=ACCENT)

    def copy_certificate(self) -> None:
        if self._last_pem:
            self.on_copy_clipboard(self._last_pem)
            self.provider_status.configure(text="Complete PEM Certificate copied to clipboard! Paste it into System B.", text_color=OK)
        else:
            self.provider_status.configure(text="No certificate generated yet. Create a share first.", text_color=ERR)

    def open_cert_folder(self) -> None:
        folder = Path(self._last_pem_path).parent if self._last_pem_path else self.service.data_root / "certs"
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())

    def update_k8s_state(self, is_k8s: bool, ok: bool, reason: str = "") -> None:
        if is_k8s and ok:
            if not self._is_sharing:
                self.btn_create_share.configure(state="normal")
            self.provider_status.configure(
                text="Kubernetes cluster is connected. Ready to share resources.", text_color=OK
            )
        else:
            self.btn_create_share.configure(state="disabled")
            msg = reason or "kubectl not reachable."
            self.provider_status.configure(
                text=f"⚠️ Kubernetes is required to share resources ({msg}). Start your cluster and click 'Check K8s'.",
                text_color=ERR,
            )

    def update_hints(
        self,
        remaining_cpu: float,
        remaining_ram: float,
        remaining_disk: float,
        remaining_gpu: int = 0,
    ) -> None:
        self.hint_cpu.configure(text=f"left {remaining_cpu:g} cores")
        self.hint_ram.configure(text=f"left {remaining_ram:g} GB")
        self.hint_disk.configure(text=f"left {remaining_disk:g} GB")
        self.hint_gpu.configure(text=f"left {remaining_gpu} GPUs")

    def cleanup(self) -> None:
        if self._share_anim_job:
            self.after_cancel(self._share_anim_job)
            self._share_anim_job = None
        try:
            self.service.tunnel_manager.stop_tunnel()
        except Exception:
            pass
