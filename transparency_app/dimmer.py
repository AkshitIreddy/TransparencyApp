"""Click-through screen dimming overlay.

One black layered WS_POPUP window per covered monitor. Each is click-through
(WS_EX_TRANSPARENT), never takes focus, and leaves a small gap at an
auto-hiding taskbar's edge so the taskbar can still be summoned. The user
can dim every monitor ("all") or only a chosen subset.

Create and drive it from the UI thread: tkinter's mainloop pumps this
thread's messages, which keeps the overlay windows responsive.
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sys

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

# Windows 10 version 2004 introduced a capture affinity that removes a window
# from screenshots while leaving it visible on the physical display. On older
# Windows builds the same value degrades to WDA_MONITOR, which would replace the
# overlay with a black rectangle in captures, so do not apply it there.
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_NONE = 0x00000000
_CAPTURE_EXCLUSION_MIN_BUILD = 19041

_SetWindowDisplayAffinity = ctypes.windll.user32.SetWindowDisplayAffinity
_SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_SetWindowDisplayAffinity.restype = wintypes.BOOL

_WINDOW_CLASS = "TransparencyAppDimmer"
_WM_SHELL_CHANGED = win32con.WM_APP + 1
_class_registered = False
_overlay_owners = {}

_TASKBAR_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
_CAPTURE_PROCESSES = {"screenclippinghost.exe"}
_SNIPPING_PROCESS = "snippingtool.exe"


def _overlay_wnd_proc(hwnd, message, wparam, lparam):
    """Run shell/capture reconciliation on the overlay's UI thread."""
    if message == _WM_SHELL_CHANGED:
        owner = _overlay_owners.get(hwnd)
        if owner is not None:
            owner._handle_shell_change_ui()
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


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
    """(edge, is_auto_hide, rect) of the primary taskbar; rect may be None."""
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
        rc = abd2.rc
        return abd2.uEdge, is_auto_hide, (rc.left, rc.top, rc.right, rc.bottom)
    except Exception:
        return ABE_BOTTOM, False, None


def _rect_contains(rect, point):
    x, y, w, h = rect
    px, py = point
    return x <= px < x + w and y <= py < y + h


def _capture_exclusion_supported():
    """Whether WDA_EXCLUDEFROMCAPTURE has its transparent capture behavior."""
    try:
        version = sys.getwindowsversion()
        return (version.major > 10 or
                (version.major == 10 and
                 version.build >= _CAPTURE_EXCLUSION_MIN_BUILD))
    except (AttributeError, OSError):
        return False


def _set_capture_excluded(hwnd, excluded):
    """Toggle screenshot exclusion without changing local display output."""
    if not hwnd:
        return False
    if excluded and not _capture_exclusion_supported():
        return False
    try:
        return bool(_SetWindowDisplayAffinity(
            wintypes.HWND(hwnd),
            WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE))
    except (AttributeError, OSError, ValueError):
        return False


def _is_capture_surface(process, class_name, title, rect, virtual_rect):
    """Identify only transient Windows capture surfaces, not the editor UI."""
    process = (process or "").lower()
    class_name = (class_name or "").lower()
    title = (title or "").lower()
    if process in _CAPTURE_PROCESSES:
        return True
    if process != _SNIPPING_PROCESS:
        return False
    if "capture" in class_name or "snipper" in class_name:
        return True
    x, y, width, height = virtual_rect
    left, top, right, bottom = rect
    area = max(0, right - left) * max(0, bottom - top)
    desktop_area = max(1, width * height)
    return (area >= desktop_area * 0.45 and
            title not in {"snipping tool", "snipping tool settings"})


class ScreenDimmer:
    def __init__(self, taskbar_ledger_path=None):
        self._overlays = {}     # monitor device name -> overlay hwnd
        self._intensity = 160   # fallback for newly connected monitors
        self._intensities = {}  # monitor device name -> 0..MAX_DIM_ALPHA
        self.enabled = False
        self._monitors = "all"  # "all", or a list of monitor device names
        self._capture_active = False
        self._taskbars = {}  # taskbar hwnd -> original style + black backdrop
        self._taskbar_ledger_path = taskbar_ledger_path
        self._recover_taskbars()
        self._z_order_hook = winapi.WinEventHook(
            self._on_shell_event,
            events=(
                winapi.EVENT_SYSTEM_FOREGROUND,
                winapi.EVENT_OBJECT_CREATE,
                winapi.EVENT_OBJECT_DESTROY,
                winapi.EVENT_OBJECT_SHOW,
                winapi.EVENT_OBJECT_REORDER,
                winapi.EVENT_OBJECT_LOCATIONCHANGE,
                winapi.EVENT_OBJECT_UNCLOAKED,
            ))

    @property
    def intensity(self) -> int:
        return self._intensity

    @property
    def monitors(self):
        return self._monitors

    @property
    def intensities(self):
        return dict(self._intensities)

    def intensity_for(self, monitor_name) -> int:
        return self._intensities.get(str(monitor_name), self._intensity)

    def set_intensities(self, value):
        """Set remembered per-monitor levels, preserving the global fallback."""
        if isinstance(value, dict):
            self._intensities = {
                str(name): max(0, min(MAX_DIM_ALPHA, int(intensity)))
                for name, intensity in value.items()
                if str(name).strip()
            }
        else:
            self._intensities = {}
        if self.enabled:
            self._rebuild()

    def set_monitor_intensity(self, monitor_name, value):
        name = str(monitor_name)
        if not name:
            return
        self._intensities[name] = max(0, min(MAX_DIM_ALPHA, int(value)))
        hwnd = self._overlays.get(name)
        if self.enabled and hwnd and win32gui.IsWindow(hwnd):
            ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, 0, self._alpha(name), win32con.LWA_ALPHA)
            self._sync_taskbars()

    def set_monitors(self, value):
        """Choose coverage: "all", or a list of monitor device names."""
        if value == "all":
            self._monitors = "all"
        elif isinstance(value, (list, tuple)):
            self._monitors = [str(v) for v in value]
        else:
            self._monitors = "all"
        if self.enabled:
            self._rebuild()

    def _register_class(self):
        global _class_registered
        if _class_registered:
            return
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = _overlay_wnd_proc
        wc.lpszClassName = _WINDOW_CLASS
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass  # already registered
        _class_registered = True

    def _target_monitors(self):
        """Monitor dicts to cover. A stale non-empty selection that now
        matches nothing (e.g. a monitor was unplugged) falls back to all, so
        the dimmer is never silently doing nothing while switched on."""
        mons = winapi.enum_monitors()
        if self._monitors == "all":
            return mons
        selected = [m for m in mons if m["name"] in self._monitors]
        if not selected and self._monitors:
            return mons
        return selected

    def _overlay_rects(self, monitors):
        """{name: (x, y, w, h)}, with the auto-hide taskbar gap applied only
        to the monitor that actually holds the taskbar."""
        edge, auto_hide, tb = _get_taskbar_state()
        tb_center = (((tb[0] + tb[2]) // 2, (tb[1] + tb[3]) // 2)
                     if tb else None)
        rects = {}
        for m in monitors:
            x, y, w, h = m["rect"]
            if auto_hide and tb_center and _rect_contains(m["rect"], tb_center):
                if edge == ABE_BOTTOM:
                    h -= _TASKBAR_GAP_PX
                elif edge == ABE_TOP:
                    y += _TASKBAR_GAP_PX
                    h -= _TASKBAR_GAP_PX
                elif edge == ABE_LEFT:
                    x += _TASKBAR_GAP_PX
                    w -= _TASKBAR_GAP_PX
                elif edge == ABE_RIGHT:
                    w -= _TASKBAR_GAP_PX
            rects[m["name"]] = (x, y, w, h)
        return rects

    def _alpha(self, monitor_name=None) -> int:
        value = (self.intensity_for(monitor_name)
                 if monitor_name is not None else self._intensity)
        return max(0, min(MAX_DIM_ALPHA, value))

    def _create(self, monitor_name, rect):
        self._register_class()
        x, y, width, height = rect
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
            hwnd, 0, self._alpha(monitor_name), win32con.LWA_ALPHA)
        _set_capture_excluded(hwnd, self._capture_active)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, x, y, width, height,
            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        _overlay_owners[hwnd] = self
        return hwnd

    def _reassert(self, monitor_name, hwnd, rect):
        x, y, width, height = rect
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, x, y, width, height,
            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        ctypes.windll.user32.SetLayeredWindowAttributes(
            hwnd, 0, self._alpha(monitor_name), win32con.LWA_ALPHA)
        _set_capture_excluded(hwnd, self._capture_active)

    def _on_shell_event(self, _event, _hwnd):
        """Coalesce foreign shell changes onto the dimmer's UI thread."""
        if not self.enabled:
            return
        overlay = next((hwnd for hwnd in tuple(self._overlays.values())
                        if hwnd and win32gui.IsWindow(hwnd)), None)
        if overlay:
            try:
                win32gui.PostMessage(overlay, _WM_SHELL_CHANGED, 0, 0)
            except win32gui.error:
                pass

    def _handle_shell_change_ui(self):
        if not self.enabled:
            return
        self._set_capture_active(self._capture_ui_active())
        self._rebuild()

    def _capture_ui_active(self):
        virtual_rect = winapi.get_virtual_screen_rect()
        active = False

        def callback(hwnd, _):
            nonlocal active
            if active or not win32gui.IsWindowVisible(hwnd):
                return not active
            try:
                rect = win32gui.GetWindowRect(hwnd)
                info = winapi.get_window_info(hwnd)
                active = _is_capture_surface(
                    info.process, info.class_name, info.title,
                    rect, virtual_rect)
            except Exception:
                pass
            return not active

        try:
            win32gui.EnumWindows(callback, None)
        except win32gui.error:
            pass
        return active

    def _set_capture_active(self, active):
        active = bool(active)
        if active == self._capture_active:
            return
        self._capture_active = active
        for hwnd in self._overlays.values():
            if hwnd and win32gui.IsWindow(hwnd):
                _set_capture_excluded(hwnd, active)
        self._sync_taskbars()

    def _taskbar_targets(self):
        """Visible Windows taskbars on monitors currently selected for dimming."""
        selected = {monitor["name"] for monitor in self._target_monitors()}
        found = {}
        for class_name in _TASKBAR_CLASSES:
            after = 0
            while True:
                try:
                    hwnd = win32gui.FindWindowEx(
                        0, after, class_name, None)
                except win32gui.error:
                    break
                if not hwnd:
                    break
                after = hwnd
                try:
                    monitor = win32api.MonitorFromWindow(
                        hwnd, win32con.MONITOR_DEFAULTTONEAREST)
                    info = win32api.GetMonitorInfo(monitor)
                    name = info.get("Device", "")
                    if name in selected:
                        found[hwnd] = (name, win32gui.GetWindowRect(hwnd))
                except Exception:
                    pass
        return found

    def _new_taskbar_state(self, hwnd, monitor_name):
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        had_layered = bool(ex_style & win32con.WS_EX_LAYERED)
        previous_alpha = winapi.get_window_alpha(hwnd)
        # Do not overwrite a taskbar's own non-alpha layered composition.
        if had_layered and previous_alpha is None:
            return None
        return {
            "monitor": monitor_name,
            "had_layered": had_layered,
            "previous_alpha": previous_alpha,
            "backdrop": None,
            "applied": False,
            "rect": None,
        }

    def _write_taskbar_ledger(self):
        if not self._taskbar_ledger_path:
            return
        rows = []
        for hwnd, state in self._taskbars.items():
            if state.get("applied") and win32gui.IsWindow(hwnd):
                rows.append({
                    "hwnd": int(hwnd),
                    "pid": winapi.get_window_pid(hwnd),
                    "had_layered": bool(state["had_layered"]),
                    "previous_alpha": state["previous_alpha"],
                })
        try:
            if not rows:
                os.remove(self._taskbar_ledger_path)
                return
            os.makedirs(os.path.dirname(self._taskbar_ledger_path), exist_ok=True)
            temporary = self._taskbar_ledger_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._taskbar_ledger_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _recover_taskbars(self):
        if (not self._taskbar_ledger_path or
                not os.path.exists(self._taskbar_ledger_path)):
            return
        try:
            with open(self._taskbar_ledger_path, "r", encoding="utf-8") as handle:
                rows = json.load(handle)
            for row in rows if isinstance(rows, list) else []:
                hwnd = int(row.get("hwnd", 0))
                if (not win32gui.IsWindow(hwnd) or
                        winapi.get_window_pid(hwnd) != int(row.get("pid", 0)) or
                        win32gui.GetClassName(hwnd) not in _TASKBAR_CLASSES):
                    continue
                winapi.restore_window(
                    hwnd, had_layered=bool(row.get("had_layered")),
                    prev_alpha=row.get("previous_alpha"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        finally:
            try:
                os.remove(self._taskbar_ledger_path)
            except OSError:
                pass

    def _create_taskbar_backdrop(self, hwnd, rect):
        self._register_class()
        left, top, right, bottom = rect
        ex_style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT |
                    win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW)
        backdrop = win32gui.CreateWindowEx(
            ex_style, _WINDOW_CLASS, "Taskbar Dimming Backdrop",
            win32con.WS_POPUP, left, top, right - left, bottom - top,
            0, 0, win32api.GetModuleHandle(None), None)
        if backdrop:
            ctypes.windll.user32.SetLayeredWindowAttributes(
                backdrop, 0, 255, win32con.LWA_ALPHA)
            _set_capture_excluded(backdrop, self._capture_active)
        return backdrop

    def _restore_taskbar(self, hwnd, state, destroy_backdrop=False):
        if state.get("applied") and win32gui.IsWindow(hwnd):
            winapi.restore_window(
                hwnd, had_layered=state["had_layered"],
                prev_alpha=state["previous_alpha"])
            state["applied"] = False
            self._write_taskbar_ledger()
        backdrop = state.get("backdrop")
        if backdrop and win32gui.IsWindow(backdrop):
            if destroy_backdrop:
                try:
                    win32gui.DestroyWindow(backdrop)
                except win32gui.error:
                    pass
                state["backdrop"] = None
            else:
                win32gui.ShowWindow(backdrop, win32con.SW_HIDE)

    def _sync_taskbars(self):
        targets = self._taskbar_targets() if self.enabled else {}
        for hwnd in list(self._taskbars):
            if hwnd not in targets or not win32gui.IsWindow(hwnd):
                state = self._taskbars.pop(hwnd)
                self._restore_taskbar(hwnd, state, destroy_backdrop=True)

        for hwnd, (monitor_name, rect) in targets.items():
            state = self._taskbars.get(hwnd)
            if state is None:
                state = self._new_taskbar_state(hwnd, monitor_name)
                if state is None:
                    continue
                self._taskbars[hwnd] = state
            state["monitor"] = monitor_name

            intensity = self._alpha(monitor_name)
            if self._capture_active or intensity <= 0:
                self._restore_taskbar(hwnd, state)
                continue

            backdrop = state.get("backdrop")
            if backdrop is None or not win32gui.IsWindow(backdrop):
                backdrop = self._create_taskbar_backdrop(hwnd, rect)
                state["backdrop"] = backdrop
            if not backdrop:
                continue

            left, top, right, bottom = rect
            _set_capture_excluded(backdrop, False)
            win32gui.SetWindowPos(
                backdrop, hwnd, left, top, right - left, bottom - top,
                win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
            if not winapi.set_window_alpha(hwnd, 255 - intensity):
                win32gui.ShowWindow(backdrop, win32con.SW_HIDE)
                continue
            state["applied"] = True
            state["rect"] = rect
            self._write_taskbar_ledger()

    def _destroy_taskbars(self):
        for hwnd, state in list(self._taskbars.items()):
            self._restore_taskbar(hwnd, state, destroy_backdrop=True)
        self._taskbars.clear()

    def _destroy_one(self, name):
        hwnd = self._overlays.pop(name, None)
        _overlay_owners.pop(hwnd, None)
        if hwnd and win32gui.IsWindow(hwnd):
            try:
                win32gui.DestroyWindow(hwnd)
            except win32gui.error:
                pass

    def _rebuild(self):
        """Make the live overlays match the current target monitors, creating,
        moving and destroying windows as displays or the selection change."""
        rects = self._overlay_rects(self._target_monitors())
        for name in list(self._overlays):
            if name not in rects:
                self._destroy_one(name)
        for name, rect in rects.items():
            hwnd = self._overlays.get(name)
            if hwnd is None or not win32gui.IsWindow(hwnd):
                self._overlays[name] = self._create(name, rect)
            else:
                self._reassert(name, hwnd, rect)
        self._sync_taskbars()

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        if self.enabled:
            self._capture_active = self._capture_ui_active()
            self._rebuild()
            self._z_order_hook.start()
        else:
            self._z_order_hook.stop()
            self._capture_active = False
            self._destroy_taskbars()
            for hwnd in self._overlays.values():
                if hwnd and win32gui.IsWindow(hwnd):
                    _set_capture_excluded(hwnd, False)
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    def set_intensity(self, value: int):
        """Set the fallback used for monitors without a saved level."""
        self._intensity = max(0, min(MAX_DIM_ALPHA, int(value)))
        if self.enabled:
            for name, hwnd in self._overlays.items():
                if hwnd and win32gui.IsWindow(hwnd):
                    ctypes.windll.user32.SetLayeredWindowAttributes(
                        hwnd, 0, self._alpha(name), win32con.LWA_ALPHA)
            self._sync_taskbars()

    def tick(self):
        """Call periodically (e.g. every 2 s from the UI) while enabled to keep
        the overlays topmost, sized to the current desktop, and in sync with
        monitors being plugged in or removed."""
        if not self.enabled:
            return
        self._set_capture_active(self._capture_ui_active())
        self._rebuild()

    def destroy(self):
        self._z_order_hook.stop()
        self._capture_active = False
        self._destroy_taskbars()
        for name in list(self._overlays):
            self._destroy_one(name)
        self._overlays.clear()
        self.enabled = False
