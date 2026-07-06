"""System-tray icon. Runs pystray detached on its own thread; menu actions
marshal back onto the Tk main thread via the controller."""

import threading

import pystray
from PIL import Image, ImageDraw

from . import winapi


def _fallback_icon():
    """A simple half-filled circle, drawn if the packaged icon is missing."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), outline=(91, 140, 255, 255), width=4)
    d.pieslice((6, 6, 58, 58), 90, 270, fill=(91, 140, 255, 255))
    return img


class Tray:
    def __init__(self, controller, icon_path=None):
        self.controller = controller
        try:
            self._image = Image.open(icon_path) if icon_path else _fallback_icon()
        except Exception:
            self._image = _fallback_icon()
        self._icon = None
        self._thread = None

    def _menu(self):
        paused = self.controller.engine.paused
        focus = self.controller.engine.focus_mode
        return pystray.Menu(
            pystray.MenuItem("Show window", lambda: self.controller.show_window(),
                             default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Transparency active", lambda: self.controller.toggle_paused(),
                checked=lambda _i: not paused),
            pystray.MenuItem(
                "Focus mode", lambda: self.controller.toggle_focus(),
                checked=lambda _i: focus),
            pystray.MenuItem("Restore all windows",
                             lambda: self.controller.restore_all()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.controller.quit()),
        )

    def start(self):
        self._icon = pystray.Icon(
            "TransparencyApp", self._image, "Transparency App", self._menu())
        self._thread = threading.Thread(
            target=self._icon.run, name="Tray", daemon=True)
        self._thread.start()

    def refresh(self):
        if self._icon is not None:
            try:
                self._icon.menu = self._menu()
                self._icon.update_menu()
            except Exception:
                pass

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
