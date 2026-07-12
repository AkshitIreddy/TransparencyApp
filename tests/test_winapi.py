import gc
import os
import time

import win32con
import win32gui

from transparency_app import winapi


class TestAlpha:
    def test_set_and_get(self, native_window):
        assert winapi.set_window_alpha(native_window.hwnd, 180)
        assert winapi.get_window_alpha(native_window.hwnd) == 180

    def test_clamping(self, native_window):
        winapi.set_window_alpha(native_window.hwnd, 999)
        assert winapi.get_window_alpha(native_window.hwnd) == 255
        winapi.set_window_alpha(native_window.hwnd, -1)
        assert winapi.get_window_alpha(native_window.hwnd) == 0

    def test_unlayered_window_reports_none(self, native_window):
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_restore_strips_layered_bit(self, native_window):
        winapi.set_window_alpha(native_window.hwnd, 100)
        assert winapi.restore_window(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) is None
        style = win32gui.GetWindowLong(native_window.hwnd, win32con.GWL_EXSTYLE)
        assert not style & win32con.WS_EX_LAYERED

    def test_restore_preserves_originally_layered(self, native_window):
        # Window that was layered at alpha 200 before we touched it.
        winapi.set_window_alpha(native_window.hwnd, 200)
        winapi.set_window_alpha(native_window.hwnd, 80)
        winapi.restore_window(native_window.hwnd, had_layered=True, prev_alpha=200)
        assert winapi.get_window_alpha(native_window.hwnd) == 200


class TestStyles:
    def test_click_through(self, native_window):
        assert winapi.set_click_through(native_window.hwnd, True)
        assert winapi.is_click_through(native_window.hwnd)
        assert winapi.set_click_through(native_window.hwnd, False)
        assert not winapi.is_click_through(native_window.hwnd)

    def test_topmost(self, native_window):
        assert winapi.set_topmost(native_window.hwnd, True)
        assert winapi.is_topmost(native_window.hwnd)
        assert winapi.set_topmost(native_window.hwnd, False)
        assert not winapi.is_topmost(native_window.hwnd)


class TestQueries:
    def test_window_info(self, native_window):
        info = winapi.get_window_info(native_window.hwnd)
        assert info.title == native_window.title
        assert info.pid == os.getpid()
        assert info.process in ("python.exe", "pythonw.exe")

    def test_enum_finds_our_window(self, native_window):
        titles = [w.title for w in winapi.enum_app_windows()]
        assert native_window.title in titles

    def test_hidden_window_not_app_window(self, make_window):
        hidden = make_window(visible=False)
        assert not winapi.is_app_window(hidden.hwnd)

    def test_is_app_window(self, native_window):
        assert winapi.is_app_window(native_window.hwnd)

    def test_dead_hwnd(self, make_window):
        w = make_window()
        hwnd = w.hwnd
        w.close()
        assert not winapi.is_window(hwnd)
        assert not winapi.set_window_alpha(hwnd, 100)


class TestMonitors:
    def test_enum_monitors_shape(self):
        mons = winapi.enum_monitors()
        assert isinstance(mons, list)
        # The test host always has at least one display.
        assert len(mons) >= 1
        for m in mons:
            assert set(("name", "rect", "primary", "number", "label")) <= set(m)
            x, y, w, h = m["rect"]
            assert w > 0 and h > 0
        assert sum(1 for m in mons if m["primary"]) <= 1

    def test_enum_monitors_names_unique(self):
        names = [m["name"] for m in winapi.enum_monitors() if m["name"]]
        assert len(names) == len(set(names))


class TestWinEventHook:
    def _wait_for(self, predicate, timeout=12.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_hook_sees_new_window(self, make_window):
        events = []
        hook = winapi.WinEventHook(
            lambda ev, hwnd: events.append((ev, hwnd)), skip_own_process=False)
        hook.start()
        try:
            assert hook.active
            w = make_window()
            assert self._wait_for(
                lambda: any(h == w.hwnd for _, h in events)
            ), "hook never reported our new window"
        finally:
            hook.stop()
        assert not hook.active

    def test_hook_survives_gc(self, make_window):
        """The ctypes callback must stay pinned; GC must not break the hook."""
        events = []
        hook = winapi.WinEventHook(
            lambda ev, hwnd: events.append(hwnd), skip_own_process=False)
        hook.start()
        try:
            gc.collect()
            w = make_window()
            assert self._wait_for(lambda: w.hwnd in events)
        finally:
            hook.stop()

    def test_title_change_event(self, make_window):
        events = []
        hook = winapi.WinEventHook(
            lambda ev, hwnd: events.append((ev, hwnd)), skip_own_process=False)
        hook.start()
        try:
            w = make_window()
            time.sleep(0.2)
            events.clear()
            w.set_title("TA-Renamed-" + w.title)
            assert self._wait_for(lambda: any(
                ev == winapi.EVENT_OBJECT_NAMECHANGE and h == w.hwnd
                for ev, h in events))
        finally:
            hook.stop()
