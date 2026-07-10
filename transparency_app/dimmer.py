"""Click-through screen dimming overlay.

A black layered WS_POPUP window covering the whole virtual desktop (all
monitors — the old version only covered the primary). It is click-through
(WS_EX_TRANSPARENT), never takes focus, and leaves a small gap at an
auto-hiding taskbar's edge so the taskbar can still be summoned.

Create and drive it from the UI thread: tkinter's mainloop pumps this
thread's messages, which keeps the overlay window responsive.
"""

import ctypes
import ctypes.wintypes as wintypes

import win32api
import win32con
import win32gui

from . import winapi

ABM_GETSTATE = 0x00000004
ABM_GETTASKBARPOS = 0x00000005
ABS_AUTOHIDE = 0x0000001
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3

MAX_DIM_ALPHA = 200  # never allow a full blackout
_TASKBAR_GAP_PX = 2

_WINDOW_CLASS = "TransparencyAppDimmer"
_class_registered = False


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


def _get_taskbar_state():
    """(edge, is_auto_hide) of the primary taskbar."""
    try:
        abd = _APPBARDATA()
        abd.cbSize = ctypes.sizeof(_APPBARDATA)
        state = ctypes.windll.shell32.SHAppBarMessage(
            ABM_GETSTATE, ctypes.byref(abd))
        is_auto_hide = bool(state & ABS_AUTOHIDE)

        abd2 = _APPBARDATA()
        abd2.cbSize = ctypes.sizeof(_APPBARDATA)
        ctypes.windll.shell32.SHAppBarMessage(
            ABM_GETTASKBARPOS, ctypes.byref(abd2))
        return abd2.uEdge, is_auto_hide
    except Exception:
        return ABE_BOTTOM, False


class ScreenDimmer:
    def __init__(self):
        self._hwnd = None
        self._intensity = 160  # 0..MAX_DIM_ALPHA
        self.enabled = False

    @property
    def intensity(self) -> int:
        return self._intensity

    def _register_class(self):
        global _class_registered
        if _class_registered:
            return
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = lambda h, m, w, l: win32gui.DefWindowProc(h, m, w, l)
        wc.lpszClassName = _WINDOW_CLASS
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass  # already registered
        _class_registered = True

    def _overlay_rect(self):
        x, y, width, height = winapi.get_virtual_screen_rect()
        edge, auto_hide = _get_taskbar_state()
        if auto_hide:
            if edge == ABE_BOTTOM:
                height -= _TASKBAR_GAP_PX
            elif edge == ABE_TOP:
                y += _TASKBAR_GAP_PX
                height -= _TASKBAR_GAP_PX
            elif edge == ABE_LEFT:
                x += _TASKBAR_GAP_PX
                width -= _TASKBAR_GAP_PX
            elif edge == ABE_RIGHT:
                width -= _TASKBAR_GAP_PX
        return x, y, width, height

    def _create(self):
        self._register_class()
        x, y, width, height = self._overlay_rect()
        ex_style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
                    | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE
                    | win32con.WS_EX_TOOLWINDOW)
        hwnd = win32gui.CreateWindowEx(
            ex_style, _WINDOW_CLASS, "Screen Dimming Overlay",
            win32con.WS_POPUP, x, y, width, height,
            0, 0, win32api.GetModuleHandle(None), None)
        if not hwnd:
            return None
        ctypes.windll.user32.SetLayeredWindowAttributes(
            hwnd, 0, self._alpha(), win32con.LWA_ALPHA)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, x, y, width, height,
            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        return hwnd

    def _alpha(self) -> int:
        return max(0, min(MAX_DIM_ALPHA, self._intensity))

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        if self.enabled:
            if self._hwnd is None or not win32gui.IsWindow(self._hwnd):
                self._hwnd = self._create()
            elif self._hwnd:
                win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNA)
                self._reassert()
        elif self._hwnd and win32gui.IsWindow(self._hwnd):
            win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)

    def set_intensity(self, value: int):
        self._intensity = max(0, min(MAX_DIM_ALPHA, int(value)))
        if self.enabled and self._hwnd and win32gui.IsWindow(self._hwnd):
            ctypes.windll.user32.SetLayeredWindowAttributes(
                self._hwnd, 0, self._alpha(), win32con.LWA_ALPHA)

    def _reassert(self):
        x, y, width, height = self._overlay_rect()
        win32gui.SetWindowPos(
            self._hwnd, win32con.HWND_TOPMOST, x, y, width, height,
            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        ctypes.windll.user32.SetLayeredWindowAttributes(
            self._hwnd, 0, self._alpha(), win32con.LWA_ALPHA)

    def tick(self):
        """Call periodically (e.g. every 2 s from the UI) while enabled to
        keep the overlay topmost and sized to the current desktop."""
        if not self.enabled:
            return
        if self._hwnd is None or not win32gui.IsWindow(self._hwnd):
            self._hwnd = self._create()
        else:
            self._reassert()

    def destroy(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            try:
                win32gui.DestroyWindow(self._hwnd)
            except win32gui.error:
                pass
        self._hwnd = None
        self.enabled = False
