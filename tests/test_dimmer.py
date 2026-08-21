import ctypes
import ctypes.wintypes as wintypes
import time

import pytest
import win32con
import win32gui

from transparency_app import dimmer as dimmer_module
from transparency_app.dimmer import (
    MAX_DIM_ALPHA,
    WDA_EXCLUDEFROMCAPTURE,
    ScreenDimmer,
)


def test_monitor_intensities_have_independent_values():
    dimmer = ScreenDimmer()
    dimmer.set_intensity(100)
    dimmer.set_monitor_intensity("DISPLAY1", 25)
    dimmer.set_monitor_intensity("DISPLAY2", 175)

    assert dimmer.intensity_for("DISPLAY1") == 25
    assert dimmer.intensity_for("DISPLAY2") == 175
    assert dimmer.intensity_for("NEW_DISPLAY") == 100
    assert dimmer._alpha("DISPLAY1") == 25
    assert dimmer._alpha("DISPLAY2") == 175


def test_monitor_intensities_are_clamped_and_copied():
    dimmer = ScreenDimmer()
    levels = {"DISPLAY1": -10, "DISPLAY2": 500}
    dimmer.set_intensities(levels)
    levels["DISPLAY1"] = 90

    assert dimmer.intensities == {"DISPLAY1": 0, "DISPLAY2": MAX_DIM_ALPHA}
    returned = dimmer.intensities
    returned["DISPLAY1"] = 80
    assert dimmer.intensity_for("DISPLAY1") == 0


def test_overlay_is_excluded_from_screen_capture_on_supported_windows():
    if not dimmer_module._capture_exclusion_supported():
        pytest.skip("WDA_EXCLUDEFROMCAPTURE requires Windows 10 version 2004+")

    user32 = ctypes.windll.user32
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL

    dimmer = ScreenDimmer()
    hwnd = dimmer._create("TEST_DISPLAY", (-32000, -32000, 64, 64))
    try:
        assert hwnd and win32gui.IsWindow(hwnd)
        affinity = wintypes.DWORD()
        assert user32.GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(affinity))
        assert affinity.value == WDA_EXCLUDEFROMCAPTURE
    finally:
        if hwnd and win32gui.IsWindow(hwnd):
            win32gui.DestroyWindow(hwnd)


def _z_order_index(hwnd):
    windows = []
    win32gui.EnumWindows(lambda candidate, _: windows.append(candidate) or True,
                         None)
    return windows.index(hwnd)


def test_shell_event_reasserts_overlay_above_new_topmost_surface(make_window):
    dimmer = ScreenDimmer()
    overlay = dimmer._create("TEST_DISPLAY", (-32000, -32000, 64, 64))
    dimmer._overlays["TEST_DISPLAY"] = overlay
    dimmer.enabled = True
    shell_surface = make_window()
    win32gui.SetWindowPos(
        shell_surface.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010)  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    try:
        assert _z_order_index(shell_surface.hwnd) < _z_order_index(overlay)

        dimmer._on_shell_event(
            dimmer_module.winapi.EVENT_OBJECT_SHOW, shell_surface.hwnd)
        deadline = time.time() + 1
        while time.time() < deadline:
            win32gui.PumpWaitingMessages()
            if _z_order_index(overlay) < _z_order_index(shell_surface.hwnd):
                break
            time.sleep(0.01)

        assert _z_order_index(overlay) < _z_order_index(shell_surface.hwnd)
    finally:
        dimmer.destroy()
