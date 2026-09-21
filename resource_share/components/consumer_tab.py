from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from ..inventory import parse_quantity
from ..network.client import RemoteResourceClient
from ..ports.compute import AccessGrant
from .metric_card import MetricCard
from .theme import ACCENT, CPU_COLOR, DISK_COLOR, ERR, GPU_COLOR, MUTED, OK, RAM_COLOR, TEXT, WARN
from .widgets import create_labeled_entry, create_panel, create_scrollable_tab, set_textbox_text


class ConsumerTabComponent(ctk.CTkFrame):
    """Component for System B (Consumer) to connect to shared resources, stream stats, and run commands."""

    def __init__(
        self,
        master,
        *,
        service,
        client: RemoteResourceClient,
        on_refresh_vms: Callable[[], None],
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.service = service
        self.client = client
        self.on_refresh_vms = on_refresh_vms

        # Remote session tracking for Consumer mode
        self._remote_url: str | None = None
        self._remote_session_id: str | None = None
        self._remote_allocated: dict | None = None
        self._remote_requested: dict | None = None
        self._remote_refresh_job: str | None = None

        # Local session tracking for Consumer mode (same PC testing)
        self._local_session_id: str | None = None
        self._local_instance_id: str | None = None
        self._local_allocated: dict | None = None
        self._local_requested: dict | None = None
        self._local_refresh_job: str | None = None

        # UI loader tracking
        self._is_using: bool = False
        self._use_anim_step: int = 0
        self._use_anim_job: str | None = None

        # Quota alert tracking
        self._quota_alert_active: bool = False
        self._quota_popup_window: ctk.CTkToplevel | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        scroll = create_scrollable_tab(self)
        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = create_panel(body, "Attach to Shared Resources (System B)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left,
            text="Enter Provider Address and Certificate to attach and stream live stats.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.need_address, _ = create_labeled_entry(
            left, "Provider Address", "e.g. https://*.trycloudflare.com or 192.168.1.50:5890"
        )
        self.need_cpu, _ = create_labeled_entry(left, "CPU cores", "e.g. 1")
        self.need_ram, _ = create_labeled_entry(left, "RAM", "e.g. 2 GB")
        self.need_disk, _ = create_labeled_entry(left, "Disk", "e.g. 10 GB")
        self.need_gpu, _ = create_labeled_entry(left, "GPU (optional)", "e.g. 0 or 1")
        self.need_user, _ = create_labeled_entry(left, "Your name", "Consumer name")
        self.need_sha, _ = create_labeled_entry(left, "SHA key", "Certificate fingerprint")

        ctk.CTkLabel(
            left, text="Paste PEM Certificate (auto-fills Address & SHA key):", font=ctk.CTkFont(size=12), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(8, 4))
        self.need_pem = ctk.CTkTextbox(left, height=110, fg_color="#0d141c")
        self.need_pem.pack(fill="x", padx=14, pady=(0, 8))
        self.need_pem.bind("<KeyRelease>", self._on_pem_paste)

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(4, 8))

        self.btn_test_conn = ctk.CTkButton(
            btn_row,
            text="Test Connection",
            fg_color="#334155",
            hover_color="#475569",
            height=38,
            width=140,
            command=self.test_remote_connection,
        )
        self.btn_test_conn.pack(side="left", padx=(0, 8))

        self.btn_use_resources = ctk.CTkButton(
            btn_row,
            text="Use Resources",
            fg_color="#0e7490",
            hover_color="#155e75",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.use_resources,
        )
        self.btn_use_resources.pack(side="left", fill="x", expand=True)

        # Modern indeterminate loader card (hidden by default, shown while attaching & negotiating with System A)
        self.use_loader_frame = ctk.CTkFrame(
            left, fg_color="#0d141c", corner_radius=8, border_width=1, border_color="#1e293b"
        )
        use_loader_header = ctk.CTkFrame(self.use_loader_frame, fg_color="transparent")
        use_loader_header.pack(fill="x", padx=12, pady=(10, 6))

        self.use_loader_spinner = ctk.CTkLabel(
            use_loader_header,
            text="⏳",
            font=ctk.CTkFont(size=14),
        )
        self.use_loader_spinner.pack(side="left", padx=(0, 6))

        self.use_loader_label = ctk.CTkLabel(
            use_loader_header,
            text="Attaching to System A...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#06b6d4",
        )
        self.use_loader_label.pack(side="left")

        self.use_progress = ctk.CTkProgressBar(
            self.use_loader_frame,
            height=6,
            mode="indeterminate",
            progress_color="#06b6d4",
            fg_color="#1e293b",
            indeterminate_speed=1.5,
        )
        self.use_progress.pack(fill="x", padx=12, pady=(0, 10))

        self.consumer_status = ctk.CTkLabel(
            left,
            text="Paste certificate from System A to connect.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        )
        self.consumer_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = create_panel(body, "System A: Real-Time Live Stats & Remote Console")
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
        rem_metrics.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.rem_cpu_card = MetricCard(rem_metrics, "SESSION CPU", CPU_COLOR)
        self.rem_ram_card = MetricCard(rem_metrics, "SESSION RAM", RAM_COLOR)
        self.rem_disk_card = MetricCard(rem_metrics, "SESSION DISK", DISK_COLOR)
        self.rem_gpu_card = MetricCard(rem_metrics, "SESSION GPU", GPU_COLOR)
        self.rem_cpu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.rem_ram_card.grid(row=0, column=1, sticky="nsew", padx=4)
        self.rem_disk_card.grid(row=0, column=2, sticky="nsew", padx=4)
        self.rem_gpu_card.grid(row=0, column=3, sticky="nsew", padx=(4, 0))

        self.rem_host_summary = ctk.CTkLabel(
            right,
            text="System A Host: Not connected",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
        )
        self.rem_host_summary.pack(fill="x", padx=14, pady=(0, 8))

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

        self.btn_clear_mem = ctk.CTkButton(
            exec_row,
            text="Clear Memory",
            width=110,
            height=34,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self.clear_memory,
        )
        self.btn_clear_mem.pack(side="left", padx=(6, 0))

        self.exec_output = ctk.CTkTextbox(
            right, height=110, fg_color="#0d141c", text_color="#f1f5f9",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.exec_output.pack(fill="x", padx=14, pady=(0, 12))
        self.exec_output.insert("1.0", "Command output will appear here...")
        self.exec_output.configure(state="disabled")

    # ----------------------------------------------------------------------
    # Event Handlers & Connection Logic
    # ----------------------------------------------------------------------
    def _on_pem_paste(self, event=None) -> None:
        raw = self.need_pem.get("1.0", "end").strip()
        if not raw:
            return

        # Attempt full certificate decode to auto-fill address, SHA key, user, and certified resource quotas
        try:
            from ..certificate import decode_pem
            cert = decode_pem(raw)
            if cert.issuer_address:
                if "api.trycloudflare.com" in cert.issuer_address.lower():
                    self.need_address.delete(0, "end")
                    self.consumer_status.configure(
                        text="⚠️ Certificate contains invalid address 'api.trycloudflare.com'. Please enter System A's Local IP (e.g. http://192.168.x.x:5890).",
                        text_color=WARN,
                    )
                else:
                    self.need_address.delete(0, "end")
                    self.need_address.insert(0, cert.issuer_address)
            if cert.fingerprint:
                self.need_sha.delete(0, "end")
                self.need_sha.insert(0, cert.fingerprint)
            if cert.target_user and not self.need_user.get().strip():
                self.need_user.delete(0, "end")
                self.need_user.insert(0, cert.target_user)
            if cert.allocated:
                if not self.need_cpu.get().strip():
                    self.need_cpu.delete(0, "end")
                    self.need_cpu.insert(0, f"{cert.allocated.cpu_cores:g}")
                if not self.need_ram.get().strip():
                    self.need_ram.delete(0, "end")
                    self.need_ram.insert(0, f"{cert.allocated.ram_gb:g} GB")
                if not self.need_disk.get().strip():
                    self.need_disk.delete(0, "end")
                    self.need_disk.insert(0, f"{cert.allocated.disk_gb:g} GB")
                if not self.need_gpu.get().strip() and cert.allocated.gpu_count > 0:
                    self.need_gpu.delete(0, "end")
                    self.need_gpu.insert(0, str(cert.allocated.gpu_count))
            return
        except Exception:
            pass

        if "-----END RESOURCE SHARE CERTIFICATE-----" in raw and "-----BEGIN RESOURCE SHARE CERTIFICATE-----" not in raw:
            self.consumer_status.configure(
                text="⚠️ Incomplete certificate pasted! Top lines (including '-----BEGIN...') were missed. Copy the FULL certificate block from System A.",
                text_color=WARN,
            )

        # Fallback line-by-line parser for partial or manual certificate pastes
        for line in raw.split("\n"):
            line = line.strip()
            if line.lower().startswith("issuer address:"):
                addr = line.split(":", 1)[1].strip()
                if addr:
                    if "api.trycloudflare.com" in addr.lower():
                        self.need_address.delete(0, "end")
                        self.consumer_status.configure(
                            text="⚠️ Certificate contains invalid address 'api.trycloudflare.com'. Please enter System A's Local IP (e.g. http://192.168.x.x:5890).",
                            text_color=WARN,
                        )
                    else:
                        self.need_address.delete(0, "end")
                        self.need_address.insert(0, addr)
            elif line.lower().startswith("sha-256 fingerprint:"):
                fp = line.split(":", 1)[1].strip()
                if fp:
                    self.need_sha.delete(0, "end")
                    self.need_sha.insert(0, fp)

    def test_remote_connection(self) -> None:
        addr = self.need_address.get().strip()
        if not addr:
            self.consumer_status.configure(text="Enter Provider Address first.", text_color=ERR)
            return

        clean_host = addr.rstrip("/").rstrip(":").replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        if clean_host and ("." not in clean_host) and (clean_host.lower() != "localhost"):
            self.consumer_status.configure(
                text=f"❌ Incomplete address '{addr}'. Enter the full URL (e.g. https://*.trycloudflare.com or http://192.168.x.x:5890).",
                text_color=ERR,
            )
            return

        if "api.trycloudflare.com" in addr.lower():
            self.consumer_status.configure(
                text="❌ 'api.trycloudflare.com' is not a valid tunnel address. Use System A's Local IP (e.g. http://192.168.x.x:5890) or an active tunnel URL.",
                text_color=ERR,
            )
            return

        self.btn_test_conn.configure(state="disabled", text="⏳ Testing...")
        self.consumer_status.configure(text="Testing connection to System A...", text_color=ACCENT)

        def _test():
            try:
                res = self.client.ping(addr)
                k8s_ready = res.get("kubernetes_ready", False)
                k8s_text = "Kubernetes Ready" if k8s_ready else "K8s Offline"
                msg = f"● Connected to System A ({res.get('hostname', 'Host')}, {k8s_text})"
                self.after(0, lambda m=msg, ok=k8s_ready: self._on_test_done(m, ok))
            except Exception as exc:
                err_msg = f"❌ Connection failed: {exc}"
                self.after(0, lambda err=err_msg: self._on_test_done(err, False))

        threading.Thread(target=_test, daemon=True).start()

    def _on_test_done(self, msg: str, ok: bool) -> None:
        self.btn_test_conn.configure(state="normal", text="Test Connection")
        self.consumer_status.configure(text=msg, text_color=OK if ok else (ERR if "failed" in msg else WARN))

    # ----------------------------------------------------------------------
    # Loader Animation & Attachment Logic
    # ----------------------------------------------------------------------
    def _start_use_loader(self) -> None:
        self._is_using = True
        self._use_anim_step = 0
        self.btn_use_resources.configure(
            state="disabled",
            text="⏳ Attaching to System A...",
            fg_color="#155e75",
        )
        self.use_loader_frame.pack(fill="x", padx=14, pady=(0, 8), before=self.consumer_status)
        self.use_progress.start()
        self._tick_use_loader_anim()

    def _tick_use_loader_anim(self) -> None:
        if not self._is_using:
            return
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.use_loader_spinner.configure(text=spinners[self._use_anim_step % len(spinners)])
        phases = [
            "Resolving Provider address & network route...",
            "Verifying SHA-256 certificate signature with System A...",
            "Negotiating allocated compute & GPU quotas...",
            "Attaching to isolated Kubernetes Pod on System A...",
            "Initializing real-time live telemetry stream...",
        ]
        phase_idx = min(len(phases) - 1, self._use_anim_step // 8)
        self.use_loader_label.configure(text=phases[phase_idx])
        self._use_anim_step += 1
        self._use_anim_job = self.after(180, self._tick_use_loader_anim)

    def _stop_use_loader(self) -> None:
        self._is_using = False
        if self._use_anim_job:
            self.after_cancel(self._use_anim_job)
            self._use_anim_job = None
        self.use_progress.stop()
        self.use_loader_frame.pack_forget()
        self.btn_use_resources.configure(
            state="normal",
            text="Use Resources",
            fg_color="#0e7490",
        )

    def _on_use_error(self, err_msg: str) -> None:
        self._stop_use_loader()
        self.consumer_status.configure(text=f"Connection error: {err_msg}", text_color=ERR)
        diag = (
            f"ATTACHMENT FAILED\n"
            f"  Error: {err_msg}\n\n"
            f"TROUBLESHOOTING:\n"
            f"  1. If using a Cloudflare tunnel URL, ensure System A's tunnel is active.\n"
            f"  2. If on the same WiFi / LAN, use System A's Local IP (e.g. http://192.168.x.x:5890).\n"
            f"  3. Check that the SHA-256 certificate pasted matches System A exactly.\n"
            f"  4. Click 'Test Connection' to verify network reachability first."
        )
        set_textbox_text(self.consumer_result, diag)

    def use_resources(self) -> None:
        if self._is_using:
            return

        addr = self.need_address.get().strip()
        sha_key = self.need_sha.get().strip()
        cert_text = self.need_pem.get("1.0", "end").strip()
        consumer_user = self.need_user.get().strip() or "consumer"

        clean_host = addr.rstrip("/").rstrip(":").replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        if clean_host and ("." not in clean_host) and (clean_host.lower() != "localhost"):
            self.consumer_status.configure(
                text=f"❌ Incomplete address '{addr}'. Enter the full URL (e.g. https://*.trycloudflare.com or http://192.168.x.x:5890).",
                text_color=ERR,
            )
            return

        if addr and "api.trycloudflare.com" in addr.lower():
            self.consumer_status.configure(
                text="❌ 'api.trycloudflare.com' is not a valid tunnel address. Use System A's Local IP (e.g. http://192.168.x.x:5890) or an active tunnel URL.",
                text_color=ERR,
            )
            return

        cpu_raw = self.need_cpu.get().strip()
        ram_raw = self.need_ram.get().strip()
        disk_raw = self.need_disk.get().strip()
        gpu_raw = self.need_gpu.get().strip()
        gpu = 0
        if gpu_raw:
            try:
                gpu = int(gpu_raw)
                if gpu < 0:
                    raise ValueError()
            except Exception:
                self.consumer_status.configure(text="❌ Invalid GPU count (must be 0 or positive integer).", text_color=ERR)
                return

        if not cpu_raw:
            self.consumer_status.configure(text="❌ CPU cores is required (e.g. 1).", text_color=ERR)
            return
        if not ram_raw:
            self.consumer_status.configure(text="❌ RAM is required (e.g. 1 GB). Pods require memory to execute commands.", text_color=ERR)
            return
        if not disk_raw:
            self.consumer_status.configure(text="❌ Disk is required (e.g. 5 GB). Pods require disk space to execute commands.", text_color=ERR)
            return

        try:
            cpu = parse_quantity(cpu_raw)
            ram = parse_quantity(ram_raw)
            disk = parse_quantity(disk_raw)
        except Exception as exc:
            self.consumer_status.configure(text=f"Invalid resource quantities: {exc}", text_color=ERR)
            return

        # Start animated loader
        self._start_use_loader()

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
                        gpu_count=gpu,
                    )
                    self.after(0, lambda a=addr, res=result: self._on_remote_attached(a, res))
                except Exception as exc:
                    err_msg = str(exc)
                    self.after(0, lambda err=err_msg: self._on_use_error(err))

            threading.Thread(target=_remote_use, daemon=True).start()
        else:
            # Fallback to local
            try:
                result = self.service.use_resources(
                    ram_text=ram_raw,
                    disk_text=disk_raw,
                    cpu_text=cpu_raw,
                    gpu_text=gpu_raw or "0",
                    sha_key=sha_key,
                    consumer_user=consumer_user,
                    certificate_text=cert_text,
                )
                self._on_local_attached(result)
            except Exception as exc:
                self._on_use_error(str(exc))

    def _on_remote_attached(self, addr: str, result: dict) -> None:
        self._stop_use_loader()
        self._remote_url = addr
        session = result.get("session", {})
        self._remote_session_id = session.get("session_id")
        allocated = result.get("allocated", {})
        requested = result.get("requested") or session.get("requested") or allocated
        self._remote_allocated = allocated
        self._remote_requested = requested
        grant = AccessGrant.from_dict(result.get("connection", {}))

        pod_name = session.get("instance_id") or "instance"
        self.remote_badge.configure(
            text=f"● Connected to System A ({addr})  ·  Pod: {pod_name}",
            text_color=OK,
        )
        self.consumer_status.configure(
            text="Successfully attached to System A's Kubernetes instance! Live stats active.",
            text_color=OK,
        )

        req_gpu = requested.get("gpu_count", 0)
        alloc_gpu = allocated.get("gpu_count", 0)
        req_gpu_str = f", {req_gpu} GPU" if req_gpu else ""
        alloc_gpu_str = f", {alloc_gpu} GPU" if alloc_gpu else ""

        details = (
            f"ATTACHED TO REMOTE KUBERNETES POD\n"
            f"  Host: {addr}\n"
            f"  Session ID: {session.get('session_id')}\n"
            f"  Pod Name: {session.get('instance_id')}\n"
            f"  Session Quota: {requested.get('cpu_cores', '—')} CPU, {requested.get('ram_gb', '—')} GB RAM, {requested.get('disk_gb', '—')} GB Disk{req_gpu_str}\n"
            f"  Host Pod Total: {allocated.get('cpu_cores', '—')} CPU, {allocated.get('ram_gb', '—')} GB RAM, {allocated.get('disk_gb', '—')} GB Disk{alloc_gpu_str}\n\n"
            f"ACCESS:\n{grant.display_text()}"
        )
        set_textbox_text(self.consumer_result, details)
        self._apply_allocated_metrics(
            requested,
            {"cpu_percent": 1.0, "ram_used_gb": 0.03, "disk_used_gb": 0.01},
            total_allocated=allocated,
        )
        self._start_remote_polling()

    def _on_local_attached(self, result: dict) -> None:
        self._stop_use_loader()
        grant = AccessGrant.from_dict(result["connection"])
        allocated = result.get("allocated", {})
        instance = result.get("instance", {})
        session = result.get("session", {})
        requested = result.get("requested") or session.get("requested") or allocated
        self._local_session_id = session.get("session_id")
        self._local_instance_id = instance.get("instance_id")
        self._local_allocated = allocated
        self._local_requested = requested

        req_gpu = requested.get("gpu_count", 0)
        alloc_gpu = allocated.get("gpu_count", 0)
        req_gpu_str = f", {req_gpu} GPU" if req_gpu else ""
        alloc_gpu_str = f", {alloc_gpu} GPU" if alloc_gpu else ""

        pod_name = instance.get("instance_id", "local-instance")
        self.remote_badge.configure(
            text=f"● Attached to Local System ({pod_name})  ·  Live Streaming",
            text_color=OK,
        )
        details = (
            f"ATTACHED TO LOCAL KUBERNETES POD  [{instance.get('status', 'running')}]\n"
            f"  VM: {instance.get('instance_id')}\n"
            f"  Session Quota: {requested.get('cpu_cores', 1):g} vCPU, {requested.get('ram_gb', 1):g} GB RAM, {requested.get('disk_gb', 1):g} GB Disk{req_gpu_str}\n"
            f"  Host Pod Total: {allocated.get('cpu_cores', 1):g} vCPU, {allocated.get('ram_gb', 1):g} GB RAM, {allocated.get('disk_gb', 1):g} GB Disk{alloc_gpu_str}\n\n"
            f"ACCESS\n{grant.display_text()}"
        )
        set_textbox_text(self.consumer_result, details)
        self.consumer_status.configure(text="Attached to virtual machine. Live stats active.", text_color=OK)
        self.on_refresh_vms()
        self._apply_allocated_metrics(
            requested,
            {"cpu_percent": 1.0, "ram_used_gb": 0.03, "disk_used_gb": 0.01},
            total_allocated=allocated,
        )
        self._start_local_polling()

    def _apply_allocated_metrics(
        self,
        requested: dict,
        usage: dict,
        host: dict | None = None,
        total_allocated: dict | None = None,
    ) -> None:
        try:
            req_cpu = float(requested.get("cpu_cores") or 1.0)
            req_ram = float(requested.get("ram_gb") or 1.0)
            req_disk = float(requested.get("disk_gb") or 1.0)

            used_cpu_pct = float(usage.get("cpu_percent") or 0.0)
            used_ram = float(usage.get("ram_used_gb") or 0.02)
            used_disk = float(usage.get("disk_used_gb") or 0.01)

            ram_free = max(round(req_ram - used_ram, 2), 0.0)
            disk_free = max(round(req_disk - used_disk, 2), 0.0)
            ram_ratio = min(max(used_ram / req_ram if req_ram else 0, 0.0), 1.0)
            disk_ratio = min(max(used_disk / req_disk if req_disk else 0, 0.0), 1.0)

            total_note = ""
            if total_allocated:
                tot_ram = total_allocated.get("ram_gb")
                if tot_ram and float(tot_ram) != req_ram:
                    total_note = f" (Pod: {float(tot_ram):g} GB)"

            self.rem_cpu_card.update_metric(
                f"{req_cpu:g} vCPU",
                f"Session quota: {req_cpu:g} core · Usage: {used_cpu_pct:.1f}%",
                used_cpu_pct / 100,
            )
            self.rem_ram_card.update_metric(
                f"{ram_free:g} GB free",
                f"{used_ram:g} GB used / {req_ram:g} GB Quota{total_note}",
                ram_ratio,
            )
            self.rem_disk_card.update_metric(
                f"{disk_free:g} GB free",
                f"{used_disk:g} GB used / {req_disk:g} GB Quota",
                disk_ratio,
            )

            # Check if RAM usage exceeded quota
            if req_ram > 0 and used_ram >= req_ram:
                if not self._quota_alert_active:
                    self._quota_alert_active = True
                    self.after(0, lambda u=used_ram, r=req_ram: self._show_quota_popup(u, r))
            elif req_ram > 0 and used_ram < (req_ram * 0.85):
                self._quota_alert_active = False

            req_gpu = int(requested.get("gpu_count") or 0)
            if req_gpu > 0:
                self.rem_gpu_card.update_metric(
                    f"{req_gpu} GPU",
                    "Session quota: Active",
                    1.0,
                )
            else:
                self.rem_gpu_card.update_metric(
                    "0 GPU",
                    "No GPU assigned to session",
                    0.0,
                )

            if host:
                h_cpu = float(host.get("cpu_usage_percent", 0))
                h_ram_free = float(host.get("ram_available_gb", 0))
                h_ram_tot = float(host.get("ram_total_gb", 1))
                h_disk_free = float(host.get("disk_free_gb", 0))
                h_name = host.get("hostname", "System A")
                h_gpu = host.get("gpu_name") or ""
                h_gpu_cnt = int(host.get("gpu_count", 0))
                gpu_info = f"  ·  GPU: {h_gpu} ({h_gpu_cnt})" if h_gpu_cnt > 0 else ""
                self.rem_host_summary.configure(
                    text=f"System A Host Health: {h_name}  ·  CPU: {h_cpu:.0f}%  ·  RAM: {h_ram_free:g} GB free / {h_ram_tot:g} GB  ·  Disk: {h_disk_free:g} GB free{gpu_info}"
                )
        except Exception:
            pass

    def _start_local_polling(self) -> None:
        if self._local_refresh_job:
            self.after_cancel(self._local_refresh_job)
        self._tick_local()

    def _tick_local(self) -> None:
        if not self._local_instance_id:
            return

        def _fetch():
            try:
                usage = self.service.get_instance_usage(self._local_instance_id)
                inv = self.service.inventory(cpu_interval=0.0)
                host_dict = inv.as_dict()
                alloc = self._local_allocated or {}
                req = self._local_requested or alloc
                self.after(0, lambda r=req, u=usage, h=host_dict, a=alloc: self._apply_allocated_metrics(r, u, h, total_allocated=a))
            except Exception:
                pass

        threading.Thread(target=_fetch, daemon=True).start()
        self._local_refresh_job = self.after(2500, self._tick_local)

    def _start_remote_polling(self) -> None:
        if self._remote_refresh_job:
            self.after_cancel(self._remote_refresh_job)
        self._tick_remote()

    def _tick_remote(self) -> None:
        if not self._remote_url:
            return

        def _fetch():
            try:
                if self._remote_session_id:
                    stats = self.client.get_session_stats(self._remote_url, self._remote_session_id)
                else:
                    stats = self.client.get_stats(self._remote_url)
                self.after(0, lambda s=stats: self._update_remote_stats_ui(s))
            except Exception:
                pass

        threading.Thread(target=_fetch, daemon=True).start()
        self._remote_refresh_job = self.after(2500, self._tick_remote)

    def _update_remote_stats_ui(self, stats: dict) -> None:
        host = stats.get("host", {})
        allocated = stats.get("allocated") or self._remote_allocated or {}
        requested = stats.get("requested") or self._remote_requested or allocated
        usage = stats.get("usage") or {"cpu_percent": 1.0, "ram_used_gb": 0.03, "disk_used_gb": 0.01}
        self._apply_allocated_metrics(requested, usage, host, total_allocated=allocated)

    def run_remote_command(self) -> None:
        cmd = self.exec_cmd_entry.get().strip()
        if not cmd:
            return

        if not self._remote_url or not self._remote_session_id:
            if self._local_session_id:
                self.btn_exec.configure(state="disabled", text="Running...")
                set_textbox_text(self.exec_output, f"Executing on local Pod: '{cmd}'...")

                def _exec_local():
                    try:
                        out = self.service.execute_in_session(self._local_session_id, cmd)
                        self.after(0, lambda res=out: self._on_cmd_done(res))
                    except Exception as exc:
                        err_msg = f"Error: {exc}"
                        self.after(0, lambda err=err_msg: self._on_cmd_done(err))

                threading.Thread(target=_exec_local, daemon=True).start()
                return

            set_textbox_text(self.exec_output, "Attach to System A first before running commands.")
            return

        self.btn_exec.configure(state="disabled", text="Running...")
        set_textbox_text(self.exec_output, f"Executing on System A: '{cmd}'...")

        def _exec():
            try:
                out = self.client.execute_command(self._remote_url, self._remote_session_id, cmd)
                self.after(0, lambda res=out: self._on_cmd_done(res))
            except Exception as exc:
                err_msg = f"Error: {exc}"
                self.after(0, lambda err=err_msg: self._on_cmd_done(err))

        threading.Thread(target=_exec, daemon=True).start()

    def _on_cmd_done(self, output: str) -> None:
        set_textbox_text(self.exec_output, output)
        self.btn_exec.configure(state="normal", text="Run in Pod")

    def clear_memory(self) -> None:
        cmd = "killall -9 python3 python stress 2>/dev/null; sync; echo 'Memory cleared. Workload processes stopped.'"

        if not self._remote_url or not self._remote_session_id:
            if self._local_session_id:
                set_textbox_text(self.exec_output, "Clearing memory on local Pod...")

                def _clear_local():
                    try:
                        out = self.service.execute_in_session(self._local_session_id, cmd)
                        self.after(0, lambda res=out: self._on_memory_cleared(res))
                    except Exception as exc:
                        self.after(0, lambda err=str(exc): self._on_memory_cleared(f"Error clearing memory: {err}"))

                threading.Thread(target=_clear_local, daemon=True).start()
                return

            set_textbox_text(self.exec_output, "Attach to System A first before clearing memory.")
            return

        set_textbox_text(self.exec_output, "Clearing memory on System A's Pod...")

        def _clear_remote():
            try:
                out = self.client.execute_command(self._remote_url, self._remote_session_id, cmd)
                self.after(0, lambda res=out: self._on_memory_cleared(res))
            except Exception as exc:
                self.after(0, lambda err=str(exc): self._on_memory_cleared(f"Error clearing memory: {err}"))

        threading.Thread(target=_clear_remote, daemon=True).start()

    def _on_memory_cleared(self, output: str) -> None:
        set_textbox_text(self.exec_output, output)
        self._quota_alert_active = False
        if self._quota_popup_window:
            try:
                self._quota_popup_window.destroy()
            except Exception:
                pass
            self._quota_popup_window = None

        # Instantly refresh stats
        if self._remote_url:
            threading.Thread(target=self._tick_remote, daemon=True).start()
        elif self._local_instance_id:
            threading.Thread(target=self._tick_local, daemon=True).start()

    def _show_quota_popup(self, used_ram: float, req_ram: float) -> None:
        if self._quota_popup_window is not None:
            try:
                if self._quota_popup_window.winfo_exists():
                    self._quota_popup_window.lift()
                    self._quota_popup_window.focus_force()
                    return
            except Exception:
                self._quota_popup_window = None

        top = ctk.CTkToplevel(self)
        self._quota_popup_window = top
        top.title("Resource Quota Alert")
        top.geometry("490x270")
        top.resizable(False, False)
        top.configure(fg_color="#0f1720")
        top.attributes("-topmost", True)

        try:
            top.update_idletasks()
            rx = self.winfo_rootx() + (self.winfo_width() // 2) - 245
            ry = self.winfo_rooty() + (self.winfo_height() // 2) - 135
            top.geometry(f"+{max(rx, 50)}+{max(ry, 50)}")
        except Exception:
            pass

        card = ctk.CTkFrame(top, fg_color="#16202c", corner_radius=12, border_width=1, border_color="#ef4444")
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            card,
            text="⚠️ USAGE QUOTA REACHED",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f87171",
        ).pack(anchor="w", padx=16, pady=(16, 6))

        ctk.CTkLabel(
            card,
            text="your usage quota Complete, please stop the processed to further usage",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f1f5f9",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            card,
            text=f"RAM Usage: {used_ram:g} GB used / {req_ram:g} GB Quota limit.\nClick 'Clear Memory' to stop all active workload processes and free up allocated RAM.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 16))

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(0, 12))

        def _on_clear_click():
            try:
                top.destroy()
            except Exception:
                pass
            self._quota_popup_window = None
            self.clear_memory()

        def _on_dismiss():
            try:
                top.destroy()
            except Exception:
                pass
            self._quota_popup_window = None

        top.protocol("WM_DELETE_WINDOW", _on_dismiss)

        ctk.CTkButton(
            btn_box,
            text="🧹 Clear Memory",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=36,
            command=_on_clear_click,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            btn_box,
            text="Dismiss",
            font=ctk.CTkFont(size=13),
            fg_color="#334155",
            hover_color="#475569",
            width=90,
            height=36,
            command=_on_dismiss,
        ).pack(side="right")

    def handle_instance_deleted(self, instance_id: str) -> None:
        self._quota_alert_active = False
        if self._quota_popup_window:
            try:
                self._quota_popup_window.destroy()
            except Exception:
                pass
            self._quota_popup_window = None

        if self._local_instance_id == instance_id:
            self._local_instance_id = None
            self._local_session_id = None
            self._local_allocated = None
            if self._local_refresh_job:
                self.after_cancel(self._local_refresh_job)
                self._local_refresh_job = None
            self.rem_cpu_card.update_metric("—", "", 0)
            self.rem_ram_card.update_metric("—", "", 0)
            self.rem_disk_card.update_metric("—", "", 0)
            self.rem_gpu_card.update_metric("—", "", 0)
            self.remote_badge.configure(
                text="● Disconnected (attach to System A to stream live stats)",
                text_color=MUTED,
            )

    def cleanup(self) -> None:
        if self._quota_popup_window:
            try:
                self._quota_popup_window.destroy()
            except Exception:
                pass
            self._quota_popup_window = None
        if self._use_anim_job:
            self.after_cancel(self._use_anim_job)
            self._use_anim_job = None
        if self._local_refresh_job:
            self.after_cancel(self._local_refresh_job)
            self._local_refresh_job = None
        if self._remote_refresh_job:
            self.after_cancel(self._remote_refresh_job)
            self._remote_refresh_job = None
