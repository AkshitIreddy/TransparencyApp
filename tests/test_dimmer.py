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
    WDA_NONE,
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


def test_overlay_capture_exclusion_is_only_active_during_snipping():
    if not dimmer_module._capture_exclusion_supported():
        pytest.skip("WDA_EXCLUDEFROMCAPTURE requires Windows 10 version 2004+")

    user32 = ctypes.windll.user32
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL

    dimmer = ScreenDimmer()
    hwnd = dimmer._create("TEST_DISPLAY", (-32000, -32000, 64, 64))
    dimmer._overlays["TEST_DISPLAY"] = hwnd
    try:
        assert hwnd and win32gui.IsWindow(hwnd)
        affinity = wintypes.DWORD()
        assert user32.GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(affinity))
        assert affinity.value == WDA_NONE

        dimmer._set_capture_active(True)
        assert user32.GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(affinity))
        assert affinity.value == WDA_EXCLUDEFROMCAPTURE

        dimmer._set_capture_active(False)
        assert user32.GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(affinity))
        assert affinity.value == WDA_NONE
    finally:
        dimmer.destroy()


@pytest.mark.parametrize(("process", "class_name", "title", "rect", "active"), [
    ("screenclippinghost.exe", "ApplicationFrameWindow", "", (0, 0, 10, 10), True),
    ("snippingtool.exe", "Microsoft-Windows-SnipperCaptureForm", "", (0, 0, 10, 10), True),
    ("snippingtool.exe", "ApplicationFrameWindow", "Snipping Tool", (10, 10, 800, 600), False),
    ("notepad.exe", "Notepad", "Notes", (0, 0, 1920, 1080), False),
])
def test_only_transient_capture_surfaces_suspend_dimming(
        process, class_name, title, rect, active):
    assert dimmer_module._is_capture_surface(
        process, class_name, title, rect, (0, 0, 1920, 1080)) is active


def test_taskbar_dimming_applies_alpha_over_black_and_restores(
        make_window, monkeypatch):
    taskbar = make_window()
    rect = win32gui.GetWindowRect(taskbar.hwnd)
    dimmer = ScreenDimmer()
    dimmer.set_monitor_intensity("DISPLAY2", 131)
    monkeypatch.setattr(
        dimmer, "_taskbar_targets",
        lambda: {taskbar.hwnd: ("DISPLAY2", rect)})
    dimmer.enabled = True

    assert dimmer_module.winapi.get_window_alpha(taskbar.hwnd) is None
    dimmer._sync_taskbars()
    state = dimmer._taskbars[taskbar.hwnd]
    try:
        assert dimmer_module.winapi.get_window_alpha(taskbar.hwnd) == 124
        assert state["backdrop"] and win32gui.IsWindow(state["backdrop"])
    finally:
        dimmer.destroy()

    assert dimmer_module.winapi.get_window_alpha(taskbar.hwnd) is None


def test_taskbar_crash_ledger_restores_original_state(
        make_window, monkeypatch, tmp_path):
    taskbar = make_window()
    rect = win32gui.GetWindowRect(taskbar.hwnd)
    ledger = tmp_path / "taskbar-session.json"
    monkeypatch.setattr(
        dimmer_module, "_TASKBAR_CLASSES",
        dimmer_module._TASKBAR_CLASSES | {"#32770"})

    dimmer = ScreenDimmer(taskbar_ledger_path=str(ledger))
    dimmer.set_monitor_intensity("DISPLAY2", 131)
    monkeypatch.setattr(
        dimmer, "_taskbar_targets",
        lambda: {taskbar.hwnd: ("DISPLAY2", rect)})
    dimmer.enabled = True
    dimmer._sync_taskbars()
    state = dimmer._taskbars[taskbar.hwnd]
    assert ledger.exists()
    assert dimmer_module.winapi.get_window_alpha(taskbar.hwnd) == 124

    # A killed process loses its own backdrop windows but cannot cleanly
    # restore Explorer. The next app construction consumes the crash ledger.
    if state["backdrop"] and win32gui.IsWindow(state["backdrop"]):
        win32gui.DestroyWindow(state["backdrop"])
    recovered = ScreenDimmer(taskbar_ledger_path=str(ledger))

    assert dimmer_module.winapi.get_window_alpha(taskbar.hwnd) is None
    assert not ledger.exists()
    dimmer._taskbars.clear()
    recovered.destroy()


def _z_order_index(hwnd):
    windows = []
    win32gui.EnumWindows(lambda candidate, _: windows.append(candidate) or True,
                         None)
    return windows.index(hwnd)


def test_shell_event_reasserts_overlay_above_new_topmost_surface(
        make_window, monkeypatch):
    dimmer = ScreenDimmer()
    overlay = dimmer._create("TEST_DISPLAY", (-32000, -32000, 64, 64))
    dimmer._overlays["TEST_DISPLAY"] = overlay
    dimmer.enabled = True
    monkeypatch.setattr(
        dimmer, "_rebuild",
        lambda: dimmer._reassert(
            "TEST_DISPLAY", overlay, (-32000, -32000, 64, 64)))
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
