from __future__ import annotations

import customtkinter as ctk

from .theme import ACCENT, CARD, CARD_ALT, MUTED, TEXT


def set_textbox_text(widget: ctk.CTkTextbox, value: str) -> None:
    """Safely updates a disabled CTkTextbox with new text."""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


def create_panel(parent, title: str) -> ctk.CTkFrame:
    """Creates a standard rounded panel card with a prominent section title."""
    frame = ctk.CTkFrame(parent, fg_color=CARD_ALT, corner_radius=12)
    ctk.CTkLabel(
        frame,
        text=title,
        font=ctk.CTkFont(size=15, weight="bold"),
        text_color=TEXT,
    ).pack(anchor="w", padx=14, pady=(12, 8))
    return frame


def create_labeled_entry(
    parent,
    label: str,
    placeholder: str,
    hint: str = "",
) -> tuple[ctk.CTkEntry, ctk.CTkLabel]:
    """Creates a standard labeled entry row with an optional hint."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=14, pady=5)
    ctk.CTkLabel(
        row,
        text=label,
        width=130,
        anchor="w",
        font=ctk.CTkFont(size=13),
        text_color=MUTED,
    ).pack(side="left")
    entry = ctk.CTkEntry(
        row,
        placeholder_text=placeholder,
        height=36,
        fg_color="#0d141c",
        border_color="#334155",
    )
    entry.pack(side="left", fill="x", expand=True, padx=(8, 8 if hint else 0))
    hint_label = ctk.CTkLabel(
        row,
        text=hint,
        width=120 if hint else 0,
        anchor="e",
        text_color=ACCENT,
        font=ctk.CTkFont(size=12),
    )
    if hint:
        hint_label.pack(side="right")
    return entry, hint_label


def create_scrollable_tab(parent) -> ctk.CTkScrollableFrame:
    """Creates a transparent scrollable container inside a tab."""
    parent.configure(fg_color=CARD)
    scroller = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
    scroller.pack(fill="both", expand=True, padx=4, pady=4)
    return scroller
