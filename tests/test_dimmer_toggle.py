from types import SimpleNamespace

from transparency_app.app import AppController


class FakeDimmer:
    def __init__(self):
        self.enabled = False
        self.calls = []
        self.ticks = 0

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.calls.append(self.enabled)

    def tick(self):
        self.ticks += 1


class FakeWindow:
    def __init__(self):
        self.states = []
        self._after_id = 0

    def after(self, delay, callback, *args):
        # Like Tk: delay 0 runs on the UI loop; longer delays only schedule.
        if delay == 0:
            callback(*args)
            return 0
        self._after_id += 1
        return self._after_id

    def after_cancel(self, _ident):
        pass

    def set_dimmer_state(self, enabled):
        self.states.append(bool(enabled))


class FakeTray:
    def __init__(self):
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


def make_dimmer_controller():
    controller = AppController.__new__(AppController)
    controller.dimmer = FakeDimmer()
    controller.config = SimpleNamespace(
        store={},
        set_setting=lambda k, v, s={}: s.__setitem__(k, v),
        get_setting=lambda k, d=None: None,
    )
    # Bind a real dict-backed set_setting for assertions.
    store = {}
    controller.config = SimpleNamespace(
        set_setting=lambda k, v: store.__setitem__(k, v),
        store=store,
    )
    controller.window = FakeWindow()
    controller.tray = FakeTray()
    controller._dimmer_tick_id = None
    return controller


def test_toggle_dimmer_runs_on_ui_thread_and_syncs_everywhere():
    controller = make_dimmer_controller()

    controller.toggle_dimmer()
    assert controller.dimmer.enabled is True
    assert controller.config.store["dimmer_enabled"] is True
    assert controller.window.states == [True]
    assert controller.tray.refreshes == 1

    controller.toggle_dimmer()
    assert controller.dimmer.enabled is False
    assert controller.config.store["dimmer_enabled"] is False
    assert controller.window.states == [True, False]
    assert controller.tray.refreshes == 2


def test_set_dimmer_enabled_updates_tray_and_window():
    controller = make_dimmer_controller()
    controller.set_dimmer_enabled(True)
    assert controller.dimmer.enabled is True
    assert controller.window.states == [True]
    assert controller.tray.refreshes == 1
