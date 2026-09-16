"""Branded, transactional installer mode for verified app updates.

The downloaded one-file executable runs this module itself.  It waits for the
old app to close, replaces it with a byte-for-byte copy of itself, and starts
the installed copy.  Keeping the replacement logic in the new executable lets
the user see a first-party progress window without shipping a second binary.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading

import customtkinter as ctk

from . import paths
from .ui import theme

ASSET_NAME = "TransparencyApp.exe"
WAIT_TIMEOUT_MS = 120_000


class InstallError(RuntimeError):
    pass


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_for_process(process_id, timeout_ms=WAIT_TIMEOUT_MS):
    """Wait for *process_id* to exit without requiring psutil."""
    if not process_id:
        return True
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        # The old process has already gone away.
        return True
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(
            handle, timeout_ms) == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def replace_and_restart(source, target, process_id, expected_sha256,
                        progress=None, launcher=subprocess.Popen,
                        waiter=wait_for_process):
    """Replace *target* transactionally and relaunch it.

    The previous executable remains at ``.previous`` after a successful update
    so a known-good copy is available if the newly launched app later fails.
    """
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    expected_sha256 = str(expected_sha256).lower()
    if os.path.basename(target).lower() != ASSET_NAME.lower():
        raise InstallError("Refusing to replace an unexpected executable name.")
    if not os.path.isfile(source):
        raise InstallError("The verified update file is missing.")
    if file_sha256(source) != expected_sha256:
        raise InstallError("The update no longer matches its verified SHA-256.")

    notify = progress or (lambda _value, _message: None)
    notify(0.12, "Waiting for Transparency App to close…")
    if not waiter(int(process_id or 0), WAIT_TIMEOUT_MS):
        raise InstallError("Transparency App did not close in time.")

    backup = target + ".previous"
    incoming = target + ".updating"
    swapped = False
    try:
        notify(0.38, "Preparing a safe rollback copy…")
        for stale in (incoming, backup):
            if os.path.exists(stale):
                os.remove(stale)
        if os.path.exists(target):
            os.replace(target, backup)

        notify(0.62, "Installing the verified update…")
        shutil.copy2(source, incoming)
        if file_sha256(incoming) != expected_sha256:
            raise InstallError("The installed copy failed SHA-256 verification.")
        os.replace(incoming, target)
        swapped = True

        notify(0.88, "Starting the updated app…")
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        process = launcher(
            [target], cwd=os.path.dirname(target), close_fds=True,
            creationflags=creation_flags)
        notify(1.0, "Update complete — Transparency App is restarting.")
        return process
    except Exception as exc:
        try:
            if os.path.exists(incoming):
                os.remove(incoming)
            if swapped and os.path.exists(target):
                os.remove(target)
            if os.path.exists(backup):
                os.replace(backup, target)
        except OSError:
            pass
        if isinstance(exc, InstallError):
            raise
        raise InstallError(f"Could not install the update: {exc}") from exc


def _appearance_preferences():
    try:
        with open(paths.config_path(), "r", encoding="utf-8") as handle:
            settings = json.load(handle).get("settings", {})
    except (OSError, ValueError, AttributeError):
        settings = {}
    return settings.get("theme", "dark"), settings.get("accent", "blue")


class UpdateInstallerWindow(ctk.CTk):
    def __init__(self, source, target, process_id, expected_sha256,
                 version=None):
        mode, accent = _appearance_preferences()
        theme.apply_appearance(mode)
        theme.set_accent(accent)
        # Re-read the (possibly just switched) accent so the installer
        # matches the running app's own palette.
        try:
            from .ui import theme as _theme_module
            accent_color = _theme_module.ACCENT
        except Exception:
            accent_color = theme.ACCENT
        super().__init__()
        self._args = (source, target, process_id, expected_sha256)
        self._failed = False
        self._version = str(version).strip() if version else ""
        self.title("Update Transparency App")
        self.geometry("560x360")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG)
        try:
            self.iconbitmap(paths.resource_path("assets/icon.ico"))
        except Exception:
            pass

        shell = ctk.CTkFrame(
            self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS,
            border_width=1, border_color=theme.BORDER)
        shell.pack(fill="both", expand=True, padx=22, pady=22)

        brand = ctk.CTkFrame(shell, fg_color="transparent")
        brand.pack(fill="x", padx=24, pady=(24, 8))
        ctk.CTkLabel(
            brand, text="◐", width=44, font=theme.font(34, "bold"),
            text_color=accent_color).pack(side="left")
        titles = ctk.CTkFrame(brand, fg_color="transparent")
        titles.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            titles, text="Updating Transparency App", font=theme.h1(),
            text_color=theme.TEXT).pack(anchor="w")
        subtitle = "Verified release installer"
        if self._version:
            subtitle = f"Verified release installer  •  v{self._version}"
        ctk.CTkLabel(
            titles, text=subtitle, font=theme.small(),
            text_color=theme.TEXT_MUTED).pack(anchor="w")

        self.status = ctk.CTkLabel(
            shell, text="Preparing the verified update…", anchor="w",
            font=theme.body(), text_color=theme.TEXT)
        self.status.pack(fill="x", padx=24, pady=(18, 8))
        self.progress = ctk.CTkProgressBar(
            shell, height=10, corner_radius=5,
            progress_color=accent_color, fg_color=theme.SURFACE_2)
        self.progress.set(0.04)
        self.progress.pack(fill="x", padx=24)
        self.detail = ctk.CTkLabel(
            shell, text="SHA-256 verified  •  Safe rollback enabled",
            font=theme.small(), text_color=theme.TEXT_MUTED)
        self.detail.pack(anchor="w", padx=24, pady=(10, 0))
        self.close_button = ctk.CTkButton(
            shell, text="Close", width=110, height=34,
            fg_color=theme.SURFACE_2, hover_color=theme.BORDER,
            text_color=theme.TEXT, command=self.destroy)

        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.after(180, self._start)

    def _start(self):
        threading.Thread(
            target=self._worker, name="UpdateInstaller", daemon=True).start()

    def _report(self, value, message):
        self.after(0, lambda: self._apply_report(value, message))

    def _apply_report(self, value, message):
        self.progress.set(value)
        self.status.configure(text=message)

    def _worker(self):
        try:
            replace_and_restart(*self._args, progress=self._report)
        except InstallError as exc:
            self.after(0, lambda: self._show_error(str(exc)))
            return
        self.after(1100, self.destroy)

    def _show_error(self, message):
        self._failed = True
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.status.configure(text="The update was not installed.",
                              text_color=theme.DANGER)
        self.detail.configure(text=message, wraplength=440, justify="left")
        self.close_button.pack(anchor="e", padx=24, pady=(18, 0))


def run(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--install-update", action="store_true")
    parser.add_argument("--target", required=True)
    parser.add_argument("--wait-pid", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--version", required=False, default="")
    args = parser.parse_args(argv)
    window = UpdateInstallerWindow(
        os.path.abspath(sys.executable), args.target, args.wait_pid,
        args.expected_sha256, version=args.version)
    window.mainloop()
    return 1 if window._failed else 0
