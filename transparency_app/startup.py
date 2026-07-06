"""Run-at-startup toggle via the per-user Run registry key (no admin needed)."""

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "TransparencyApp"


def _launch_command() -> str:
    """The command Windows should run at login."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev installs: run the package with pythonw (no console window).
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pythonw}" -m transparency_app'


def is_enabled(value_name: str = APP_VALUE_NAME) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, value_name)
        return True
    except OSError:
        return False


def enable(value_name: str = APP_VALUE_NAME, command: str = None) -> bool:
    try:
        # CreateKeyEx opens the Run key or creates it if a freshly-provisioned
        # profile doesn't have it yet (OpenKey would raise FileNotFoundError).
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(
                key, value_name, 0, winreg.REG_SZ, command or _launch_command())
        return True
    except OSError:
        return False


def disable(value_name: str = APP_VALUE_NAME) -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, value_name)
        return True
    except FileNotFoundError:
        # Either the Run key or our value is absent — nothing to remove.
        return True
    except OSError:
        return False
