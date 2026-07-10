import ctypes
import threading
import time

from transparency_app.hotkeys import (
    Hotkey, HotkeyManager, MOD_ALT, MOD_CONTROL, MOD_SHIFT,
    format_combo, parse_combo,
)

# Deliberately obscure combos so tests don't collide with anything real.
VK_F13 = 0x7C
VK_F14 = 0x7D


class TestComboParsing:
    def test_basic(self):
        assert parse_combo("ctrl+alt+t") == (MOD_CONTROL | MOD_ALT, ord("T"))

    def test_case_and_spaces_ignored(self):
        assert parse_combo(" Ctrl + Shift + F9 ") == (
            MOD_CONTROL | MOD_SHIFT, 0x78)

    def test_named_keys(self):
        assert parse_combo("ctrl+alt+up") == (MOD_CONTROL | MOD_ALT, 0x26)
        assert parse_combo("ctrl+alt+home") == (MOD_CONTROL | MOD_ALT, 0x24)
        assert parse_combo("ctrl+alt+pagedown") == (MOD_CONTROL | MOD_ALT, 0x22)

    def test_requires_modifier(self):
        assert parse_combo("t") is None

    def test_requires_key(self):
        assert parse_combo("ctrl+alt") is None

    def test_garbage_rejected(self):
        assert parse_combo("ctrl+banana") is None
        assert parse_combo("") is None

    def test_format_round_trip(self):
        assert format_combo("ctrl+alt+t") == "Ctrl+Alt+T"
        assert format_combo("ctrl+alt+up") == "Ctrl+Alt+↑"
        assert format_combo("ctrl+shift+f9") == "Ctrl+Shift+F9"
        # Formatted output parses back to the same binding.
        assert parse_combo(format_combo("ctrl+alt+home")) == \
            parse_combo("ctrl+alt+home")


class TestRegistration:
    def test_register_and_stop(self):
        mgr = HotkeyManager()
        results = mgr.start([
            Hotkey(1, MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_F13, lambda: None)])
        try:
            assert results == {1: True}
            assert mgr.active
        finally:
            mgr.stop()
        assert not mgr.active

    def test_conflict_reported_not_fatal(self):
        a, b = HotkeyManager(), HotkeyManager()
        combo = MOD_CONTROL | MOD_ALT | MOD_SHIFT
        first = a.start([Hotkey(1, combo, VK_F14, lambda: None)])
        second = b.start([Hotkey(1, combo, VK_F14, lambda: None)])
        try:
            assert first == {1: True}
            assert second == {1: False}, \
                "a combo owned by another app must report False, not crash"
        finally:
            a.stop()
            b.stop()

    def test_combo_free_after_stop(self):
        combo = MOD_CONTROL | MOD_ALT | MOD_SHIFT
        a = HotkeyManager()
        a.start([Hotkey(1, combo, VK_F13, lambda: None)])
        a.stop()
        b = HotkeyManager()
        results = b.start([Hotkey(1, combo, VK_F13, lambda: None)])
        try:
            assert results == {1: True}, "stop() must unregister its hotkeys"
        finally:
            b.stop()


class TestDispatch:
    def test_callback_fires_on_wm_hotkey(self):
        """Post WM_HOTKEY straight to the pump thread: deterministic, and it
        never injects real key events into the machine running the tests."""
        import win32con

        fired = threading.Event()
        mgr = HotkeyManager()
        results = mgr.start([
            Hotkey(7, MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_F13,
                   fired.set)])
        try:
            assert results[7]
            user32 = ctypes.windll.user32
            assert user32.PostThreadMessageW(
                mgr._thread_id, win32con.WM_HOTKEY, 7, 0)
            assert fired.wait(timeout=5), "WM_HOTKEY never reached the callback"
        finally:
            mgr.stop()
