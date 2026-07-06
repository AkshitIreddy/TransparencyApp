"""Modal that lists live windows so users add a rule by clicking, instead of
guessing the exact title text (the old app's biggest usability trap)."""

import customtkinter as ctk

from .. import winapi
from ..config import MATCH_PROCESS, MATCH_TITLE
from . import theme


class WindowPickerDialog(ctk.CTkToplevel):
    def __init__(self, master, on_pick):
        super().__init__(master)
        self.on_pick = on_pick
        self._rows = []
        self._all = []

        self.title("Pick a window")
        self.geometry("520x560")
        self.minsize(420, 420)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.after(80, self._grab)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD, pady=(theme.PAD, theme.GAP))
        ctk.CTkLabel(header, text="Pick a window",
                     font=theme.h2(), text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(header,
                     text="Click a window to create a transparency rule for it.",
                     font=theme.small(), text_color=theme.TEXT_MUTED).pack(anchor="w")

        self.search = ctk.CTkEntry(self, placeholder_text="Search open windows…",
                                   height=38, font=theme.body())
        self.search.pack(fill="x", padx=theme.PAD)
        self.search.bind("<KeyRelease>", lambda _e: self._render())

        self.mode = ctk.StringVar(value="title")
        mode_row = ctk.CTkFrame(self, fg_color="transparent")
        mode_row.pack(fill="x", padx=theme.PAD, pady=(theme.GAP, 0))
        ctk.CTkLabel(mode_row, text="Match new rule by:", font=theme.small(),
                     text_color=theme.TEXT_MUTED).pack(side="left")
        ctk.CTkSegmentedButton(
            mode_row, values=["Window title", "App (process)"],
            command=self._mode_changed, font=theme.small(),
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
        ).pack(side="left", padx=theme.GAP)

        self.list = ctk.CTkScrollableFrame(self, fg_color=theme.SURFACE,
                                           corner_radius=theme.RADIUS)
        self.list.pack(fill="both", expand=True, padx=theme.PAD,
                       pady=theme.PAD)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=theme.PAD, pady=(0, theme.PAD))
        ctk.CTkButton(footer, text="Refresh", width=90, height=34,
                      fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
                      text_color=theme.TEXT, command=self.refresh).pack(side="left")
        ctk.CTkButton(footer, text="Close", width=90, height=34,
                      fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
                      text_color=theme.TEXT, command=self.destroy).pack(side="right")

        self.refresh()

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.search.focus_set()
        except Exception:
            pass

    def _mode_changed(self, value):
        self.mode.set(MATCH_PROCESS if value.startswith("App") else MATCH_TITLE)

    def refresh(self):
        seen_titles = set()
        rows = []
        for info in winapi.enum_app_windows():
            key = (info.title, info.process)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            rows.append(info)
        rows.sort(key=lambda i: (i.process, i.title.lower()))
        self._all = rows
        self._render()

    def _render(self):
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        query = self.search.get().strip().lower()

        matches = [
            i for i in self._all
            if not query or query in i.title.lower() or query in i.process
        ]
        if not matches:
            empty = ctk.CTkLabel(self.list, text="No open windows match.",
                                 font=theme.body(), text_color=theme.TEXT_MUTED)
            empty.pack(pady=24)
            self._rows.append(empty)
            return

        for info in matches:
            self._rows.append(self._row(info))

    def _row(self, info):
        row = ctk.CTkFrame(self.list, fg_color=theme.CARD,
                           corner_radius=theme.RADIUS_SM)
        row.pack(fill="x", padx=6, pady=4)
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        ctk.CTkLabel(text, text=info.title or "(untitled)", font=theme.body(),
                     text_color=theme.TEXT, anchor="w",
                     justify="left").pack(anchor="w", fill="x")
        ctk.CTkLabel(text, text=info.process or "unknown process",
                     font=theme.small(), text_color=theme.TEXT_MUTED,
                     anchor="w").pack(anchor="w")
        ctk.CTkButton(row, text="Add", width=64, height=30,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=lambda i=info: self._pick(i)).pack(
                          side="right", padx=12)
        return row

    def _pick(self, info):
        mode = self.mode.get()
        pattern = info.process if mode == MATCH_PROCESS else info.title
        if pattern:
            self.on_pick(pattern, mode)
        self.destroy()
