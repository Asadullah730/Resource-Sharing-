from __future__ import annotations

import customtkinter as ctk

from .theme import CARD_ALT, MUTED, TEXT


class MetricCard(ctk.CTkFrame):
    """Displays a single host or guest system metric with a live progress bar."""

    def __init__(self, master, title: str, bar_color: str, **kwargs):
        super().__init__(master, fg_color=CARD_ALT, corner_radius=12, **kwargs)
        self.bar_color = bar_color
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=MUTED,
        ).pack(anchor="w", padx=14, pady=(12, 0))

        self.value = ctk.CTkLabel(
            self,
            text="—",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=TEXT,
        )
        self.value.pack(anchor="w", padx=14, pady=(2, 0))

        self.detail = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        self.detail.pack(anchor="w", padx=14, pady=(0, 6))

        self.bar = ctk.CTkProgressBar(
            self,
            height=8,
            progress_color=bar_color,
            fg_color="#0d141c",
        )
        self.bar.pack(fill="x", padx=14, pady=(0, 14))
        self.bar.set(0)

    def update_metric(self, value: str, detail: str, ratio: float) -> None:
        self.value.configure(text=value)
        self.detail.configure(text=detail)
        self.bar.set(max(0.0, min(1.0, ratio)))
