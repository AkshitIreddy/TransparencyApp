import winreg

import pytest

from transparency_app import startup

TEST_VALUE = "TransparencyAppPytest"


@pytest.fixture(autouse=True)
def clean_registry():
    startup.disable(TEST_VALUE)
    yield
    startup.disable(TEST_VALUE)


class TestStartupToggle:
    def test_disabled_by_default(self):
        assert not startup.is_enabled(TEST_VALUE)

    def test_enable_disable_round_trip(self):
        assert startup.enable(TEST_VALUE, command='"C:\\fake\\app.exe"')
        assert startup.is_enabled(TEST_VALUE)
        assert startup.disable(TEST_VALUE)
        assert not startup.is_enabled(TEST_VALUE)

    def test_enable_writes_expected_command(self):
        startup.enable(TEST_VALUE, command='"C:\\fake\\app.exe"')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, TEST_VALUE)
        assert value == '"C:\\fake\\app.exe"'
        assert kind == winreg.REG_SZ

    def test_disable_when_missing_is_ok(self):
        assert startup.disable(TEST_VALUE)

    def test_default_command_points_at_app(self):
        cmd = startup._launch_command()
        assert "python" in cmd.lower() or ".exe" in cmd.lower()
