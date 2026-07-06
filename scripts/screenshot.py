"""Render the app with sample rules and save a PNG of the window for docs.

Run on a real desktop (not the hidden sandbox) so the capture is real:
    .venv\\Scripts\\python.exe scripts/screenshot.py assets/screenshot.png
"""
import faulthandler
import os
import sys
import time

# Hard safety net: if anything hangs, kill the process after 10s so no
# unresponsive window is ever left on screen.
faulthandler.dump_traceback_later(10, exit=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transparency_app.config import (ConfigManager, MATCH_PROCESS,  # noqa: E402
                                     MATCH_TITLE)
from transparency_app.ui.app_window import AppWindow  # noqa: E402


class FakeEngine:
    paused = False
    focus_mode = False
    def affected_window_count(self): return 4
    def get_override(self, hwnd): return None


class FakeDimmer:
    enabled = False
    intensity = 120


class FakeController:
    def __init__(self, cfg):
        self.config = cfg
        self.engine = FakeEngine()
        self.dimmer = FakeDimmer()
        self.icon_path = None
    def on_close_request(self): pass
    def set_paused(self, p): pass
    def set_focus_mode(self, e): pass
    def set_dimmer_enabled(self, e): pass
    def set_dimmer_intensity(self, v): pass
    def restore_all(self): pass
    def is_startup_enabled(self): return True
    def set_startup(self, e): return True
    def set_hotkeys_enabled(self, e): pass
    def apply_theme(self, m): pass
    def hotkey_descriptions(self):
        return [("Toggle transparency", "Ctrl+Alt+T"),
                ("Toggle focus mode", "Ctrl+Alt+F"),
                ("More opaque", "Ctrl+Alt+↑"),
                ("More transparent", "Ctrl+Alt+↓"),
                ("Restore everything", "Ctrl+Alt+Home")]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/screenshot.png"
    cfg = ConfigManager(os.path.join(os.environ.get("TEMP", "."),
                                     "ta_shot_config.json"))
    for r in list(cfg.get_rules()):
        cfg.remove_rule(r.id)
    cfg.add_rule("Visual Studio Code", opacity=235, match_mode=MATCH_TITLE)
    cfg.add_rule("chrome.exe", opacity=210, match_mode=MATCH_PROCESS)
    cfg.add_rule("Spotify", opacity=180, match_mode=MATCH_TITLE)

    win = AppWindow(FakeController(cfg))
    win.geometry("960x680+120+80")
    # Force our window above everything else so the capture is only our UI
    # (and never whatever private content happens to be behind it).
    win.attributes("-topmost", True)
    win.deiconify()
    win.lift()
    win.focus_force()
    for _ in range(60):
        win.update()
        win.update_idletasks()
        time.sleep(0.03)

    try:
        from PIL import ImageGrab
        win.lift()
        win.update()
        time.sleep(0.3)
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        img.save(out)
        print("saved", out, img.size)
    finally:
        win.destroy()


if __name__ == "__main__":
    main()
