"""Shared fixtures: real native Win32 windows to run assertions against.

Each test window runs its OWN message-pump thread and destroys itself on
that thread. This matters because the engine worker thread applies
transparency with SetWindowLong / SetLayeredWindowAttributes, and those
cross-thread calls block until the target window's thread pumps messages.
A window that pumps continuously (like every real app) keeps the engine
from deadlocking, so the test's main thread only ever needs to read state.

Windows are created with the built-in "#32770" dialog class (a native
wndproc — a Python wndproc would crash once its ctypes wrapper is collected)
and positioned far off-screen so they never appear as ghost windows.
"""

import faulthandler
import os
import tempfile
import threading
import time
import uuid

import pytest
import win32api
import win32con
import win32gui

# Per-test hang watchdog. faulthandler's timer is a raw C thread, so it fires
# even if a Python thread is blocked in a native call holding the GIL: it
# dumps every stack to %TEMP%/ta_fault_dump.txt and hard-exits the process.
_fault_file = open(
    os.path.join(tempfile.gettempdir(), "ta_fault_dump.txt"), "w", buffering=1)


@pytest.fixture(autouse=True)
def _hang_watchdog():
    faulthandler.dump_traceback_later(25, exit=True, file=_fault_file)
    yield
    faulthandler.cancel_dump_traceback_later()


DIALOG_CLASS = "#32770"


class NativeWindow:
    """An off-screen top-level window that pumps its own messages."""

    def __init__(self, title=None, visible=True):
        self.title = title or f"TA-Test-{uuid.uuid4().hex[:8]}"
        self._visible = visible
        self.hwnd = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(timeout=5), "window thread never started"
        assert self.hwnd, "CreateWindowEx failed"

    def _run(self):
        style = win32con.WS_OVERLAPPEDWINDOW
        if self._visible:
            style |= win32con.WS_VISIBLE
        self.hwnd = win32gui.CreateWindowEx(
            0, DIALOG_CLASS, self.title, style,
            -32000, -32000, 320, 200,
            0, 0, win32api.GetModuleHandle(None), None)
        self._ready.set()
        while not self._stop.is_set():
            win32gui.PumpWaitingMessages()
            time.sleep(0.005)
        if win32gui.IsWindow(self.hwnd):
            win32gui.DestroyWindow(self.hwnd)

    def set_title(self, title):
        self.title = title
        # Cross-thread SetWindowText is serviced by our own pump thread.
        win32gui.SetWindowText(self.hwnd, title)

    def close(self):
        self._stop.set()
        self._thread.join(timeout=3)


@pytest.fixture
def native_window():
    w = NativeWindow()
    yield w
    w.close()


@pytest.fixture
def second_window():
    w = NativeWindow()
    yield w
    w.close()


@pytest.fixture
def make_window():
    created = []

    def _make(**kwargs):
        w = NativeWindow(**kwargs)
        created.append(w)
        return w

    yield _make
    for w in created:
        w.close()


def wait_for(predicate, timeout=6.0):
    """Poll a condition. The test windows pump themselves, so the main
    thread just needs to read — no message pumping required here."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
