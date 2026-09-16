from __future__ import annotations

import webbrowser
from pathlib import Path

import customtkinter as ctk

from .bootstrap import build_service
from .models import HostInventory
from .ports.compute import AccessGrant, MISSING, RUNNING, ERROR

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
        self.geometry("1080x860")
        self.minsize(800, 560)
        self.configure(fg_color=BG)

        self.service = build_service()
        self.host: HostInventory | None = None
        self._last_pem_path: str | None = None
        self._refresh_job: str | None = None

        self.page = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.page.pack(fill="both", expand=True)

        self._build_header(self.page)
        self._build_system_dashboard(self.page)

        self.tabs = ctk.CTkTabview(
            self.page,
            fg_color=CARD,
            height=720,
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
            text="Share CPU, RAM, and disk with a SHA certificate  ·  runtime-agnostic",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(anchor="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        backend, ok, reason = self.service.backend_status()
        self.backend_chip = ctk.CTkLabel(
            actions,
            text=f"  {backend.upper()}  ",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#14532d" if ok else "#7f1d1d",
            text_color=OK if ok else ERR,
            corner_radius=8,
        )
        self.backend_chip.pack(side="left", padx=(0, 8), ipady=4)
        self.backend_hint = ctk.CTkLabel(
            actions, text=reason, font=ctk.CTkFont(size=12), text_color=MUTED
        )
        self.backend_hint.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            actions,
            text="Refresh System",
            width=140,
            height=34,
            fg_color="#1d4ed8",
            hover_color="#1e40af",
            command=lambda: self.refresh_system(initial=False),
        ).pack(side="left")

    def _build_system_dashboard(self, parent):
        shell = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16)
        shell.pack(fill="x", padx=18, pady=(0, 12))

        title_row = ctk.CTkFrame(shell, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            title_row,
            text="Physical host  ·  live Windows stats (this is not the VM)",
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
        self.cpu_card = MetricCard(metrics, "CPU", CPU_COLOR)
        self.ram_card = MetricCard(metrics, "MEMORY", RAM_COLOR)
        self.disk_card = MetricCard(metrics, "DISK", DISK_COLOR)
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

    def _build_provider_tab(self, parent):
        scroll = self._scrollable_tab(parent)
        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = self._panel(body, "Allocate resources to share")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(
            left,
            text="These fields become the guest VM. The dashboard above stays the physical PC.",
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

        ctk.CTkButton(
            left,
            text="Create SHA Certificate + Virtual Machine",
            fg_color="#15803d",
            hover_color="#166534",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.create_share,
        ).pack(fill="x", padx=14, pady=(16, 8))
        self.provider_status = ctk.CTkLabel(
            left, text="System details load automatically. Fill the fields, then create a share.",
            font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=360, justify="left",
        )
        self.provider_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = self._panel(body, "Guest VM system details")
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
            sha_row, placeholder_text="SHA-256 key appears here after you share",
            height=36, fg_color="#0d141c", border_color="#334155",
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

    def _build_consumer_tab(self, parent):
        scroll = self._scrollable_tab(parent)
        body = ctk.CTkFrame(scroll, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        left = self._panel(body, "Resources you need")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(
            left,
            text="Request must be less than or equal to what the SHA certificate allocated.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            wraplength=360,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        self.need_cpu, _ = self._labeled_entry(left, "CPU cores", "e.g. 1")
        self.need_ram, _ = self._labeled_entry(left, "RAM", "e.g. 2 GB")
        self.need_disk, _ = self._labeled_entry(left, "Disk", "e.g. 10 GB")
        self.need_user, _ = self._labeled_entry(left, "Your name", "Consumer name")
        self.need_sha, _ = self._labeled_entry(left, "SHA key", "Certificate fingerprint")

        ctk.CTkLabel(
            left, text="Optional PEM certificate", font=ctk.CTkFont(size=12), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(8, 4))
        self.need_pem = ctk.CTkTextbox(left, height=120, fg_color="#0d141c")
        self.need_pem.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkButton(
            left,
            text="Use Resources",
            fg_color="#0e7490",
            hover_color="#155e75",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.use_resources,
        ).pack(fill="x", padx=14, pady=(4, 8))
        self.consumer_status = ctk.CTkLabel(
            left, text="Enter the SHA key from the sharer, then attach to the VM.",
            font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=360, justify="left",
        )
        self.consumer_status.pack(anchor="w", padx=14, pady=(0, 12))

        right = self._panel(body, "Access details")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.consumer_result = ctk.CTkTextbox(
            right, height=280, fg_color="#0d141c", text_color="#d1fae5",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.consumer_result.pack(fill="x", padx=14, pady=(0, 14))
        self.consumer_result.insert("1.0", "Connection details will appear here after a successful attach.")
        self.consumer_result.configure(state="disabled")

    def _build_vm_tab(self, parent):
        parent.configure(fg_color=CARD)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(
            bar, text="Created virtual machines", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(bar, text="Refresh list", width=120, command=self.refresh_vms).pack(side="right")
        self.vm_container = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.vm_container.pack(fill="both", expand=True, padx=8, pady=8)
        self.refresh_vms()

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
        self._mousewheel_handler = on_wheel

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
            text=(
                f"OS {host.os} ({host.architecture})    IP {host.ip}\n"
                f"{host.cpu_name}"
            )
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
            self.provider_status.configure(
                text="System details are visible above. Choose what to share, then create the certificate and VM.",
                text_color=OK,
            )
            self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(4000, self._tick)

    def _tick(self):
        self.refresh_system(initial=False)
        self._schedule_refresh()

    def create_share(self):
        if self.host is None:
            self.provider_status.configure(text="Wait for system details to finish loading.", text_color=ERR)
            return
        try:
            result = self.service.share_resources(
                ram_text=self.entry_ram.get(),
                disk_text=self.entry_disk.get(),
                cpu_text=self.entry_cpu.get(),
                target_user=self.entry_user.get(),
                purpose=self.entry_purpose.get(),
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
        target = self.entry_user.get().strip()
        details = (
            f"GUEST VIRTUAL MACHINE  [{guest['state'].upper()}]\n"
            f"  Name: {guest['hostname']}\n"
            f"  OS: {guest['os']}\n"
            f"  Guest IP: {guest['ip']}\n"
            f"  vCPU: {guest['vcpu']:g} cores   (this VM, not the physical 8-core host)\n"
            f"  RAM: {guest['ram_used_gb']:g} GB used / {guest['memory_gb']:g} GB allocated\n"
            f"  Disk: {guest['disk_used_gb']:g} GB used / {guest['disk_gb']:g} GB allocated\n"
            f"  Target user: {guest['target_user']}\n"
            f"  Purpose: {guest['purpose']}\n\n"
            f"WHAT TO DO NEXT\n"
            f"  1. Click Copy and send the SHA key to {target or 'the other user'}.\n"
            f"  2. They open the Use Resources tab.\n"
            f"  3. They enter CPU / RAM / disk up to "
            f"{allocated['cpu_cores']:g} / {allocated['ram_gb']:g} GB / {allocated['disk_gb']:g} GB.\n"
            f"  4. They paste the SHA key and click Use Resources.\n\n"
            f"SHA-256: {result['sha_key']}\n"
            f"Workspace: {result['instance']['workspace']}\n"
            f"Certificate: {result['pem_path']}\n\n"
            f"{result['pem']}"
        )
        self._set_text(self.provider_result, details)
        self.provider_status.configure(
            text=f"Guest VM is running with {guest['vcpu']:g} CPU, {guest['memory_gb']:g} GB RAM, {guest['disk_gb']:g} GB disk. Copy the SHA key and send it to {target}.",
            text_color=OK,
        )
        self.refresh_vms()
        self.refresh_system(initial=False)

    def copy_sha_key(self):
        key = self.entry_sha_key.get().strip()
        if not key:
            self.provider_status.configure(text="No SHA key to copy yet.", text_color=ERR)
            return
        self.clipboard_clear()
        self.clipboard_append(key)
        self.provider_status.configure(text="SHA key copied to clipboard.", text_color=ACCENT)

    def open_cert_folder(self):
        folder = Path(self._last_pem_path).parent if self._last_pem_path else self.service.data_root / "certs"
        folder.mkdir(parents=True, exist_ok=True)
        webbrowser.open(folder.as_uri())

    def use_resources(self):
        try:
            result = self.service.use_resources(
                ram_text=self.need_ram.get(),
                disk_text=self.need_disk.get(),
                cpu_text=self.need_cpu.get(),
                sha_key=self.need_sha.get(),
                consumer_user=self.need_user.get(),
                certificate_text=self.need_pem.get("1.0", "end"),
            )
        except Exception as exc:
            self.consumer_status.configure(text=str(exc), text_color=ERR)
            return

        grant = AccessGrant.from_dict(result["connection"])
        allocated = result["allocated"]
        details = (
            f"ATTACHED TO GUEST VM  [{result['instance']['status']}]\n"
            f"  VM: {result['instance']['instance_id']}\n"
            f"  Guest CPU: {allocated['cpu_cores']:g} vCPU\n"
            f"  Guest RAM: {allocated['ram_gb']:g} GB\n"
            f"  Guest Disk: {allocated['disk_gb']:g} GB\n"
            f"  You requested: {result['requested']}\n"
            f"  Workspace: {result['instance']['workspace']}\n\n"
            f"ACCESS\n{grant.display_text()}"
        )
        self._set_text(self.consumer_result, details)
        self.consumer_status.configure(
            text="Certificate verified. You are attached to the shared virtual machine.",
            text_color=OK,
        )
        location = grant.location or result["instance"]["workspace"]
        try:
            webbrowser.open(Path(location).as_uri())
        except Exception:
            pass
        self.refresh_vms()

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
            guest_line = (
                f"Guest VM: {record.spec.label()}\n"
                f"This is the virtual machine envelope, not the physical host."
            )
            if offer is not None:
                host = offer.host
                guest_line = (
                    f"Guest VM: {record.spec.label()}\n"
                    f"Target user: {offer.target_user}  ·  Purpose: {offer.purpose or '—'}\n"
                    f"Hosted on {host.hostname} ({host.os}) — host is separate from these guest sizes"
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

    def _on_close(self):
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
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
