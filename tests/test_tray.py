from types import SimpleNamespace

from transparency_app.tray import Tray


class FakeController:
    def __init__(self):
        self.engine = SimpleNamespace(paused=False, focus_mode=False)
        self.update_state = "idle"
        self.install_requests = 0

    def show_window(self):
        pass

    def toggle_paused(self):
        pass

    def toggle_focus(self):
        pass

    def restore_all(self):
        pass

    def request_install_update(self):
        self.install_requests += 1

    def quit(self):
        pass


class FakeIcon:
    HAS_NOTIFICATION = True

    def __init__(self):
        self.notifications = []

    def notify(self, message, title=None):
        self.notifications.append((message, title))


def test_ready_update_is_available_from_tray_menu():
    controller = FakeController()
    tray = Tray(controller)
    assert "Install downloaded update" not in {
        item.text for item in tray._menu().items}

    controller.update_state = "ready"
    assert "Install downloaded update" in {
        item.text for item in tray._menu().items}


def test_verified_update_uses_native_desktop_notification():
    tray = Tray(FakeController())
    tray._icon = FakeIcon()

    assert tray.notify_update("9.2.1") is True
    message, title = tray._icon.notifications[-1]
    assert "9.2.1" in message
    assert "downloaded and verified" in message
    assert title == "Transparency App update ready"
