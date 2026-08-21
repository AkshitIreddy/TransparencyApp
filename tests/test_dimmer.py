import ctypes
import ctypes.wintypes as wintypes

import pytest
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


def test_capture_affinity_is_off_normally_and_only_on_during_snipping():
    if not dimmer_module._capture_exclusion_supported():
        pytest.skip("WDA_EXCLUDEFROMCAPTURE requires Windows 10 version 2004+")

    user32 = ctypes.windll.user32
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL

    dimmer = ScreenDimmer()
    hwnd = dimmer._create("TEST_DISPLAY", (-32000, -32000, 64, 64))
    dimmer._overlays["TEST_DISPLAY"] = hwnd
    affinity = wintypes.DWORD()
    try:
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
def test_only_transient_capture_surfaces_enable_capture_affinity(
        process, class_name, title, rect, active):
    assert dimmer_module._is_capture_surface(
        process, class_name, title, rect, (0, 0, 1920, 1080)) is active
