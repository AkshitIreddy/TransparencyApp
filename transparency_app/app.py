"""Application controller: owns the config, engine, dimmer, hotkeys, tray and
main window, and is the single mediator between them.

Threading contract: Tk must only be touched from the main thread. Anything
arriving from another thread (hotkey pump, tray) is marshalled onto the Tk
loop with ``root.after``. The engine and config are internally thread-safe.
"""

import logging

from . import hotkeys as hk
from . import paths, startup, winapi
from .config import ConfigManager
from .dimmer import ScreenDimmer
from .engine import TransparencyEngine

log = logging.getLogger("transparency_app.app")

# (name shown in UI, hotkey_id, modifiers, vk, controller-method-name)
HOTKEY_DEFS = [
    ("Toggle transparency", 1, hk.MOD_CONTROL | hk.MOD_ALT, ord("T"),
     "toggle_paused", "Ctrl+Alt+T"),
    ("Toggle focus mode", 2, hk.MOD_CONTROL | hk.MOD_ALT, ord("F"),
     "toggle_focus", "Ctrl+Alt+F"),
    ("More opaque (active window)", 3, hk.MOD_CONTROL | hk.MOD_ALT, hk.VK_UP,
     "nudge_up", "Ctrl+Alt+↑"),
    ("More transparent (active window)", 4, hk.MOD_CONTROL | hk.MOD_ALT,
     hk.VK_DOWN, "nudge_down", "Ctrl+Alt+↓"),
    ("Restore everything (panic)", 5, hk.MOD_CONTROL | hk.MOD_ALT, hk.VK_HOME,
     "panic", "Ctrl+Alt+Home"),
]

NUDGE_STEP = 20


class AppController:
    def __init__(self):
        paths.setup_logging()
        paths.migrate_legacy_config()
        self.icon_path = self._resolve_icon()

        self.config = ConfigManager(paths.config_path())
        self.engine = TransparencyEngine(self.config, ledger_path=paths.ledger_path())
        self.dimmer = ScreenDimmer()
        self.dimmer.set_intensity(self.config.get_setting("dimmer_intensity", 120))
        self.hotkeys = hk.HotkeyManager()

        self.window = None
        self.tray = None
        self._dimmer_tick_scheduled = False

    def _resolve_icon(self):
        for name in ("icon.ico", "assets/icon.ico"):
            path = paths.resource_path(name)
            try:
                import os
                if os.path.exists(path):
                    return path
            except Exception:
                pass
        return None

    # -- startup / shutdown ---------------------------------------------------

    def run(self):
        from .tray import Tray
        from .ui.app_window import AppWindow

        self.engine.start()
        if self.config.get_setting("hotkeys_enabled", True):
            self._register_hotkeys()

        self.window = AppWindow(self)
        self.tray = Tray(self, self.icon_path)
        self.tray.start()

        if self.config.get_setting("start_minimized", False):
            self.window.after(200, self.hide_window)

        try:
            self.window.mainloop()
        finally:
            self._shutdown()

    def _shutdown(self):
        log.info("shutting down")
        try:
            self.config.set_setting("dimmer_intensity", self.dimmer.intensity)
        except Exception:
            pass
        for closer in (self.hotkeys.stop, self.dimmer.destroy,
                       self.engine.stop, self.config.close):
            try:
                closer()
            except Exception:
                log.exception("error during shutdown step")
        if self.tray:
            self.tray.stop()

    # -- thread marshalling ---------------------------------------------------

    def _ui(self, fn):
        """Run fn on the Tk main thread (safe from any thread)."""
        if self.window is not None:
            try:
                self.window.after(0, fn)
                return
            except Exception:
                pass
        fn()

    # -- window visibility ----------------------------------------------------

    def show_window(self):
        self._ui(self._show_window_impl)

    def _show_window_impl(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide_window(self):
        self.window.withdraw()

    def on_close_request(self):
        # Closing the window minimises to tray (matches the original app).
        self.hide_window()

    # -- engine controls ------------------------------------------------------

    def set_paused(self, paused):
        self.engine.set_paused(paused)
        self._refresh_indicators()

    def toggle_paused(self):
        self.set_paused(not self.engine.paused)
        if self.window:
            self._ui(lambda: self.window.set_pause_state(self.engine.paused))

    def set_focus_mode(self, enabled):
        self.engine.set_focus_mode(enabled)
        self._refresh_indicators()

    def toggle_focus(self):
        self.set_focus_mode(not self.engine.focus_mode)
        if self.window:
            self._ui(lambda: self.window.set_focus_state(self.engine.focus_mode))

    def restore_all(self):
        self.engine.restore_all()

    def panic(self):
        self.engine.panic_restore()
        if self.window:
            self._ui(lambda: self.window.set_pause_state(True))
        self._refresh_indicators()

    def _nudge(self, delta):
        hwnd = winapi.get_foreground_window()
        if not hwnd or not winapi.is_app_window(hwnd):
            return
        current = self.engine.get_override(hwnd)
        if current is None:
            current = winapi.get_window_alpha(hwnd) or 255
        self.engine.set_override(hwnd, max(20, min(255, current + delta)))

    def nudge_up(self):
        self._nudge(NUDGE_STEP)

    def nudge_down(self):
        self._nudge(-NUDGE_STEP)

    def _refresh_indicators(self):
        if self.tray:
            self.tray.refresh()

    # -- dimmer ---------------------------------------------------------------

    def set_dimmer_enabled(self, enabled):
        self.dimmer.set_enabled(enabled)
        if enabled:
            self._schedule_dimmer_tick()

    def set_dimmer_intensity(self, value):
        self.dimmer.set_intensity(value)

    def _schedule_dimmer_tick(self):
        # Keep the overlay topmost/sized; runs on the UI thread (which owns the
        # overlay's message pump). Stops rescheduling once the dimmer is off.
        if not self.dimmer.enabled or self.window is None:
            self._dimmer_tick_scheduled = False
            return
        self.dimmer.tick()
        self._dimmer_tick_scheduled = True
        self.window.after(2000, self._schedule_dimmer_tick)

    # -- hotkeys --------------------------------------------------------------

    def _register_hotkeys(self):
        defs = [hk.Hotkey(hid, mods, vk, getattr(self, method))
                for (_name, hid, mods, vk, method, _combo) in HOTKEY_DEFS]
        results = self.hotkeys.start(defs)
        failed = [name for (name, hid, *_rest) in HOTKEY_DEFS
                  if not results.get(hid, False)]
        if failed:
            log.warning("hotkeys unavailable (in use by another app): %s", failed)

    def set_hotkeys_enabled(self, enabled):
        self.config.set_setting("hotkeys_enabled", enabled)
        if enabled:
            self._register_hotkeys()
        else:
            self.hotkeys.stop()

    def hotkey_descriptions(self):
        return [(name, combo) for (name, _id, _m, _vk, _method, combo)
                in HOTKEY_DEFS]

    # -- startup / theme ------------------------------------------------------

    def is_startup_enabled(self):
        return startup.is_enabled()

    def set_startup(self, enabled):
        ok = startup.enable() if enabled else startup.disable()
        self.config.set_setting("start_minimized", enabled)
        return ok

    def apply_theme(self, mode):
        from .ui import theme
        theme.apply_appearance(mode)

    def quit(self):
        self._ui(self._quit_impl)

    def _quit_impl(self):
        try:
            self.window.destroy()
        except Exception:
            pass
