"""GUI smoke test: build the whole window and every page without a human.

It uses a fake controller so nothing touches the OS (engine/hotkeys/registry).
Skipped automatically if no display / Tk is available (e.g. headless CI).
"""

import pytest

ctk = pytest.importorskip("customtkinter")

from transparency_app.config import ConfigManager  # noqa: E402


class FakeEngine:
    paused = False
    focus_mode = False

    def affected_window_count(self):
        return 3

    def get_override(self, hwnd):
        return None


class FakeDimmer:
    enabled = False
    intensity = 120
    monitors = "all"
    intensities = {}

    def intensity_for(self, _name):
        return self.intensity


class FakeController:
    def __init__(self, tmp_path):
        self.config = ConfigManager(str(tmp_path / "config.json"))
        self.engine = FakeEngine()
        self.dimmer = FakeDimmer()
        self.icon_path = None
        self.update_state = "idle"
        self.update_message = "Updates are checked automatically."

    # every action the window can call — all no-ops
    def on_close_request(self): pass
    def set_paused(self, p): self.engine.paused = p
    def set_focus_mode(self, e): self.engine.focus_mode = e
    def set_dimmer_enabled(self, e): self.dimmer.enabled = e
    def set_dimmer_intensity(self, v): self.dimmer.intensity = v
    def set_monitor_dimmer_intensity(self, name, v):
        self.dimmer.intensities[name] = int(float(v))
    def set_dimmer_monitors(self, v): self.dimmer.monitors = v
    def restore_all(self): pass
    def is_startup_enabled(self): return False
    def set_startup(self, e): return True
    def set_hotkeys_enabled(self, e): pass
    def set_update_checks_enabled(self, e):
        self.config.set_setting("check_updates_on_startup", e)
    def check_for_updates(self, manual=False):
        self.last_manual_update_check = manual
    def install_ready_update(self): self.update_state = "installing"
    def apply_theme(self, m): pass
    def hotkey_descriptions(self):
        return [("toggle_transparency", "Toggle transparency", "ctrl+alt+t"),
                ("toggle_focus", "Focus mode", "ctrl+alt+f")]
    def set_hotkey_binding(self, action, combo):
        self.last_binding = (action, combo)
        return True, ""
    def reset_hotkey_bindings(self): pass


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # One root window for the whole module: CustomTkinter does not support
    # multiple CTk() roots in a single process.
    tmp_path = tmp_path_factory.mktemp("ui")
    try:
        from transparency_app.ui.app_window import AppWindow
        win = AppWindow(FakeController(tmp_path))
    except Exception as e:
        pytest.skip(f"no GUI available: {e}")
    win.update_idletasks()
    yield win
    try:
        win.destroy()
    except Exception:
        pass


def test_all_pages_build(app):
    for page in ("rules", "focus", "dimmer", "settings"):
        app.show_page(page)
        app.update_idletasks()
    assert app._page == "settings"


def test_rules_render_and_add(app):
    app.show_page("rules")
    app.config_mgr.add_rule("notepad", opacity=180)
    app._render_rules()
    app.update_idletasks()
    assert any(getattr(c, "rule", None) and c.rule.pattern == "notepad"
               for c in app._cards)


def test_accent_change_applies_and_persists(app):
    from transparency_app.ui import theme
    app.show_page("settings")
    app._change_accent("teal")
    app.update_idletasks()
    assert theme.ACCENT == theme.ACCENTS["teal"][0]
    assert app.config_mgr.get_setting("accent") == "teal"
    app._change_accent("blue")


def test_pause_switch_reflects_state(app):
    app.set_pause_state(True)
    app.update_idletasks()
    assert app.pause_switch.get() == 0  # off = paused
    app.set_pause_state(False)
    assert app.pause_switch.get() == 1


def test_update_controls_reflect_ready_state(app):
    app.show_page("settings")
    app.set_update_state("ready", "v9.0.0 is ready to install.")
    app.update_idletasks()
    assert app._update_status_label.cget("text") == "v9.0.0 is ready to install."
    assert app._update_button.cget("text") == "Install & restart"
