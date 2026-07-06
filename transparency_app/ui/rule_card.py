"""A card representing one transparency rule.

Emits changes through callbacks; it never touches the config directly so the
main window stays the single place that talks to the model.
"""

import customtkinter as ctk

from ..config import MATCH_PROCESS, MATCH_TITLE, MATCH_TITLE_EXACT
from . import theme
from .tooltip import Tooltip

_MODE_LABELS = {
    MATCH_TITLE: "Title contains",
    MATCH_TITLE_EXACT: "Title is exactly",
    MATCH_PROCESS: "App (process)",
}
_LABEL_TO_MODE = {v: k for k, v in _MODE_LABELS.items()}

SHADES = [("25%", 64), ("50%", 128), ("75%", 191), ("100%", 255)]


def _pct(alpha):
    return f"{round(alpha / 255 * 100)}%"


class RuleCard(ctk.CTkFrame):
    def __init__(self, master, rule, on_change, on_delete):
        super().__init__(master, fg_color=theme.CARD, corner_radius=theme.RADIUS,
                         border_width=1, border_color=theme.BORDER)
        self.rule = rule
        self.on_change = on_change
        self.on_delete = on_delete
        self._build()

    # -- layout ---------------------------------------------------------------

    def _build(self):
        pad = 14
        # Row 1: enable switch, pattern entry, match mode, delete.
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=pad, pady=(pad, 6))

        self.enabled = ctk.CTkSwitch(
            top, text="", width=44, command=self._toggle_enabled,
            progress_color=theme.ACCENT)
        self.enabled.pack(side="left")
        (self.enabled.select if self.rule.enabled else self.enabled.deselect)()
        Tooltip(self.enabled, "Turn this rule on or off without deleting it.")

        self.pattern = ctk.CTkEntry(top, font=theme.body(), height=34)
        self.pattern.insert(0, self.rule.pattern)
        self.pattern.pack(side="left", fill="x", expand=True, padx=8)
        self.pattern.bind("<FocusOut>", lambda _e: self._commit_pattern())
        self.pattern.bind("<Return>", lambda _e: self._commit_pattern())

        self.mode = ctk.CTkOptionMenu(
            top, values=list(_MODE_LABELS.values()), width=150, height=34,
            font=theme.small(), command=self._change_mode,
            fg_color=theme.SURFACE_2, button_color=theme.SURFACE_2,
            button_hover_color=theme.BORDER, text_color=theme.TEXT)
        self.mode.set(_MODE_LABELS[self.rule.match_mode])
        self.mode.pack(side="left", padx=(0, 8))
        Tooltip(self.mode, "How this rule matches windows. 'App (process)' is "
                           "the most reliable — it ignores title changes.")

        delete = ctk.CTkButton(top, text="✕", width=34, height=34,
                               fg_color="transparent", hover_color=theme.DANGER,
                               text_color=theme.TEXT_MUTED,
                               command=lambda: self.on_delete(self.rule.id))
        delete.pack(side="left")
        Tooltip(delete, "Delete this rule")

        # Row 2: opacity slider + live percentage.
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=pad, pady=6)
        ctk.CTkLabel(mid, text="Opacity", font=theme.small(),
                     text_color=theme.TEXT_MUTED, width=60,
                     anchor="w").pack(side="left")
        self.slider = ctk.CTkSlider(
            mid, from_=0, to=255, number_of_steps=255,
            command=self._slide, progress_color=theme.ACCENT,
            button_color=theme.ACCENT, button_hover_color=theme.ACCENT_HOVER)
        self.slider.set(self.rule.opacity)
        self.slider.pack(side="left", fill="x", expand=True, padx=8)
        self.pct = ctk.CTkLabel(mid, text=_pct(self.rule.opacity),
                                font=theme.font(13, "bold"),
                                text_color=theme.TEXT, width=48)
        self.pct.pack(side="left")

        # Row 3: quick shades.
        shades = ctk.CTkFrame(self, fg_color="transparent")
        shades.pack(fill="x", padx=pad, pady=(2, 6))
        ctk.CTkLabel(shades, text="Shades", font=theme.small(),
                     text_color=theme.TEXT_MUTED, width=60,
                     anchor="w").pack(side="left")
        for label, value in SHADES:
            b = ctk.CTkButton(shades, text=label, width=54, height=28,
                              font=theme.small(), fg_color=theme.SURFACE_2,
                              hover_color=theme.ACCENT_MUTED,
                              text_color=theme.TEXT,
                              command=lambda v=value: self._set_opacity(v))
            b.pack(side="left", padx=3)

        # Row 4: behaviour toggles.
        toggles = ctk.CTkFrame(self, fg_color="transparent")
        toggles.pack(fill="x", padx=pad, pady=(2, pad))
        self.click = ctk.CTkSwitch(
            toggles, text="Click-through", font=theme.small(),
            command=self._toggle_click, progress_color=theme.ACCENT)
        (self.click.select if self.rule.click_through else self.click.deselect)()
        self.click.pack(side="left")
        Tooltip(self.click, "Let mouse clicks pass through the window to "
                            "whatever is behind it. A global hotkey turns this "
                            "off everywhere if you get stuck.")
        self.topmost = ctk.CTkSwitch(
            toggles, text="Always on top", font=theme.small(),
            command=self._toggle_topmost, progress_color=theme.ACCENT)
        (self.topmost.select if self.rule.topmost else self.topmost.deselect)()
        self.topmost.pack(side="left", padx=16)
        Tooltip(self.topmost, "Keep matching windows above other windows.")

    # -- events ---------------------------------------------------------------

    def _emit(self, **fields):
        self.on_change(self.rule.id, **fields)

    def _commit_pattern(self):
        text = self.pattern.get().strip()
        if text and text != self.rule.pattern:
            self.rule.pattern = text
            self._emit(pattern=text)

    def _change_mode(self, label):
        mode = _LABEL_TO_MODE.get(label, MATCH_TITLE)
        self.rule.match_mode = mode
        self._emit(match_mode=mode)

    def _slide(self, value):
        alpha = int(float(value))
        self.rule.opacity = alpha
        self.pct.configure(text=_pct(alpha))
        self._emit(opacity=alpha)

    def _set_opacity(self, alpha):
        self.slider.set(alpha)
        self._slide(alpha)

    def _toggle_enabled(self):
        self.rule.enabled = bool(self.enabled.get())
        self._emit(enabled=self.rule.enabled)

    def _toggle_click(self):
        self.rule.click_through = bool(self.click.get())
        self._emit(click_through=self.rule.click_through)

    def _toggle_topmost(self):
        self.rule.topmost = bool(self.topmost.get())
        self._emit(topmost=self.rule.topmost)
