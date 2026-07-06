"""Global hotkeys via RegisterHotKey.

RegisterHotKey is thread-affine: WM_HOTKEY arrives on the thread that
registered the key, so this manager runs its own message-pump thread and
registers everything there. Callbacks fire on that thread — they should do
tiny work (enqueue into the engine, post to the UI thread).
"""

import ctypes
import ctypes.wintypes as wintypes
import threading

import win32con

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_UP = 0x26
VK_DOWN = 0x28
VK_HOME = 0x24


class Hotkey:
    def __init__(self, hotkey_id, modifiers, vk, callback, label=""):
        self.id = int(hotkey_id)
        self.modifiers = modifiers
        self.vk = vk
        self.callback = callback
        self.label = label


class HotkeyManager:
    """Registers a set of global hotkeys on a dedicated pump thread."""

    def __init__(self):
        self._hotkeys = {}
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._results = {}

    def start(self, hotkeys) -> dict:
        """Register hotkeys; returns {hotkey_id: bool registered}.

        A False value usually means another app owns that combination.
        """
        if self._thread is not None:
            self.stop()
        self._hotkeys = {hk.id: hk for hk in hotkeys}
        self._results = {}
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._pump, name="HotkeyManager", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return dict(self._results)

    def stop(self):
        if self._thread is None:
            return
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, win32con.WM_QUIT, 0, 0)
        self._thread.join(timeout=2)
        self._thread = None
        self._thread_id = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _pump(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        # Force-create the message queue before start() returns so stop()'s
        # PostThreadMessage(WM_QUIT) cannot be lost.
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None,
                            win32con.WM_USER, win32con.WM_USER, 0)
        for hk in self._hotkeys.values():
            ok = bool(user32.RegisterHotKey(
                None, hk.id, hk.modifiers | MOD_NOREPEAT, hk.vk))
            self._results[hk.id] = ok
        self._ready.set()
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == win32con.WM_HOTKEY:
                    hk = self._hotkeys.get(msg.wParam)
                    if hk is not None:
                        try:
                            hk.callback()
                        except Exception:
                            pass
        finally:
            for hk_id, ok in self._results.items():
                if ok:
                    user32.UnregisterHotKey(None, hk_id)
