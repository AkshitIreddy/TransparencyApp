"""Thin, dependency-light wrappers around the Win32 calls the app needs.

Everything here works on plain HWNDs and is safe to call from any thread.
The WinEventHook class owns its own message-pump thread because
SetWinEventHook delivers events only to the thread that installed the hook.

Window-attribute calls (get/set style, text, class, position) go through
ctypes rather than pywin32. This is deliberate: pywin32 holds the GIL while a
call blocks, so a slow or cross-thread call would freeze every thread in the
app; the ctypes equivalents release the GIL, so the engine worker can never
lock up the UI thread (or vice-versa).
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import threading
from dataclasses import dataclass

import win32api
import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64-bit-correct signatures for the pointer-returning style calls.
if ctypes.sizeof(ctypes.c_void_p) == 8:
    _GetWindowLong = user32.GetWindowLongPtrW
    _SetWindowLong = user32.SetWindowLongPtrW
    _LONG_PTR = ctypes.c_longlong
else:
    _GetWindowLong = user32.GetWindowLongW
    _SetWindowLong = user32.SetWindowLongW
    _LONG_PTR = ctypes.c_long
_GetWindowLong.restype = _LONG_PTR
_GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
_SetWindowLong.restype = _LONG_PTR
_SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]

for _fn in (user32.IsWindow, user32.IsWindowVisible):
    _fn.restype = wintypes.BOOL
    _fn.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.SetWindowPos.restype = wintypes.BOOL


def _get_long(hwnd, index):
    return int(_GetWindowLong(wintypes.HWND(hwnd), index))


def _set_long(hwnd, index, value):
    return int(_SetWindowLong(wintypes.HWND(hwnd), index, value))

# --- Win32 constants not exposed by win32con -------------------------------
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_UNCLOAKED = 0x8018
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
CHILDID_SELF = 0
LWA_ALPHA = win32con.LWA_ALPHA

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_CLOAKED = 14

WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,  # hWinEventHook
    wintypes.DWORD,   # event
    wintypes.HWND,    # hwnd
    wintypes.LONG,    # idObject
    wintypes.LONG,    # idChild
    wintypes.DWORD,   # idEventThread
    wintypes.DWORD,   # dwmsEventTime
)

# Explicit signatures: without these, 64-bit handles get truncated to c_int.
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WinEventProcType,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
user32.UnhookWinEvent.restype = wintypes.BOOL
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]

# If a pump thread ever fails to shut down, its ctypes callback must stay
# alive for the life of the process — a registered hook calling into a
# collected thunk is a hard crash.
_pinned_callbacks = []


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    process: str  # executable base name, lowercase, e.g. "code.exe"


# --- basic window queries ---------------------------------------------------

def is_window(hwnd) -> bool:
    try:
        return bool(user32.IsWindow(wintypes.HWND(hwnd)))
    except Exception:
        return False


def get_window_title(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 512)
        return buf.value
    except Exception:
        return ""


def get_window_class(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
        return buf.value
    except Exception:
        return ""


def get_window_pid(hwnd) -> int:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return 0


_process_name_cache: dict[int, str] = {}
_process_cache_lock = threading.Lock()


def get_process_name(pid: int) -> str:
    """Executable base name for a pid ("code.exe"), lowercase. Cached."""
    if not pid:
        return ""
    with _process_cache_lock:
        cached = _process_name_cache.get(pid)
    if cached is not None:
        return cached
    name = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            buf_len = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(buf_len.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
                name = os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(handle)
    with _process_cache_lock:
        # Pids get reused; keep the cache small so stale entries wash out.
        if len(_process_name_cache) > 512:
            _process_name_cache.clear()
        _process_name_cache[pid] = name
    return name


def get_window_info(hwnd) -> WindowInfo:
    pid = get_window_pid(hwnd)
    return WindowInfo(
        hwnd=hwnd,
        title=get_window_title(hwnd),
        class_name=get_window_class(hwnd),
        pid=pid,
        process=get_process_name(pid),
    )


def is_cloaked(hwnd) -> bool:
    """DWM-cloaked windows (suspended UWP frames) look open but are not
    visible; applying alpha to them affects ghost windows."""
    try:
        cloaked = wintypes.DWORD(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_CLOAKED,
            ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return bool(cloaked.value)
    except Exception:
        return False


# Shell/system windows that must never be dimmed or made transparent.
_EXCLUDED_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
    "TransparencyAppDimmer",
}
_EXCLUDED_TITLES = {"Windows Input Experience", "Program Manager"}


def is_app_window(hwnd) -> bool:
    """A window a user would recognize: visible, titled, not a tool window,
    and not part of the Windows shell."""
    try:
        chwnd = wintypes.HWND(hwnd)
        if not user32.IsWindow(chwnd) or not user32.IsWindowVisible(chwnd):
            return False
        if _get_long(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return False
        title = get_window_title(hwnd)
        if not title or title in _EXCLUDED_TITLES:
            return False
        if get_window_class(hwnd) in _EXCLUDED_CLASSES:
            return False
        return not is_cloaked(hwnd)
    except Exception:
        return False


def get_window_exstyle(hwnd) -> int:
    try:
        return _get_long(hwnd, win32con.GWL_EXSTYLE)
    except Exception:
        return 0


def enum_app_windows() -> list:
    """All current top-level app windows as WindowInfo, minimized included."""
    found = []

    def _cb(hwnd, _):
        if is_app_window(hwnd):
            found.append(get_window_info(hwnd))
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found


def get_foreground_window() -> int:
    try:
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


# --- transparency / styles ---------------------------------------------------

def set_window_alpha(hwnd, alpha: int) -> bool:
    """Set layered alpha (0..255) on a window. Returns True on success."""
    alpha = max(0, min(255, int(alpha)))
    try:
        if not is_window(hwnd):
            return False
        style = _get_long(hwnd, win32con.GWL_EXSTYLE)
        if not style & win32con.WS_EX_LAYERED:
            _set_long(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
        return bool(user32.SetLayeredWindowAttributes(
            wintypes.HWND(hwnd), 0, alpha, LWA_ALPHA))
    except Exception:
        return False


def get_window_alpha(hwnd):
    """Current layered alpha, or None if the window is not layered."""
    try:
        style = _get_long(hwnd, win32con.GWL_EXSTYLE)
        if not style & win32con.WS_EX_LAYERED:
            return None
        alpha = ctypes.c_ubyte()
        flags = wintypes.DWORD()
        ok = user32.GetLayeredWindowAttributes(
            wintypes.HWND(hwnd), None, ctypes.byref(alpha), ctypes.byref(flags)
        )
        if ok and flags.value & LWA_ALPHA:
            return alpha.value
        return None
    except Exception:
        return None


def restore_window(hwnd, had_layered=False, prev_alpha=None) -> bool:
    """Return a window to how it was before we touched it.

    Windows that were layered on their own get their previous alpha back and
    keep WS_EX_LAYERED; everything else goes back to opaque non-layered.
    """
    try:
        if not is_window(hwnd):
            return False
        if had_layered:
            return set_window_alpha(
                hwnd, prev_alpha if prev_alpha is not None else 255)
        set_window_alpha(hwnd, 255)
        style = _get_long(hwnd, win32con.GWL_EXSTYLE)
        if style & win32con.WS_EX_LAYERED:
            _set_long(hwnd, win32con.GWL_EXSTYLE,
                      style & ~win32con.WS_EX_LAYERED)
        return True
    except Exception:
        return False


def set_click_through(hwnd, enabled: bool) -> bool:
    """Make a window ignore mouse input (WS_EX_TRANSPARENT).

    Requires the window to be layered; callers should have applied an alpha
    already (a fully opaque click-through window is confusing, so the UI ties
    this to transparency rules).
    """
    try:
        if not is_window(hwnd):
            return False
        style = _get_long(hwnd, win32con.GWL_EXSTYLE)
        if enabled:
            style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
        else:
            style &= ~win32con.WS_EX_TRANSPARENT
        _set_long(hwnd, win32con.GWL_EXSTYLE, style)
        return True
    except Exception:
        return False


def is_click_through(hwnd) -> bool:
    try:
        return bool(_get_long(hwnd, win32con.GWL_EXSTYLE)
                    & win32con.WS_EX_TRANSPARENT)
    except Exception:
        return False


def set_topmost(hwnd, enabled: bool) -> bool:
    try:
        if not is_window(hwnd):
            return False
        flag = win32con.HWND_TOPMOST if enabled else win32con.HWND_NOTOPMOST
        return bool(user32.SetWindowPos(
            wintypes.HWND(hwnd), wintypes.HWND(flag), 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE))
    except Exception:
        return False


def is_topmost(hwnd) -> bool:
    try:
        return bool(_get_long(hwnd, win32con.GWL_EXSTYLE)
                    & win32con.WS_EX_TOPMOST)
    except Exception:
        return False


# --- event hook --------------------------------------------------------------

class WinEventHook:
    """Delivers window lifecycle events (created/shown/renamed/focused) to a
    callback, replacing the old poll-everything-every-100ms loop.

    The callback runs on the hook's message-pump thread and must be fast:
    push into a queue and return. Events already filtered to real top-level
    windows (idObject == OBJID_WINDOW, idChild == CHILDID_SELF).
    """

    _EVENTS = (
        EVENT_SYSTEM_FOREGROUND,
        EVENT_OBJECT_CREATE,
        EVENT_OBJECT_DESTROY,
        EVENT_OBJECT_SHOW,
        EVENT_OBJECT_NAMECHANGE,
        EVENT_OBJECT_UNCLOAKED,
    )

    def __init__(self, callback, skip_own_process=True):
        self._callback = callback
        self._flags = WINEVENT_OUTOFCONTEXT
        if skip_own_process:
            self._flags |= WINEVENT_SKIPOWNPROCESS
        self._hooks = []
        self._thread = None
        self._thread_id = None
        self._started = threading.Event()
        # Keep a reference so the ctypes callback isn't garbage collected.
        self._proc = WinEventProcType(self._on_event)

    def _on_event(self, hook, event, hwnd, id_object, id_child, thread_id, event_time):
        if id_object != OBJID_WINDOW or id_child != CHILDID_SELF or not hwnd:
            return
        try:
            self._callback(event, hwnd)
        except Exception:
            pass

    def _pump(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Force-create this thread's message queue BEFORE start() returns,
        # otherwise stop()'s PostThreadMessage(WM_QUIT) can be silently lost
        # and the thread (with live hooks) outlives the object owning the
        # ctypes callback — a native crash on the next event.
        user32.PeekMessageW(ctypes.byref(msg), None,
                            win32con.WM_USER, win32con.WM_USER, 0)
        for ev in self._EVENTS:
            hook = user32.SetWinEventHook(
                ev, ev, None, self._proc, 0, 0, self._flags,
            )
            if hook:
                self._hooks.append(hook)
        self._started.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hook in self._hooks:
            user32.UnhookWinEvent(hook)
        self._hooks.clear()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._pump, name="WinEventHook", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5)

    def stop(self):
        if self._thread is None:
            return
        thread = self._thread
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, win32con.WM_QUIT, 0, 0)
        thread.join(timeout=3)
        if thread.is_alive():
            # The pump refused to die; keep the callback alive forever so the
            # still-registered hooks never call into freed memory.
            _pinned_callbacks.append(self._proc)
        self._thread = None
        self._thread_id = None
        self._started.clear()

    @property
    def active(self) -> bool:
        return bool(self._hooks)


def get_screen_size() -> tuple:
    return (
        win32api.GetSystemMetrics(win32con.SM_CXSCREEN),
        win32api.GetSystemMetrics(win32con.SM_CYSCREEN),
    )


def get_virtual_screen_rect() -> tuple:
    """(x, y, width, height) of the full virtual desktop across monitors."""
    return (
        win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN),
    )
