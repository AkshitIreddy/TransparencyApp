"""A tiny hover tooltip — newcomers lean on these to learn the controls."""

import customtkinter as ctk

from . import theme


class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except Exception:
            return
        self._tip = tip = ctk.CTkToplevel(self.widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        try:
            tip.attributes("-alpha", 0.96)
        except Exception:
            pass
        frame = ctk.CTkFrame(tip, corner_radius=theme.RADIUS_SM,
                             fg_color=theme.SURFACE_2, border_width=1,
                             border_color=theme.BORDER)
        frame.pack()
        ctk.CTkLabel(frame, text=self.text, font=theme.small(),
                     text_color=theme.TEXT, justify="left",
                     wraplength=260).pack(padx=10, pady=6)
        tip.update_idletasks()
        tip.geometry(f"+{x}+{y}")

    def _hide(self, _=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
