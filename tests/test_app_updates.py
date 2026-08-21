import threading
import time
from types import SimpleNamespace

from transparency_app import app as app_module
from transparency_app.app import AppController


class FakeWindow:
    def __init__(self):
        self.states = []
        self.offers = []

    def after(self, _delay, callback):
        callback()

    def set_update_state(self, state, message):
        self.states.append((state, message))

    def offer_update(self, version):
        self.offers.append(version)


class FakeTray:
    def __init__(self):
        self.notifications = []
        self.refresh_count = 0

    def refresh(self):
        self.refresh_count += 1

    def notify_update(self, version):
        self.notifications.append(version)


def make_controller():
    controller = AppController.__new__(AppController)
    controller.window = FakeWindow()
    controller.tray = FakeTray()
    controller.update_state = "idle"
    controller.update_message = ""
    controller._update_info = None
    controller._staged_update = None
    controller._update_lock = threading.Lock()
    return controller


def wait_until_ready(controller):
    deadline = time.time() + 2
    while time.time() < deadline and controller.update_state != "ready":
        time.sleep(0.01)
    assert controller.update_state == "ready"


def configure_verified_update(monkeypatch):
    release = SimpleNamespace(version="9.2.1")
    monkeypatch.setattr(app_module.updater, "check_for_update", lambda: release)
    monkeypatch.setattr(
        app_module.updater, "staged_update_path",
        lambda version: f"TransparencyApp-v{version}.exe")
    monkeypatch.setattr(
        app_module.updater, "download_update",
        lambda info, destination, progress: destination)


def test_automatic_update_notifies_without_interrupting(monkeypatch):
    configure_verified_update(monkeypatch)
    controller = make_controller()

    controller.check_for_updates(manual=False)
    wait_until_ready(controller)

    assert controller.tray.notifications == ["9.2.1"]
    assert controller.window.offers == []
    assert controller._staged_update == "TransparencyApp-v9.2.1.exe"


def test_manual_update_check_still_offers_immediate_install(monkeypatch):
    configure_verified_update(monkeypatch)
    controller = make_controller()

    controller.check_for_updates(manual=True)
    wait_until_ready(controller)

    assert controller.tray.notifications == ["9.2.1"]
    assert controller.window.offers == ["9.2.1"]
