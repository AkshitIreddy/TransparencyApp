"""Main application window: a sidebar shell with Rules, Focus, Dimmer and
Settings pages. Talks to the controller for anything that touches the OS."""

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from .. import __version__
from ..config import (MATCH_PROCESS, MIN_FOCUS_BACKGROUND_ALPHA)
from ..dimmer import MAX_DIM_ALPHA
from . import theme
from .rule_card import RuleCard, _pct
from .tooltip import Tooltip
from .window_picker import WindowPickerDialog

NAV = [("rules", "  Rules"), ("focus", "  Focus mode"),
       ("dimmer", "  Screen dimmer"), ("settings", "  Settings")]


class AppWindow(ctk.CTk):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.config_mgr = controller.config
        self.engine = controller.engine
        self._cards = []
        self._page = None
        self._nav_buttons = {}

        theme.apply_appearance(self.config_mgr.get_setting("theme", "dark"))
        self.title("Transparency App")
        self.geometry("940x680")
        self.minsize(820, 560)
        self.configure(fg_color=theme.BG)
        try:
            self.iconbitmap(controller.icon_path)
        except Exception:
            pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self.show_page("rules")

        self.protocol("WM_DELETE_WINDOW", self.controller.on_close_request)
        self._tick()

    # -- sidebar --------------------------------------------------------------

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=210, corner_radius=0,
                           fg_color=theme.SURFACE)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 18))
        ctk.CTkLabel(brand, text="◐", font=theme.font(28, "bold"),
                     text_color=theme.ACCENT).pack(side="left")
        ctk.CTkLabel(brand, text="Transparency", font=theme.h2(),
                     text_color=theme.TEXT).pack(side="left", padx=8)

        for key, label in NAV:
            btn = ctk.CTkButton(
                bar, text=label, anchor="w", height=42, corner_radius=theme.RADIUS_SM,
                font=theme.body(), fg_color="transparent",
                hover_color=theme.SURFACE_2, text_color=theme.TEXT_MUTED,
                command=lambda k=key: self.show_page(k))
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_buttons[key] = btn

        spacer = ctk.CTkFrame(bar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        self.pause_switch = ctk.CTkSwitch(
            bar, text="Transparency on", font=theme.small(),
            progress_color=theme.SUCCESS, command=self._toggle_pause)
        self.pause_switch.select()
        self.pause_switch.pack(padx=20, pady=(0, 6), anchor="w")
        Tooltip(self.pause_switch,
                "Master switch. Off restores every window to normal instantly.")

        ctk.CTkLabel(bar, text=f"v{__version__}", font=theme.small(),
                     text_color=theme.TEXT_MUTED).pack(padx=20, pady=(0, 16),
                                                       anchor="w")

    # -- main area ------------------------------------------------------------

    def _build_main(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(container, fg_color="transparent", height=64)
        header.grid(row=0, column=0, sticky="ew", padx=theme.PAD,
                    pady=(theme.PAD, 6))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ctk.CTkLabel(header, text="Rules", font=theme.h1(),
                                       text_color=theme.TEXT)
        self.page_title.grid(row=0, column=0, sticky="w")
        self.count_badge = ctk.CTkLabel(
            header, text="", font=theme.small(), text_color=theme.TEXT_MUTED)
        self.count_badge.grid(row=0, column=1, sticky="e")

        self.body = ctk.CTkFrame(container, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=theme.PAD,
                       pady=(0, theme.PAD))
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)

    # -- navigation -----------------------------------------------------------

    def show_page(self, key):
        self._page = key
        for k, btn in self._nav_buttons.items():
            active = k == key
            btn.configure(
                fg_color=theme.ACCENT_MUTED if active else "transparent",
                text_color=theme.TEXT if active else theme.TEXT_MUTED)
        self.page_title.configure(text=dict(NAV)[key].strip())
        for child in self.body.winfo_children():
            child.destroy()
        builder = {
            "rules": self._page_rules,
            "focus": self._page_focus,
            "dimmer": self._page_dimmer,
            "settings": self._page_settings,
        }[key]
        builder()

    # -- rules page -----------------------------------------------------------

    def _page_rules(self):
        wrap = ctk.CTkFrame(self.body, fg_color="transparent")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_rowconfigure(2, weight=1)  # the rules list gets the space
        wrap.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(wrap, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, theme.GAP))
        ctk.CTkButton(toolbar, text="＋ Pick a window", height=38,
                      font=theme.body(), fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER,
                      command=self._open_picker).pack(side="left")
        add_manual = ctk.CTkButton(
            toolbar, text="Add manually", height=38, font=theme.body(),
            fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
            text_color=theme.TEXT, command=self._add_manual)
        add_manual.pack(side="left", padx=8)
        Tooltip(add_manual, "Type a window title or app name yourself.")

        self.search = ctk.CTkEntry(toolbar, placeholder_text="Filter rules…",
                                   height=38, width=180, font=theme.body())
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda _e: self._render_rules())

        self._build_presets_bar(wrap)

        self.rules_list = ctk.CTkScrollableFrame(
            wrap, fg_color="transparent")
        self.rules_list.grid(row=2, column=0, sticky="nsew")
        self.rules_list.grid_columnconfigure(0, weight=1)
        self._render_rules()

    def _build_presets_bar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=theme.SURFACE,
                           corner_radius=theme.RADIUS_SM)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, theme.GAP))
        ctk.CTkLabel(bar, text="Presets", font=theme.small(),
                     text_color=theme.TEXT_MUTED).pack(side="left", padx=(12, 8),
                                                       pady=8)
        names = self.config_mgr.list_presets() or ["(none saved)"]
        self.preset_menu = ctk.CTkOptionMenu(
            bar, values=names, width=170, height=30, font=theme.small(),
            fg_color=theme.SURFACE_2, button_color=theme.SURFACE_2,
            button_hover_color=theme.BORDER, text_color=theme.TEXT)
        self.preset_menu.pack(side="left")
        ctk.CTkButton(bar, text="Apply", width=64, height=30, font=theme.small(),
                      fg_color=theme.ACCENT_MUTED, hover_color=theme.ACCENT,
                      command=self._apply_preset).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Save as…", width=76, height=30,
                      font=theme.small(), fg_color=theme.SURFACE_2,
                      hover_color=theme.BORDER, text_color=theme.TEXT,
                      command=self._save_preset).pack(side="left")
        ctk.CTkButton(bar, text="Delete", width=64, height=30, font=theme.small(),
                      fg_color=theme.SURFACE_2, hover_color=theme.DANGER,
                      text_color=theme.TEXT,
                      command=self._delete_preset).pack(side="left", padx=6)

    def _render_rules(self):
        for card in self._cards:
            card.destroy()
        self._cards.clear()
        query = getattr(self, "search", None)
        query = query.get().strip().lower() if query else ""

        rules = self.config_mgr.get_rules()
        shown = [r for r in rules if not query or query in r.pattern.lower()]

        if not rules:
            self._empty_state()
            return
        if not shown:
            lbl = ctk.CTkLabel(self.rules_list, text="No rules match your filter.",
                               font=theme.body(), text_color=theme.TEXT_MUTED)
            lbl.grid(sticky="w", pady=20)
            self._cards.append(lbl)
            return

        for rule in shown:
            card = RuleCard(self.rules_list, rule,
                            on_change=self._on_rule_change,
                            on_delete=self._on_rule_delete)
            card.grid(sticky="ew", pady=6, padx=2)
            self._cards.append(card)

    def _empty_state(self):
        box = ctk.CTkFrame(self.rules_list, fg_color=theme.SURFACE,
                           corner_radius=theme.RADIUS)
        box.grid(sticky="ew", pady=20, padx=2)
        ctk.CTkLabel(box, text="◐", font=theme.font(46, "bold"),
                     text_color=theme.ACCENT_MUTED).pack(pady=(28, 6))
        ctk.CTkLabel(box, text="No transparency rules yet",
                     font=theme.h2(), text_color=theme.TEXT).pack()
        ctk.CTkLabel(
            box, wraplength=460, justify="center", font=theme.body(),
            text_color=theme.TEXT_MUTED,
            text=("Click “Pick a window” to choose one of your open windows, "
                  "then drag its opacity down. The rule keeps working even for "
                  "windows you open later.")).pack(pady=(4, 8), padx=20)
        ctk.CTkButton(box, text="＋ Pick a window", height=40, font=theme.body(),
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._open_picker).pack(pady=(0, 28))

    # -- rules actions --------------------------------------------------------

    def _open_picker(self):
        WindowPickerDialog(self, on_pick=self._add_rule)

    def _add_manual(self):
        rule = self.config_mgr.add_rule("New rule", opacity=220)
        if rule:
            self._render_rules()

    def _add_rule(self, pattern, mode):
        default = 230 if mode == MATCH_PROCESS else 220
        self.config_mgr.add_rule(pattern, opacity=default, match_mode=mode)
        self._render_rules()

    def _on_rule_change(self, rule_id, **fields):
        self.config_mgr.update_rule(rule_id, **fields)

    def _on_rule_delete(self, rule_id):
        self.config_mgr.remove_rule(rule_id)
        self._render_rules()

    def _apply_preset(self):
        name = self.preset_menu.get()
        if self.config_mgr.apply_preset(name):
            self._render_rules()

    def _save_preset(self):
        dialog = ctk.CTkInputDialog(text="Name this preset:", title="Save preset")
        name = dialog.get_input()
        if name and name.strip():
            self.config_mgr.save_preset(name.strip())
            self.preset_menu.configure(values=self.config_mgr.list_presets())
            self.preset_menu.set(name.strip())

    def _delete_preset(self):
        name = self.preset_menu.get()
        if self.config_mgr.delete_preset(name):
            names = self.config_mgr.list_presets() or ["(none saved)"]
            self.preset_menu.configure(values=names)
            self.preset_menu.set(names[0])

    # -- focus page -----------------------------------------------------------

    def _page_focus(self):
        fm = self.config_mgr.get_setting("focus_mode")
        page = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)

        card = self._section(page, "Focus mode")
        ctk.CTkLabel(
            card, wraplength=560, justify="left", font=theme.body(),
            text_color=theme.TEXT_MUTED,
            text=("Dim every window except the one you're using. Switch windows "
                  "and the focus follows automatically. Great for staying on "
                  "task or keeping notes readable behind your work.")
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self.focus_switch = ctk.CTkSwitch(
            card, text="Enable focus mode", font=theme.body(),
            progress_color=theme.ACCENT, command=self._toggle_focus)
        (self.focus_switch.select if self.engine.focus_mode
         else self.focus_switch.deselect)()
        self.focus_switch.pack(anchor="w", padx=16, pady=(0, 14))

        self.focus_active_lbl = ctk.CTkLabel(
            card, text=f"Focused window opacity — {_pct(fm['active_opacity'])}",
            font=theme.small(), text_color=theme.TEXT_MUTED)
        self.focus_active_lbl.pack(anchor="w", padx=16)
        self.focus_active = ctk.CTkSlider(
            card, from_=MIN_FOCUS_BACKGROUND_ALPHA, to=255,
            progress_color=theme.ACCENT, button_color=theme.ACCENT,
            command=lambda v: self._focus_slide("active_opacity", v,
                                                self.focus_active_lbl,
                                                "Focused window opacity"))
        self.focus_active.set(fm["active_opacity"])
        self.focus_active.pack(fill="x", padx=16, pady=(2, 12))

        self.focus_bg_lbl = ctk.CTkLabel(
            card, text=f"Background windows opacity — {_pct(fm['background_opacity'])}",
            font=theme.small(), text_color=theme.TEXT_MUTED)
        self.focus_bg_lbl.pack(anchor="w", padx=16)
        self.focus_bg = ctk.CTkSlider(
            card, from_=MIN_FOCUS_BACKGROUND_ALPHA, to=255,
            progress_color=theme.ACCENT, button_color=theme.ACCENT,
            command=lambda v: self._focus_slide("background_opacity", v,
                                                self.focus_bg_lbl,
                                                "Background windows opacity"))
        self.focus_bg.set(fm["background_opacity"])
        self.focus_bg.pack(fill="x", padx=16, pady=(2, 16))

    def _toggle_focus(self):
        self.controller.set_focus_mode(bool(self.focus_switch.get()))

    def _focus_slide(self, key, value, label, prefix):
        alpha = int(float(value))
        label.configure(text=f"{prefix} — {_pct(alpha)}")
        self.config_mgr.set_setting("focus_mode", {key: alpha})

    # -- dimmer page ----------------------------------------------------------

    def _page_dimmer(self):
        page = ctk.CTkFrame(self.body, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)

        card = self._section(page, "Screen dimmer")
        ctk.CTkLabel(
            card, wraplength=560, justify="left", font=theme.body(),
            text_color=theme.TEXT_MUTED,
            text=("Lay a dark overlay across every monitor to cut glare in a "
                  "dark room. It's click-through, so it never gets in your way.")
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self.dimmer_switch = ctk.CTkSwitch(
            card, text="Enable screen dimmer", font=theme.body(),
            progress_color=theme.ACCENT, command=self._toggle_dimmer)
        (self.dimmer_switch.select if self.controller.dimmer.enabled
         else self.dimmer_switch.deselect)()
        self.dimmer_switch.pack(anchor="w", padx=16, pady=(0, 14))

        intensity = self.controller.dimmer.intensity
        self.dimmer_lbl = ctk.CTkLabel(
            card, text=f"Dimming — {round(intensity / MAX_DIM_ALPHA * 100)}%",
            font=theme.small(), text_color=theme.TEXT_MUTED)
        self.dimmer_lbl.pack(anchor="w", padx=16)
        self.dimmer_slider = ctk.CTkSlider(
            card, from_=0, to=MAX_DIM_ALPHA, progress_color=theme.ACCENT,
            button_color=theme.ACCENT, command=self._dimmer_slide)
        self.dimmer_slider.set(intensity)
        self.dimmer_slider.pack(fill="x", padx=16, pady=(2, 16))

    def _toggle_dimmer(self):
        self.controller.set_dimmer_enabled(bool(self.dimmer_switch.get()))

    def _dimmer_slide(self, value):
        alpha = int(float(value))
        self.dimmer_lbl.configure(
            text=f"Dimming — {round(alpha / MAX_DIM_ALPHA * 100)}%")
        self.controller.set_dimmer_intensity(alpha)

    # -- settings page --------------------------------------------------------

    def _page_settings(self):
        page = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)

        appearance = self._section(page, "Appearance")
        row = ctk.CTkFrame(appearance, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(row, text="Theme", font=theme.body(),
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkSegmentedButton(
            row, values=["Dark", "Light", "System"], command=self._change_theme,
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER
        ).pack(side="right")

        startup = self._section(page, "Startup & behaviour")
        self._switch_row(
            startup, "Start with Windows",
            "Launch Transparency App automatically when you sign in.",
            self.controller.is_startup_enabled(), self._toggle_startup)
        self._switch_row(
            startup, "Global hotkeys",
            "Keyboard shortcuts that work anywhere (see below).",
            self.config_mgr.get_setting("hotkeys_enabled", True),
            self._toggle_hotkeys)

        hot = self._section(page, "Keyboard shortcuts")
        for name, combo in self.controller.hotkey_descriptions():
            r = ctk.CTkFrame(hot, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(r, text=name, font=theme.body(),
                         text_color=theme.TEXT).pack(side="left")
            ctk.CTkLabel(r, text=combo, font=theme.small(),
                         text_color=theme.TEXT_MUTED, fg_color=theme.SURFACE_2,
                         corner_radius=6, padx=10, pady=2).pack(side="right")

        data = self._section(page, "Settings file")
        r = ctk.CTkFrame(data, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(r, text="Export…", height=34, font=theme.body(),
                      fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
                      text_color=theme.TEXT, command=self._export).pack(side="left")
        ctk.CTkButton(r, text="Import…", height=34, font=theme.body(),
                      fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
                      text_color=theme.TEXT,
                      command=self._import).pack(side="left", padx=8)
        ctk.CTkButton(r, text="Restore all windows now", height=34,
                      font=theme.body(), fg_color=theme.SURFACE_2,
                      hover_color=theme.ACCENT_MUTED, text_color=theme.TEXT,
                      command=self.controller.restore_all).pack(side="right")

    def _switch_row(self, parent, title, desc, initial, command):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=8)
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text, text=title, font=theme.body(),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(text, text=desc, font=theme.small(),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        sw = ctk.CTkSwitch(row, text="", progress_color=theme.ACCENT,
                           command=lambda: command(bool(sw.get())))
        (sw.select if initial else sw.deselect)()
        sw.pack(side="right")

    def _change_theme(self, value):
        mode = value.lower()
        self.config_mgr.set_setting("theme", mode)
        self.controller.apply_theme(mode)

    def _toggle_startup(self, enabled):
        self.controller.set_startup(enabled)

    def _toggle_hotkeys(self, enabled):
        self.controller.set_hotkeys_enabled(enabled)

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile="transparency-settings.json")
        if path:
            self.config_mgr.export_to(path)

    def _import(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path and self.config_mgr.import_from(path):
            theme.apply_appearance(self.config_mgr.get_setting("theme", "dark"))
            self.show_page(self._page)

    # -- shared helpers -------------------------------------------------------

    def _section(self, parent, title):
        header = ctk.CTkLabel(parent, text=title, font=theme.h2(),
                              text_color=theme.TEXT)
        header.pack(anchor="w", pady=(6, 6))
        card = ctk.CTkFrame(parent, fg_color=theme.SURFACE,
                            corner_radius=theme.RADIUS)
        card.pack(fill="x", pady=(0, 16))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", pady=14)
        return inner

    # -- master switch + live count ------------------------------------------

    def _toggle_pause(self):
        # Switch ON = transparency active = engine NOT paused.
        self.controller.set_paused(not bool(self.pause_switch.get()))

    def set_pause_state(self, paused):
        (self.pause_switch.deselect if paused else self.pause_switch.select)()

    def set_focus_state(self, enabled):
        if hasattr(self, "focus_switch") and self.focus_switch.winfo_exists():
            (self.focus_switch.select if enabled else self.focus_switch.deselect)()

    def _tick(self):
        try:
            n = self.engine.affected_window_count()
            self.count_badge.configure(
                text=f"{n} window{'s' if n != 1 else ''} affected"
                if not self.engine.paused else "paused")
        except Exception:
            pass
        self.after(1000, self._tick)
