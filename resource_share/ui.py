from __future__ import annotations

import customtkinter as ctk

from .bootstrap import build_service
from .components import (
    ACCENT,
    BG,
    CARD,
    CARD_ALT,
    CPU_COLOR,
    DISK_COLOR,
    ERR,
    MUTED,
    OK,
    RAM_COLOR,
    TEXT,
    WARN,
    ConsumerTabComponent,
    HeaderComponent,
    MetricCard,
    ProviderTabComponent,
    SystemDashboardComponent,
    VMTabComponent,
    create_labeled_entry,
    create_panel,
    create_scrollable_tab,
    set_textbox_text,
)
from .models import HostInventory
from .network.client import RemoteResourceClient
from .network.server import get_local_ip


class ResourceShareApp(ctk.CTk):
    """Main application window coordinating modular UI components."""

    def __init__(self):
        super().__init__()
        self.title("Resource Sharing Manager")
        self.geometry("1120x900")
        self.minsize(860, 600)
        self.configure(fg_color=BG)

        self.service = build_service()
        self.client = RemoteResourceClient()
        self.host: HostInventory | None = None
        self._refresh_job: str | None = None

        # Main scrollable canvas container
        self.page = ctk.CTkScrollableFrame(self, fg_color=BG, corner_radius=0)
        self.page.pack(fill="both", expand=True)

        # 1. Header Component
        local_ip = get_local_ip()
        port = getattr(self.service.server_manager, "actual_port", 5890)
        self.header = HeaderComponent(
            self.page,
            on_check_k8s=self.check_k8s,
            on_refresh_system=lambda: self.refresh_system(initial=False),
            on_copy_clipboard=self._copy_to_clipboard,
            initial_ip=local_ip,
            initial_port=port,
        )
        self.header.pack(fill="x", padx=20, pady=(16, 8))

        # 2. Host System Dashboard Component
        self.dashboard = SystemDashboardComponent(self.page)
        self.dashboard.pack(fill="x", padx=18, pady=(0, 12))

        # 3. Tabview Container
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

        # 4. Tab Components
        self.provider_tab = ProviderTabComponent(
            self.tabs.tab("Share Resources"),
            service=self.service,
            get_host=lambda: self.host,
            on_share_completed=self._on_share_completed,
            on_copy_clipboard=self._copy_to_clipboard,
        )
        self.provider_tab.pack(fill="both", expand=True)

        self.consumer_tab = ConsumerTabComponent(
            self.tabs.tab("Use Resources"),
            service=self.service,
            client=self.client,
            on_refresh_vms=self.refresh_vms,
        )
        self.consumer_tab.pack(fill="both", expand=True)

        self.vm_tab = VMTabComponent(
            self.tabs.tab("Virtual Machines"),
            service=self.service,
            on_vm_deleted=self._on_vm_deleted,
        )
        self.vm_tab.pack(fill="both", expand=True)

        # Lifecycle & Window bindings
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_resize, add="+")
        self.after(80, self._wire_mousewheel)
        self.after(50, lambda: self.refresh_system(initial=True))
        self.after(100, self.check_k8s)

    # ----------------------------------------------------------------------
    # System Status & Kubernetes Coordination
    # ----------------------------------------------------------------------
    def check_k8s(self) -> None:
        backend, ok, reason = self.service.backend_status()
        is_k8s = backend.lower() == "kubernetes"
        self.header.update_k8s_status(is_k8s, ok)
        self.provider_tab.update_k8s_state(is_k8s, ok, reason)

    def refresh_system(self, initial: bool = False) -> None:
        try:
            self.host = self.service.inventory(cpu_interval=0.2 if initial else 0.0)
        except Exception as exc:
            self.dashboard.update_error(str(exc))
            return

        reserved = self.service.reserved_spec()
        remaining = self.service.remaining_shareable(self.host)
        self.dashboard.update_host(self.host, reserved, remaining)
        self.provider_tab.update_hints(remaining.cpu_cores, remaining.ram_gb, remaining.disk_gb, remaining.gpu_count)

        if initial:
            self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(4000, self._tick)

    def _tick(self) -> None:
        self.refresh_system(initial=False)
        self._schedule_refresh()

    def refresh_vms(self) -> None:
        self.vm_tab.refresh_vms()

    def _on_vm_deleted(self, instance_id: str) -> None:
        self.consumer_tab.handle_instance_deleted(instance_id)
        self.refresh_system(initial=False)

    def _on_share_completed(self) -> None:
        self.refresh_vms()
        self.refresh_system(initial=False)

    # ----------------------------------------------------------------------
    # Window & Helper Utilities
    # ----------------------------------------------------------------------
    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_resize(self, event) -> None:
        if event.widget is not self:
            return
        width = max(event.width - 80, 400)
        self.dashboard.set_wraplength(width)

    def _wire_mousewheel(self) -> None:
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

    def _on_close(self) -> None:
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self.provider_tab.cleanup()
        self.consumer_tab.cleanup()
        try:
            self.service.server_manager.stop()
        except Exception:
            pass
        self.unbind_all("<MouseWheel>")
        self.destroy()

    # Backwards-compatible aliases for tests or external callers
    @staticmethod
    def _set_text(widget: ctk.CTkTextbox, value: str) -> None:
        set_textbox_text(widget, value)

    def create_share(self) -> None:
        self.provider_tab.create_share()

    def delete_vm(self, instance_id: str, btn: ctk.CTkButton | None = None) -> None:
        self.vm_tab.delete_vm(instance_id, btn)


def main() -> None:
    app = ResourceShareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
