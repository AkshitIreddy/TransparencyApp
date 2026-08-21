"""Application controller: owns the config, engine, dimmer, hotkeys, tray and
main window, and is the single mediator between them.

Threading contract: Tk must only be touched from the main thread. Anything
arriving from another thread (hotkey pump, tray) is marshalled onto the Tk
loop with ``root.after``. The engine and config are internally thread-safe.
"""

import logging
import os
import sys
import threading

from . import hotkeys as hk
from . import paths, startup, updater, winapi
from .config import ConfigManager
from .dimmer import ScreenDimmer
from .engine import TransparencyEngine

log = logging.getLogger("transparency_app.app")

# (action key, name shown in UI, hotkey_id, default combo, controller method)
HOTKEY_DEFS = [
    ("toggle_transparency", "Toggle transparency", 1, "ctrl+alt+t",
     "toggle_paused"),
    ("toggle_focus", "Toggle focus mode", 2, "ctrl+alt+f", "toggle_focus"),
    ("nudge_up", "More opaque (active window)", 3, "ctrl+alt+up", "nudge_up"),
    ("nudge_down", "More transparent (active window)", 4, "ctrl+alt+down",
     "nudge_down"),
    ("panic", "Restore everything (panic)", 5, "ctrl+alt+home", "panic"),
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
        self.dimmer.set_intensity(self.config.get_setting("dimmer_intensity", 160))
        self.dimmer.set_intensities(
            self.config.get_setting("dimmer_intensities", {}))
        self.dimmer.set_monitors(self.config.get_setting("dimmer_monitors", "all"))
        self.hotkeys = hk.HotkeyManager()

        self.window = None
        self.tray = None
        self._dimmer_tick_id = None
        self.update_state = "idle"
        self.update_message = "Updates are checked automatically."
        self._update_info = None
        self._staged_update = None
        self._update_lock = threading.Lock()

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

        # Restore the toggles the user left on last session.
        if not self.config.get_setting("transparency_on", True):
            self.engine.set_paused(True)
        if self.config.get_setting("focus_mode", {}).get("enabled"):
            self.engine.set_focus_mode(True)

        self.window = AppWindow(self)
        self.tray = Tray(self, self.icon_path)
        self.tray.start()

        if self.config.get_setting("dimmer_enabled", False):
            # The overlay must be created on the UI thread once Tk is pumping.
            self.window.after(200, lambda: self._restore_dimmer())

        if self.config.get_setting("start_minimized", False):
            self.window.after(200, self.hide_window)

        if self.config.get_setting("check_updates_on_startup", True):
            self.window.after(1500, self.check_for_updates)

        try:
            self.window.mainloop()
        finally:
            self._shutdown()

    def self_test(self) -> bool:
        """Bring the app up without mainloop, exercise it, tear down. For CI."""
        from .ui.app_window import AppWindow
        try:
            self.engine.start()
            self.window = AppWindow(self)
            for page in ("rules", "focus", "dimmer", "settings"):
                self.window.show_page(page)
                self.window.update_idletasks()
                self.window.update()
            self.window.destroy()
            return True
        except Exception:
            log.exception("self-test failed")
            return False
        finally:
            try:
                self.engine.stop()
                self.config.close()
            except Exception:
                pass

    def _shutdown(self):
        log.info("shutting down")
        try:
            self.config.set_setting("dimmer_intensity", self.dimmer.intensity)
            self.config.set_setting("dimmer_intensities", self.dimmer.intensities)
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
        """Marshal fn onto the Tk main thread (safe to call from any thread).

        Never run fn synchronously as a fallback: Tk must only be touched on
        the main thread, so if the window is gone or the marshal fails, the
        call is simply dropped.
        """
        window = self.window
        if window is None:
            return
        try:
            window.after(0, fn)
        except Exception:
            pass

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
        self.config.set_setting("transparency_on", not paused)
        self._refresh_indicators()

    def toggle_paused(self):
        self.set_paused(not self.engine.paused)
        if self.window:
            self._ui(lambda: self.window.set_pause_state(self.engine.paused))

    def set_focus_mode(self, enabled):
        self.engine.set_focus_mode(enabled)
        self.config.set_setting("focus_mode", {"enabled": bool(enabled)})
        self._refresh_indicators()

    def toggle_focus(self):
        self.set_focus_mode(not self.engine.focus_mode)
        if self.window:
            self._ui(lambda: self.window.set_focus_state(self.engine.focus_mode))

    def restore_all(self):
        self.engine.restore_all()

    def panic(self):
        self.engine.panic_restore()
        self.config.set_setting("transparency_on", False)
        self.config.set_setting("focus_mode", {"enabled": False})
        if self.window:
            self._ui(lambda: self.window.set_pause_state(True))
            self._ui(lambda: self.window.set_focus_state(False))
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
        self.config.set_setting("dimmer_enabled", bool(enabled))
        if enabled:
            self._schedule_dimmer_tick()
        else:
            self._cancel_dimmer_tick()

    def set_dimmer_intensity(self, value):
        self.dimmer.set_intensity(value)
        self.config.set_setting("dimmer_intensity", self.dimmer.intensity)

    def set_monitor_dimmer_intensity(self, monitor_name, value):
        self.dimmer.set_monitor_intensity(monitor_name, value)
        self.config.set_setting("dimmer_intensities", self.dimmer.intensities)

    def set_dimmer_monitors(self, value):
        self.dimmer.set_monitors(value)
        self.config.set_setting("dimmer_monitors", value)

    def _restore_dimmer(self):
        """Re-enable the dimmer saved from last session (UI thread only)."""
        self.dimmer.set_enabled(True)
        self._schedule_dimmer_tick()
        if self.window:
            self.window.set_dimmer_state(True)

    def _cancel_dimmer_tick(self):
        if self._dimmer_tick_id is not None and self.window is not None:
            try:
                self.window.after_cancel(self._dimmer_tick_id)
            except Exception:
                pass
        self._dimmer_tick_id = None

    def _schedule_dimmer_tick(self):
        # Keep the overlay topmost/sized; runs on the UI thread (which owns the
        # overlay's message pump). Exactly one tick chain runs at a time —
        # cancelling any pending one first prevents rapid off/on from stacking
        # overlapping loops.
        self._cancel_dimmer_tick()
        if not self.dimmer.enabled or self.window is None:
            return
        self.dimmer.tick()
        self._dimmer_tick_id = self.window.after(2000, self._schedule_dimmer_tick)

    # -- hotkeys --------------------------------------------------------------

    def _hotkey_combo(self, action, default):
        """The active combo string for an action (saved override or default)."""
        combo = self.config.get_setting("hotkeys", {}).get(action, default)
        return combo if hk.parse_combo(combo) else default

    def _register_hotkeys(self):
        defs = []
        for action, _name, hid, default, method in HOTKEY_DEFS:
            mods, vk = hk.parse_combo(self._hotkey_combo(action, default))
            defs.append(hk.Hotkey(hid, mods, vk, getattr(self, method)))
        results = self.hotkeys.start(defs)
        failed = [name for (_a, name, hid, *_rest) in HOTKEY_DEFS
                  if not results.get(hid, False)]
        if failed:
            log.warning("hotkeys unavailable (in use by another app): %s", failed)
        return results

    def set_hotkeys_enabled(self, enabled):
        self.config.set_setting("hotkeys_enabled", enabled)
        if enabled:
            self._register_hotkeys()
        else:
            self.hotkeys.stop()

    def hotkey_descriptions(self):
        """[(action, name, active combo string)] for the settings page."""
        return [(action, name, self._hotkey_combo(action, default))
                for (action, name, _id, default, _m) in HOTKEY_DEFS]

    def set_hotkey_binding(self, action, combo):
        """Rebind one action. Returns (ok, message). Re-registers live."""
        if hk.parse_combo(combo) is None:
            return False, "That key combination can't be used."
        taken = [a for (a, _n, _i, d, _m) in HOTKEY_DEFS
                 if a != action and hk.parse_combo(self._hotkey_combo(a, d))
                 == hk.parse_combo(combo)]
        if taken:
            return False, "Already used by another shortcut."
        bindings = self.config.get_setting("hotkeys", {})
        bindings[action] = str(combo).strip().lower()
        self.config.set_setting("hotkeys", bindings)
        if self.config.get_setting("hotkeys_enabled", True):
            results = self._register_hotkeys()
            hid = next(i for (a, _n, i, _d, _m) in HOTKEY_DEFS if a == action)
            if not results.get(hid, False):
                return False, "Another app already uses that combination."
        return True, ""

    def reset_hotkey_bindings(self):
        self.config.set_setting("hotkeys", {})
        if self.config.get_setting("hotkeys_enabled", True):
            self._register_hotkeys()

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

    # -- updates -------------------------------------------------------------

    def set_update_checks_enabled(self, enabled):
        self.config.set_setting("check_updates_on_startup", bool(enabled))

    def _set_update_state(self, state, message):
        self.update_state = state
        self.update_message = message
        if self.window:
            self._ui(lambda: self.window.set_update_state(state, message))
        if self.tray:
            self.tray.refresh()

    def check_for_updates(self, manual=False):
        if not self._update_lock.acquire(blocking=False):
            return
        self._set_update_state("checking", "Checking GitHub Releases…")

        def worker():
            try:
                release = updater.check_for_update()
                if release is None:
                    self._set_update_state("current", "You're up to date.")
                    return
                self._update_info = release
                self._set_update_state(
                    "downloading", f"Downloading v{release.version}…")
                destination = updater.staged_update_path(release.version)

                def progress(done, total):
                    percent = round(done / total * 100) if total else 0
                    self._set_update_state(
                        "downloading",
                        f"Downloading v{release.version}… {percent}%")

                self._staged_update = updater.download_update(
                    release, destination, progress=progress)
                self._set_update_state(
                    "ready", f"v{release.version} is ready to install.")
                if self.tray:
                    self.tray.notify_update(release.version)
                if manual and self.window:
                    self._ui(lambda: self.window.offer_update(release.version))
            except updater.UpdateError as exc:
                log.warning("update check failed: %s", exc)
                message = (str(exc) if manual else
                           "Automatic update check failed. Try again later.")
                self._set_update_state("error", message)
            finally:
                self._update_lock.release()

        threading.Thread(target=worker, name="AppUpdater", daemon=True).start()

    def install_ready_update(self):
        if not self._staged_update or not self._update_info:
            self.check_for_updates(manual=True)
            return
        if not getattr(sys, "frozen", False):
            self._set_update_state(
                "error", "Updates can only install from the packaged app.")
            return
        try:
            updater.launch_installer(
                self._staged_update, os.path.abspath(sys.executable))
        except updater.UpdateError as exc:
            self._set_update_state("error", str(exc))
            return
        self._set_update_state("installing", "Restarting to finish the update…")
        if self.window:
            self.window.after(150, self._quit_impl)

    def request_install_update(self):
        """Marshal a tray-menu install request onto Tk's UI thread."""
        self._ui(self.install_ready_update)

    def quit(self):
        self._ui(self._quit_impl)

    def _quit_impl(self):
        try:
            self.window.destroy()
        except Exception:
            pass
