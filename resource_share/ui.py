from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import customtkinter as ctk

from .bootstrap import build_service
from .models import HostInventory
from .network.client import RemoteResourceClient, normalize_url
from .network.server import get_local_ip, get_tailscale_ip
from .ports.compute import ERROR, MISSING, RUNNING, AccessGrant

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BG = "#0f1720"
CARD = "#16202c"
CARD_ALT = "#1b2735"
MUTED = "#93a4b8"
TEXT = "#e8eef5"
ACCENT = "#38bdf8"
OK = "#34d399"
WARN = "#fbbf24"
ERR = "#f87171"
CPU_COLOR = "#60a5fa"
RAM_COLOR = "#34d399"
DISK_COLOR = "#fbbf24"


class MetricCard(ctk.CTkFrame):
    def __init__(self, master, title: str, bar_color: str, **kwargs):
        super().__init__(master, fg_color=CARD_ALT, corner_radius=12, **kwargs)
        self.bar_color = bar_color
        ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(12, 0))
        self.value = ctk.CTkLabel(
            self, text="—", font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT
        )
        self.value.pack(anchor="w", padx=14, pady=(2, 0))
        self.detail = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.detail.pack(anchor="w", padx=14, pady=(0, 6))
        self.bar = ctk.CTkProgressBar(self, height=8, progress_color=bar_color, fg_color="#0d141c")
        self.bar.pack(fill="x", padx=14, pady=(0, 14))
        self.bar.set(0)

    def update_metric(self, value: str, detail: str, ratio: float) -> None:
        self.value.configure(text=value)
        self.detail.configure(text=detail)
        self.bar.set(max(0.0, min(1.0, ratio)))


class ResourceShareApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Resource Sharing Manager")
        self.geometry("1120x900")
        self.minsize(860, 600)
        self.configure(fg_color=BG)

        self.service = build_service()
        self.client = RemoteResourceClient()
        self.host: HostInventory | None = None
        self._last_pem_path: str | None = None
        self._refresh_job: str | None = None

        # Remote session tracking for Consumer mode
        self._remote_url: str | None = None
        self._remote_session_id: str | None = None
        self._remote_refresh_job: str | None = None

        self.page = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.page.pack(fill="both", expand=True)

        self._build_header(self.page)
        self._build_system_dashboard(self.page)

        self.tabs = ctk.CTkTabview(
            self.page,
            fg_color=CARD,
            height=760,
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8",
            segmented_button_unselected_color="#223044",
        )
        self.tabs.pack(padx=18, pady=(0, 24), fill="both", expand=True)
        self.tabs.add("Share Resources")
        self.tabs.add("Use Resources")
        self.tabs.add("Virtual Machines")

        self._build_provider_tab(self.tabs.tab("Share Resources"))
        self._build_consumer_tab(self.tabs.tab("Use Resources"))
        self._build_vm_tab(self.tabs.tab("Virtual Machines"))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_resize, add="+")
        self.after(80, self._wire_mousewheel)
        self.after(50, lambda: self.refresh_system(initial=True))
        self.after(100, self.check_k8s)

    def _build_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))

        titles = ctk.CTkFrame(header, fg_color="transparent")
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

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")

        # Network Server status chip
        local_ip = get_local_ip()
        port = getattr(self.service.server_manager, "actual_port", 5890)
        self.server_chip = ctk.CTkLabel(
            actions,
            text=f"  IP: {local_ip}:{port}  ",
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
            command=lambda: self._copy_to_clipboard(f"{local_ip}:{port}"),
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
            command=self.check_k8s,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions,
            text="Refresh",
            width=70,
            height=28,
            fg_color="#374151",
            hover_color="#4b5563",
            command=lambda: self.refresh_system(initial=False),
        ).pack(side="left")

    def _build_system_dashboard(self, parent):
        shell = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16)
        shell.pack(fill="x", padx=18, pady=(0, 12))

        title_row = ctk.CTkFrame(shell, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            title_row,
            text="Physical Host  ·  Live System Stats",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")
        self.live_dot = ctk.CTkLabel(
            title_row, text="● live", font=ctk.CTkFont(size=12), text_color=OK
        )
        self.live_dot.pack(side="right")

        identity = ctk.CTkFrame(shell, fg_color=CARD_ALT, corner_radius=12)
        identity.pack(fill="x", padx=16, pady=(0, 10))
        self.host_name = ctk.CTkLabel(
            identity, text="Loading host…", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT
        )
        self.host_name.pack(anchor="w", padx=14, pady=(10, 0))
        self.host_meta = ctk.CTkLabel(
            identity, text="", font=ctk.CTkFont(size=12), text_color=MUTED, justify="left", wraplength=900
        )
        self.host_meta.pack(anchor="w", padx=14, pady=(2, 10))

        metrics = ctk.CTkFrame(shell, fg_color="transparent")
        metrics.pack(fill="x", padx=16, pady=(0, 14))
        metrics.grid_columnconfigure((0, 1, 2), weight=1)
        self.cpu_card = MetricCard(metrics, "HOST CPU", CPU_COLOR)
        self.ram_card = MetricCard(metrics, "HOST MEMORY", RAM_COLOR)
        self.disk_card = MetricCard(metrics, "HOST DISK", DISK_COLOR)
        self.cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.disk_card.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        self.reserved_banner = ctk.CTkLabel(
            shell,
            text="No resources reserved for VMs yet.",
            font=ctk.CTkFont(size=12),
            text_color=ACCENT,
        )
        self.reserved_banner.pack(anchor="w", padx=18, pady=(0, 12))

    def _labeled_entry(self, parent, label: str, placeholder: str, hint: str = ""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row, text=label, width=130, anchor="w", font=ctk.CTkFont(size=13), text_color=MUTED
        ).pack(side="left")
        entry = ctk.CTkEntry(
            row, placeholder_text=placeholder, height=36, fg_color="#0d141c", border_color="#334155"
        )
        entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        hint_label = ctk.CTkLabel(row, text=hint, width=150, anchor="e", text_color=ACCENT, font=ctk.CTkFont(size=12))
        hint_label.pack(side="right")
        return entry, hint_label

    def _panel(self, parent, title: str):
        frame = ctk.CTkFrame(parent, fg_color=CARD_ALT, corner_radius=12)
        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT
        ).pack(anchor="w", padx=14, pady=(12, 8))
        return frame

    def _scrollable_tab(self, parent):
        parent.configure(fg_color=CARD)
        scroller = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        scroller.pack(fill="both", expand=True, padx=4, pady=4)
        return scroller

    # ----------------------------------------------------------------------
    # Provider Tab (System A)
    # ----------------------------------------------------------------------
    def _build_provider_tab(self, parent):
        scroll = self._scrollable_tab(parent)

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

        left = self._panel(body, "Allocate Kubernetes Resources to Share")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left,
            text="Creates an isolated Kubernetes Pod on System A with exact quotas.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.entry_cpu, self.hint_cpu = self._labeled_entry(left, "CPU cores", "e.g. 2")
        self.entry_ram, self.hint_ram = self._labeled_entry(left, "RAM", "e.g. 4 GB")
        self.entry_disk, self.hint_disk = self._labeled_entry(left, "Disk", "e.g. 20 GB")
        self.entry_user, _ = self._labeled_entry(left, "Target user", "Collaborator name")
        self.entry_purpose, _ = self._labeled_entry(left, "Purpose", "Optional project name")

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

        self.provider_status = ctk.CTkLabel(
            left,
            text="Kubernetes check in progress...",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        )
        self.provider_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = self._panel(body, "Guest VM System Details")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        guest_metrics = ctk.CTkFrame(right, fg_color="transparent")
        guest_metrics.pack(fill="x", padx=10, pady=(0, 8))
        guest_metrics.grid_columnconfigure((0, 1, 2), weight=1)
        self.guest_cpu_card = MetricCard(guest_metrics, "GUEST CPU", CPU_COLOR)
        self.guest_ram_card = MetricCard(guest_metrics, "GUEST RAM", RAM_COLOR)
        self.guest_disk_card = MetricCard(guest_metrics, "GUEST DISK", DISK_COLOR)
        self.guest_cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.guest_ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.guest_disk_card.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
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
        ctk.CTkButton(sha_row, text="Copy", width=80, command=self.copy_sha_key).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            sha_row, text="Folder", width=80, fg_color="#334155", hover_color="#475569",
            command=self.open_cert_folder,
        ).pack(side="left")

        self.provider_result = ctk.CTkTextbox(
            right, height=240, fg_color="#0d141c", text_color="#dbeafe",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.provider_result.pack(fill="x", padx=14, pady=(0, 14))
        self.provider_result.insert("1.0", "SHA certificate and VM details will appear here.")
        self.provider_result.configure(state="disabled")

    # ----------------------------------------------------------------------
    # Consumer Tab (System B)
    # ----------------------------------------------------------------------
    def _build_consumer_tab(self, parent):
        scroll = self._scrollable_tab(parent)
        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = self._panel(body, "Attach to Shared Resources (System B)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left,
            text="Enter Provider Address and Certificate to attach and stream live stats.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.need_address, _ = self._labeled_entry(
            left, "Provider Address", "e.g. https://*.trycloudflare.com or 192.168.1.50:5890"
        )
        self.need_cpu, _ = self._labeled_entry(left, "CPU cores", "e.g. 1")
        self.need_ram, _ = self._labeled_entry(left, "RAM", "e.g. 2 GB")
        self.need_disk, _ = self._labeled_entry(left, "Disk", "e.g. 10 GB")
        self.need_user, _ = self._labeled_entry(left, "Your name", "Consumer name")
        self.need_sha, _ = self._labeled_entry(left, "SHA key", "Certificate fingerprint")

        ctk.CTkLabel(
            left, text="Paste PEM Certificate (auto-fills Address & SHA key):", font=ctk.CTkFont(size=12), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(8, 4))
        self.need_pem = ctk.CTkTextbox(left, height=110, fg_color="#0d141c")
        self.need_pem.pack(fill="x", padx=14, pady=(0, 8))
        self.need_pem.bind("<KeyRelease>", self._on_pem_paste)

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(4, 8))

        ctk.CTkButton(
            btn_row,
            text="Test Connection",
            fg_color="#334155",
            hover_color="#475569",
            height=38,
            width=140,
            command=self.test_remote_connection,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Use Resources",
            fg_color="#0e7490",
            hover_color="#155e75",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.use_resources,
        ).pack(side="left", fill="x", expand=True)

        self.consumer_status = ctk.CTkLabel(
            left, text="Paste certificate from System A to connect.",
            font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=360, justify="left",
        )
        self.consumer_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = self._panel(body, "System A: Real-Time Live Stats & Remote Console")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # Remote Host Live Stats Dashboard
        self.remote_badge = ctk.CTkLabel(
            right,
            text="● Disconnected (attach to System A to stream live stats)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=MUTED,
        )
        self.remote_badge.pack(anchor="w", padx=14, pady=(0, 6))

        rem_metrics = ctk.CTkFrame(right, fg_color="transparent")
        rem_metrics.pack(fill="x", padx=10, pady=(0, 8))
        rem_metrics.grid_columnconfigure((0, 1, 2), weight=1)
        self.rem_cpu_card = MetricCard(rem_metrics, "SYSTEM A CPU", CPU_COLOR)
        self.rem_ram_card = MetricCard(rem_metrics, "SYSTEM A RAM", RAM_COLOR)
        self.rem_disk_card = MetricCard(rem_metrics, "SYSTEM A DISK", DISK_COLOR)
        self.rem_cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.rem_ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.rem_disk_card.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        self.consumer_result = ctk.CTkTextbox(
            right, height=130, fg_color="#0d141c", text_color="#d1fae5",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.consumer_result.pack(fill="x", padx=14, pady=(0, 10))
        self.consumer_result.insert("1.0", "Access connection details will appear here.")
        self.consumer_result.configure(state="disabled")

        # Remote Workload Execution Box
        ctk.CTkLabel(
            right,
            text="Remote Kubernetes Console (Execute commands on System A's Pod):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=14, pady=(4, 2))

        exec_row = ctk.CTkFrame(right, fg_color="transparent")
        exec_row.pack(fill="x", padx=14, pady=(0, 6))
        self.exec_cmd_entry = ctk.CTkEntry(
            exec_row,
            placeholder_text="e.g. uname -a, python3 --version, ls -la /data",
            height=34,
            fg_color="#0d141c",
            border_color="#334155",
        )
        self.exec_cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_exec = ctk.CTkButton(
            exec_row,
            text="Run in Pod",
            width=100,
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.run_remote_command,
        )
        self.btn_exec.pack(side="left")

        self.exec_output = ctk.CTkTextbox(
            right, height=110, fg_color="#0d141c", text_color="#f1f5f9",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.exec_output.pack(fill="x", padx=14, pady=(0, 12))
        self.exec_output.insert("1.0", "Command output will appear here...")
        self.exec_output.configure(state="disabled")

    # ----------------------------------------------------------------------
    # VM Tab
    # ----------------------------------------------------------------------
    def _build_vm_tab(self, parent):
        parent.configure(fg_color=CARD)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(
            bar, text="Created Virtual Machines / Workloads", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(bar, text="Refresh list", width=120, command=self.refresh_vms).pack(side="right")
        self.vm_container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.vm_container.pack(fill="both", expand=True, padx=8, pady=8)
        self.refresh_vms()

    # ----------------------------------------------------------------------
    # Actions & Logic
    # ----------------------------------------------------------------------
    def check_k8s(self):
        backend, ok, reason = self.service.backend_status()
        is_k8s = backend.lower() == "kubernetes"
        if is_k8s and ok:
            self.backend_chip.configure(
                text="  ● KUBERNETES READY  ",
                fg_color="#14532d",
                text_color=OK,
            )
            self.btn_create_share.configure(state="normal")
            self.provider_status.configure(
                text="Kubernetes cluster is connected. Ready to share resources.", text_color=OK
            )
        else:
            self.backend_chip.configure(
                text="  ● KUBERNETES OFFLINE  ",
                fg_color="#7f1d1d",
                text_color=ERR,
            )
            self.btn_create_share.configure(state="disabled")
            msg = reason or "kubectl not reachable."
            self.provider_status.configure(
                text=f"⚠️ Kubernetes is required to share resources ({msg}). Start your cluster and click 'Check K8s'.",
                text_color=ERR,
            )

    def toggle_tunnel(self):
        tm = self.service.tunnel_manager
        if self.tunnel_var.get():
            self.tunnel_status_label.configure(
                text="Starting Cloudflare Quick Tunnel (no account required)...", text_color=ACCENT
            )
            port = getattr(self.service.server_manager, "actual_port", 5890)

            def _on_status(status: str, url: str | None):
                self.after(0, lambda: self._update_tunnel_ui(status, url))

            tm.start_tunnel(local_port=port, status_callback=_on_status)
        else:
            tm.stop_tunnel()
            self._update_tunnel_ui("offline", None)

    def _update_tunnel_ui(self, status: str, url: str | None):
        self.tunnel_url_entry.configure(state="normal")
        self.tunnel_url_entry.delete(0, "end")
        if url:
            self.tunnel_url_entry.insert(0, url)
            self.tunnel_status_label.configure(
                text=f"● Internet Tunnel Active! Share this URL or certificate across different Wi-Fi networks.",
                text_color=OK,
            )
        elif status == "offline":
            self.tunnel_status_label.configure(
                text="Tunnel Offline. System B can connect over the same Wi-Fi using your Local IP.",
                text_color=MUTED,
            )
        elif status.startswith("error"):
            self.tunnel_status_label.configure(text=f"❌ Tunnel error: {status}", text_color=ERR)
        else:
            self.tunnel_status_label.configure(text=f"Tunnel status: {status}...", text_color=ACCENT)
        self.tunnel_url_entry.configure(state="disabled")

    def copy_tunnel_url(self):
        url = self.tunnel_url_entry.get().strip()
        if url:
            self._copy_to_clipboard(url)
            self.tunnel_status_label.configure(text="Public URL copied to clipboard!", text_color=ACCENT)

    def _best_provider_address(self) -> str:
        tm = self.service.tunnel_manager
        if tm.is_active() and tm.get_url():
            return tm.get_url()
        ts_ip = get_tailscale_ip()
        port = getattr(self.service.server_manager, "actual_port", 5890)
        if ts_ip:
            return f"http://{ts_ip}:{port}"
        local_ip = get_local_ip()
        return f"http://{local_ip}:{port}"

    def create_share(self):
        # Strict Kubernetes Check
        backend, ok, reason = self.service.backend_status()
        if backend.lower() != "kubernetes" or not ok:
            self.provider_status.configure(
                text=f"❌ Cannot share: Kubernetes is required but not active ({reason}). Start your cluster first.",
                text_color=ERR,
            )
            return

        if self.host is None:
            self.provider_status.configure(text="Wait for system details to finish loading.", text_color=ERR)
            return

        best_address = self._best_provider_address()
        try:
            result = self.service.share_resources(
                ram_text=self.entry_ram.get(),
                disk_text=self.entry_disk.get(),
                cpu_text=self.entry_cpu.get(),
                target_user=self.entry_user.get(),
                purpose=self.entry_purpose.get(),
                issuer_address=best_address,
            )
        except Exception as exc:
            self.provider_status.configure(text=str(exc), text_color=ERR)
            return

        self._last_pem_path = result["pem_path"]
        self.entry_sha_key.delete(0, "end")
        self.entry_sha_key.insert(0, result["sha_key"])
        guest = result["guest"]
        allocated = result["instance"]["spec"]
        self._show_guest_cards(guest)
        target = self.entry_user.get().strip() or "Consumer"

        details = (
            f"KUBERNETES GUEST POD  [{guest['state'].upper()}]\n"
            f"  Pod Name: {guest['hostname']}\n"
            f"  Backend: Kubernetes\n"
            f"  Allocated: {allocated['cpu_cores']:g} CPU cores, {allocated['ram_gb']:g} GB RAM, {allocated['disk_gb']:g} GB Disk\n"
            f"  Provider Address: {best_address}\n"
            f"  Target User: {target}\n\n"
            f"INSTRUCTIONS FOR SYSTEM B (CONSUMER):\n"
            f"  1. Copy the certificate below (or click Copy SHA key).\n"
            f"  2. On System B, open the 'Use Resources' tab.\n"
            f"  3. Paste the certificate (it will auto-fill Address and SHA key).\n"
            f"  4. Click 'Use Resources' to connect and stream live stats in real time!\n\n"
            f"SHA-256 Fingerprint:\n{result['sha_key']}\n\n"
            f"{result['pem']}"
        )
        self._set_text(self.provider_result, details)
        self.provider_status.configure(
            text=f"Kubernetes Pod running ({allocated['cpu_cores']:g} cores, {allocated['ram_gb']:g} GB RAM). Share details ready for {target}!",
            text_color=OK,
        )
        self.refresh_vms()
        self.refresh_system(initial=False)

    def _on_pem_paste(self, event=None):
        raw = self.need_pem.get("1.0", "end").strip()
        if not raw:
            return
        # Auto-extract Issuer Address
        for line in raw.split("\n"):
            line = line.strip()
            if line.lower().startswith("issuer address:"):
                addr = line.split(":", 1)[1].strip()
                if addr:
                    self.need_address.delete(0, "end")
                    self.need_address.insert(0, addr)
            elif line.lower().startswith("sha-256 fingerprint:"):
                fp = line.split(":", 1)[1].strip()
                if fp:
                    self.need_sha.delete(0, "end")
                    self.need_sha.insert(0, fp)

    def test_remote_connection(self):
        addr = self.need_address.get().strip()
        if not addr:
            self.consumer_status.configure(text="Enter Provider Address first.", text_color=ERR)
            return

        self.consumer_status.configure(text="Testing connection to System A...", text_color=ACCENT)

        def _test():
            try:
                res = self.client.ping(addr)
                k8s_ready = res.get("kubernetes_ready", False)
                k8s_text = "Kubernetes Ready" if k8s_ready else "K8s Offline"
                msg = f"● Connected to System A ({res.get('hostname', 'Host')}, {k8s_text})"
                self.after(0, lambda: self.consumer_status.configure(text=msg, text_color=OK if k8s_ready else WARN))
            except Exception as exc:
                self.after(0, lambda: self.consumer_status.configure(text=f"❌ Connection failed: {exc}", text_color=ERR))

        threading.Thread(target=_test, daemon=True).start()

    def use_resources(self):
        addr = self.need_address.get().strip()
        sha_key = self.need_sha.get().strip()
        cert_text = self.need_pem.get("1.0", "end").strip()
        consumer_user = self.need_user.get().strip() or "consumer"

        try:
            from .inventory import parse_quantity
            cpu = parse_quantity(self.need_cpu.get() or "1")
            ram = parse_quantity(self.need_ram.get() or "1")
            disk = parse_quantity(self.need_disk.get() or "5")
        except Exception as exc:
            self.consumer_status.configure(text=f"Invalid resource quantities: {exc}", text_color=ERR)
            return

        # If a remote address is specified, attach over the network to System A
        if addr:
            self.consumer_status.configure(text="Connecting to System A and attaching...", text_color=ACCENT)

            def _remote_use():
                try:
                    result = self.client.use_resources(
                        addr,
                        sha_key=sha_key,
                        certificate_text=cert_text,
                        consumer_user=consumer_user,
                        cpu_cores=cpu,
                        ram_gb=ram,
                        disk_gb=disk,
                    )
                    self.after(0, lambda: self._on_remote_attached(addr, result))
                except Exception as exc:
                    self.after(0, lambda: self.consumer_status.configure(text=str(exc), text_color=ERR))

            threading.Thread(target=_remote_use, daemon=True).start()
        else:
            # Fallback to local
            try:
                result = self.service.use_resources(
                    ram_text=self.need_ram.get(),
                    disk_text=self.need_disk.get(),
                    cpu_text=self.need_cpu.get(),
                    sha_key=sha_key,
                    consumer_user=consumer_user,
                    certificate_text=cert_text,
                )
                self._on_local_attached(result)
            except Exception as exc:
                self.consumer_status.configure(text=str(exc), text_color=ERR)

    def _on_remote_attached(self, addr: str, result: dict):
        self._remote_url = addr
        session = result.get("session", {})
        self._remote_session_id = session.get("session_id")
        allocated = result.get("allocated", {})
        grant = AccessGrant.from_dict(result.get("connection", {}))

        self.remote_badge.configure(
            text=f"● Connected to System A ({addr})  ·  Live Streaming",
            text_color=OK,
        )
        self.consumer_status.configure(
            text="Successfully attached to System A's Kubernetes instance! Live stats active.",
            text_color=OK,
        )

        details = (
            f"ATTACHED TO REMOTE KUBERNETES POD\n"
            f"  Host: {addr}\n"
            f"  Session ID: {session.get('session_id')}\n"
            f"  Pod Name: {session.get('instance_id')}\n"
            f"  Allocated: {allocated.get('cpu_cores', '—')} CPU, {allocated.get('ram_gb', '—')} GB RAM\n\n"
            f"ACCESS:\n{grant.display_text()}"
        )
        self._set_text(self.consumer_result, details)
        self._start_remote_polling()

    def _on_local_attached(self, result: dict):
        grant = AccessGrant.from_dict(result["connection"])
        allocated = result["allocated"]
        details = (
            f"ATTACHED TO LOCAL KUBERNETES POD  [{result['instance']['status']}]\n"
            f"  VM: {result['instance']['instance_id']}\n"
            f"  Allocated: {allocated['cpu_cores']:g} vCPU, {allocated['ram_gb']:g} GB RAM\n\n"
            f"ACCESS\n{grant.display_text()}"
        )
        self._set_text(self.consumer_result, details)
        self.consumer_status.configure(text="Attached to local virtual machine.", text_color=OK)
        self.refresh_vms()

    def _start_remote_polling(self):
        if self._remote_refresh_job:
            self.after_cancel(self._remote_refresh_job)
        self._tick_remote()

    def _tick_remote(self):
        if not self._remote_url:
            return

        def _fetch():
            try:
                stats = self.client.get_stats(self._remote_url)
                self.after(0, lambda: self._update_remote_stats_ui(stats))
            except Exception:
                pass

        threading.Thread(target=_fetch, daemon=True).start()
        self._remote_refresh_job = self.after(2500, self._tick_remote)

    def _update_remote_stats_ui(self, stats: dict):
        host = stats.get("host", {})
        if not host:
            return
        cpu_usage = float(host.get("cpu_usage_percent", 0))
        ram_total = float(host.get("ram_total_gb", 1))
        ram_avail = float(host.get("ram_available_gb", 0))
        ram_used = round(max(ram_total - ram_avail, 0), 2)
        disk_total = float(host.get("disk_total_gb", 1))
        disk_free = float(host.get("disk_free_gb", 0))
        disk_used = round(max(disk_total - disk_free, 0), 2)

        self.rem_cpu_card.update_metric(
            f"{cpu_usage:.0f}%",
            f"{host.get('logical_cores', '—')} cores (System A Host)",
            cpu_usage / 100,
        )
        self.rem_ram_card.update_metric(
            f"{ram_avail:g} GB free",
            f"{ram_used:g} used / {ram_total:g} GB",
            ram_used / ram_total if ram_total else 0,
        )
        self.rem_disk_card.update_metric(
            f"{disk_free:g} GB free",
            f"{disk_used:g} used / {disk_total:g} GB",
            disk_used / disk_total if disk_total else 0,
        )

    def run_remote_command(self):
        cmd = self.exec_cmd_entry.get().strip()
        if not cmd:
            return

        if not self._remote_url or not self._remote_session_id:
            self._set_text(self.exec_output, "Attach to System A first before running commands.")
            return

        self.btn_exec.configure(state="disabled", text="Running...")
        self._set_text(self.exec_output, f"Executing on System A: '{cmd}'...")

        def _exec():
            try:
                out = self.client.execute_command(self._remote_url, self._remote_session_id, cmd)
                self.after(0, lambda: self._on_cmd_done(out))
            except Exception as exc:
                self.after(0, lambda: self._on_cmd_done(f"Error: {exc}"))

        threading.Thread(target=_exec, daemon=True).start()

    def _on_cmd_done(self, output: str):
        self._set_text(self.exec_output, output)
        self.btn_exec.configure(state="normal", text="Run in Pod")

    def refresh_system(self, initial: bool = False):
        try:
            self.host = self.service.inventory(cpu_interval=0.2 if initial else 0.0)
        except Exception as exc:
            self.live_dot.configure(text="● error", text_color=ERR)
            self.host_meta.configure(text=str(exc))
            return

        host = self.host
        reserved = self.service.reserved_spec()
        remaining = self.service.remaining_shareable(host)
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
        if reserved.cpu_cores or reserved.ram_gb or reserved.disk_gb:
            self.reserved_banner.configure(
                text=(
                    f"Reserved for VMs: {reserved.label()}    ·    "
                    f"Still shareable: {remaining.cpu_cores:g} CPU, "
                    f"{remaining.ram_gb:g} GB RAM, {remaining.disk_gb:g} GB disk"
                )
            )
        else:
            self.reserved_banner.configure(text="No resources reserved for VMs yet.")

        self.hint_cpu.configure(text=f"left {remaining.cpu_cores:g} cores")
        self.hint_ram.configure(text=f"left {remaining.ram_gb:g} GB")
        self.hint_disk.configure(text=f"left {remaining.disk_gb:g} GB")
        self.live_dot.configure(text="● live host", text_color=OK)

        if initial:
            self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(4000, self._tick)

    def _tick(self):
        self.refresh_system(initial=False)
        self._schedule_refresh()

    def refresh_vms(self):
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
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 4))
            ctk.CTkLabel(
                top, text=record.instance_id, font=ctk.CTkFont(size=15, weight="bold")
            ).pack(side="left")
            ctk.CTkLabel(
                top, text=f"  {record.status}  ", fg_color="#14532d", text_color=status_color,
                corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="right")

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

    def _reset_guest_cards(self) -> None:
        self.guest_cpu_card.update_metric("—", "Create a VM to see guest cores", 0)
        self.guest_ram_card.update_metric("—", "Create a VM to see guest RAM", 0)
        self.guest_disk_card.update_metric("—", "Create a VM to see guest disk", 0)

    def _show_guest_cards(self, guest: dict) -> None:
        vcpu = float(guest["vcpu"])
        ram = float(guest["memory_gb"])
        disk = float(guest["disk_gb"])
        self.guest_cpu_card.update_metric(
            f"{vcpu:g} vCPU", f"{guest['cpu_usage_percent']}% used inside this VM", 1.0
        )
        self.guest_ram_card.update_metric(
            f"{ram:g} GB", f"{guest['ram_used_gb']:g} GB used of guest allocation", 1.0
        )
        self.guest_disk_card.update_metric(
            f"{disk:g} GB", f"{guest['disk_used_gb']:g} GB used of guest allocation", 1.0
        )

    def copy_sha_key(self):
        key = self.entry_sha_key.get().strip()
        if not key:
            self.provider_status.configure(text="No SHA key to copy yet.", text_color=ERR)
            return
        self._copy_to_clipboard(key)
        self.provider_status.configure(text="SHA key copied to clipboard.", text_color=ACCENT)

    def open_cert_folder(self):
        folder = Path(self._last_pem_path).parent if self._last_pem_path else self.service.data_root / "certs"
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_resize(self, event):
        if event.widget is not self:
            return
        width = max(event.width - 80, 400)
        if hasattr(self, "host_meta"):
            self.host_meta.configure(wraplength=width)

    def _wire_mousewheel(self):
        canvas = getattr(self.page, "_parent_canvas", None)
        if canvas is None:
            return

        def on_wheel(event):
            try:
                if event.widget.winfo_class() == "Text":
                    return
            except Exception:
                pass
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.bind_all("<MouseWheel>", on_wheel)

    def _on_close(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        if self._remote_refresh_job:
            self.after_cancel(self._remote_refresh_job)
        try:
            self.service.tunnel_manager.stop_tunnel()
        except Exception:
            pass
        try:
            self.service.server_manager.stop()
        except Exception:
            pass
        self.unbind_all("<MouseWheel>")
        self.destroy()

    @staticmethod
    def _set_text(widget: ctk.CTkTextbox, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")


def main() -> None:
    app = ResourceShareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
