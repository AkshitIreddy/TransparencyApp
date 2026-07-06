"""Event-driven transparency engine.

Replaces the old architecture (a thread re-reading data.json and re-applying
transparency to every window every 100 ms) with:

- a WinEventHook that tells us when windows are created, shown, renamed,
  uncloaked, destroyed or focused, so matching happens only when something
  actually changed;
- a single worker thread that owns every Win32 mutation (no racing threads);
- an applied-state ledger per window (original layered/alpha/topmost state is
  snapshotted before we touch it, so restore puts things back exactly);
- skip-redundant-writes bookkeeping, so an unchanged window is never touched;
- a slow safety-net sweep (every few seconds) to catch anything the hook
  missed, which is nearly free because redundant writes are skipped;
- a crash ledger on disk: if the previous session died without restoring,
  the next launch puts its windows back to normal.
"""

import json
import logging
import os
import queue
import threading

from . import winapi
from .config import MIN_FOCUS_BACKGROUND_ALPHA

log = logging.getLogger("transparency_app.engine")

SWEEP_INTERVAL_SECONDS = 5.0

_CMD_EVENT = "event"
_CMD_SWEEP = "sweep"
_CMD_CONFIG = "config"
_CMD_RESTORE_ALL = "restore_all"
_CMD_OVERRIDE = "override"
_CMD_CLEAR_OVERRIDE = "clear_override"
_CMD_STOP = "stop"


class _WindowState:
    """What a window looked like before we touched it, and what we applied."""

    __slots__ = ("had_layered", "prev_alpha", "was_topmost", "was_click",
                 "alpha", "click", "topmost")

    def __init__(self, hwnd):
        style = winapi.get_window_exstyle(hwnd)
        self.had_layered = bool(style & 0x00080000)   # WS_EX_LAYERED
        self.was_click = bool(style & 0x00000020)     # WS_EX_TRANSPARENT
        self.prev_alpha = winapi.get_window_alpha(hwnd)
        self.was_topmost = winapi.is_topmost(hwnd)
        self.alpha = None      # alpha we applied (None = not yet)
        self.click = self.was_click
        self.topmost = self.was_topmost

    def snapshot(self):
        return {
            "had_layered": self.had_layered,
            "prev_alpha": self.prev_alpha,
            "was_topmost": self.was_topmost,
            "was_click": self.was_click,
        }


class TransparencyEngine:
    def __init__(self, config, ledger_path=None, manage_own_windows=False):
        # manage_own_windows exists for the test suite, which creates its
        # target windows inside the test process itself.
        self._config = config
        self._ledger_path = ledger_path
        self._queue = queue.Queue()
        self._worker = None
        self._hook = winapi.WinEventHook(
            self._on_win_event, skip_own_process=not manage_own_windows)
        self._own_pid = None if manage_own_windows else os.getpid()

        # Owned by the worker thread.
        self._state = {}           # hwnd -> _WindowState
        self._overrides = {}       # hwnd -> alpha from hotkeys (wins over rules)
        self._last_foreground = 0
        self._ledger_dirty = False

        # Read from other threads; written via their setters.
        self.paused = False
        self.focus_mode = False

        config.add_listener(self.notify_config_changed)

    # -- lifecycle -------------------------------------------------------------

    def start(self):
        if self._worker is not None:
            return
        self._recover_previous_session()
        self._worker = threading.Thread(
            target=self._run, name="TransparencyEngine", daemon=True)
        self._worker.start()
        self._hook.start()
        self.request_sweep()

    def stop(self):
        """Stop the engine and restore every window we touched."""
        self._hook.stop()
        if self._worker is None:
            return
        self._queue.put((_CMD_STOP,))
        self._worker.join(timeout=5)
        self._worker = None

    # -- requests from other threads (UI, tray, hotkeys) -------------------------

    def request_sweep(self):
        self._queue.put((_CMD_SWEEP,))

    def notify_config_changed(self):
        self._queue.put((_CMD_CONFIG,))

    def set_paused(self, paused: bool):
        self.paused = bool(paused)
        if self.paused:
            self._queue.put((_CMD_RESTORE_ALL,))
        else:
            self.request_sweep()

    def set_focus_mode(self, enabled: bool):
        self.focus_mode = bool(enabled)
        if not self.focus_mode:
            self._queue.put((_CMD_RESTORE_ALL,))
        self.request_sweep()

    def restore_all(self):
        self._queue.put((_CMD_RESTORE_ALL,))
        self.request_sweep()

    def panic_restore(self):
        """Restore everything and pause: the escape hatch."""
        self.paused = True
        self._queue.put((_CMD_RESTORE_ALL,))

    def set_override(self, hwnd, alpha):
        """Session-only manual opacity for one window (from hotkeys)."""
        self._queue.put((_CMD_OVERRIDE, hwnd, alpha))

    def clear_override(self, hwnd):
        self._queue.put((_CMD_CLEAR_OVERRIDE, hwnd))

    def get_override(self, hwnd):
        return self._overrides.get(hwnd)

    def affected_window_count(self) -> int:
        return sum(1 for s in self._state.values() if s.alpha is not None)

    # -- hook callback (runs on the hook's pump thread; must stay fast) ----------

    def _on_win_event(self, event, hwnd):
        self._queue.put((_CMD_EVENT, event, hwnd))

    # -- worker ------------------------------------------------------------------

    def _run(self):
        while True:
            try:
                cmd = self._queue.get(timeout=SWEEP_INTERVAL_SECONDS)
            except queue.Empty:
                self._sweep()
                self._flush_ledger()
                continue
            try:
                if cmd[0] == _CMD_STOP:
                    self._restore_everything()
                    self._clear_ledger()
                    return
                self._dispatch(cmd)
                # Coalesce bursts (title-change storms): drain what's queued
                # now, dropping duplicate events for the same window.
                seen = {(cmd[1], cmd[2])} if cmd[0] == _CMD_EVENT else set()
                while True:
                    try:
                        nxt = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if nxt[0] == _CMD_STOP:
                        self._restore_everything()
                        self._clear_ledger()
                        return
                    if nxt[0] == _CMD_EVENT:
                        key = (nxt[1], nxt[2])
                        if key in seen:
                            continue
                        seen.add(key)
                    self._dispatch(nxt)
                self._flush_ledger()
            except Exception:
                log.exception("engine command failed")

    def _dispatch(self, cmd):
        kind = cmd[0]
        if kind == _CMD_EVENT:
            self._handle_event(cmd[1], cmd[2])
        elif kind in (_CMD_SWEEP, _CMD_CONFIG):
            self._sweep()
        elif kind == _CMD_RESTORE_ALL:
            self._restore_everything()
        elif kind == _CMD_OVERRIDE:
            self._overrides[cmd[1]] = max(
                MIN_FOCUS_BACKGROUND_ALPHA, min(255, int(cmd[2])))
            self._apply_one(cmd[1])
        elif kind == _CMD_CLEAR_OVERRIDE:
            self._overrides.pop(cmd[1], None)
            self._apply_one(cmd[1])

    def _handle_event(self, event, hwnd):
        if event == winapi.EVENT_OBJECT_DESTROY:
            self._forget(hwnd)
            return
        if self.paused:
            return
        if event == winapi.EVENT_SYSTEM_FOREGROUND:
            previous, self._last_foreground = self._last_foreground, hwnd
            if self.focus_mode:
                # Two windows change roles; no full sweep needed.
                self._apply_one(hwnd)
                if previous and previous != hwnd:
                    self._apply_one(previous)
                return
        self._apply_one(hwnd)

    # -- application logic (worker thread only) -----------------------------------

    def _target_alpha(self, info, foreground_hwnd):
        """What alpha (or None = leave alone/restore) a window should have."""
        override = self._overrides.get(info.hwnd)
        if override is not None:
            return override

        if self.focus_mode:
            fm = self._config.get_setting("focus_mode")
            if info.process in fm.get("exclude", []):
                return None
            rule = self._config.find_matching_rule(info.title, info.process)
            if info.hwnd == foreground_hwnd:
                return rule.opacity if rule else fm["active_opacity"]
            return max(MIN_FOCUS_BACKGROUND_ALPHA, fm["background_opacity"])

        rule = self._config.find_matching_rule(info.title, info.process)
        return rule.opacity if rule else None

    def _apply_one(self, hwnd):
        if not winapi.is_window(hwnd):
            self._forget(hwnd)
            return
        if not winapi.is_app_window(hwnd):
            return
        info = winapi.get_window_info(hwnd)
        if info.pid == self._own_pid:
            return
        # In focus mode, trust the foreground we were told about by events —
        # re-querying live races against fast alt-tabbing.
        if self.focus_mode and self._last_foreground:
            foreground = self._last_foreground
        else:
            foreground = winapi.get_foreground_window()
        self._apply_to(info, foreground)

    def _apply_to(self, info, foreground_hwnd):
        hwnd = info.hwnd
        target = self._target_alpha(info, foreground_hwnd)

        if target is None:
            # Not ours (any more): put it back how it was, if we changed it.
            state = self._state.get(hwnd)
            if state is not None and state.alpha is not None:
                self._restore_one(hwnd, state)
            return

        state = self._state.get(hwnd)
        if state is None:
            state = _WindowState(hwnd)
            self._state[hwnd] = state
            self._ledger_dirty = True

        if state.alpha != target:
            if winapi.set_window_alpha(hwnd, target):
                state.alpha = target

        # Click-through / topmost come from the rule (not overrides/focus mode).
        rule = None
        if not self.focus_mode and self._overrides.get(hwnd) is None:
            rule = self._config.find_matching_rule(info.title, info.process)
        want_click = bool(rule.click_through) if rule else state.was_click
        want_top = bool(rule.topmost) if rule else state.was_topmost
        if state.click != want_click:
            if winapi.set_click_through(hwnd, want_click):
                state.click = want_click
        if state.topmost != want_top:
            if winapi.set_topmost(hwnd, want_top):
                state.topmost = want_top

    def _sweep(self):
        if self.paused:
            return
        foreground = winapi.get_foreground_window()
        if self.focus_mode:
            self._last_foreground = foreground
        for info in winapi.enum_app_windows():
            if info.pid == self._own_pid:
                continue
            self._apply_to(info, foreground)
        for hwnd in list(self._state):
            if not winapi.is_window(hwnd):
                self._forget(hwnd)

    def _restore_one(self, hwnd, state):
        winapi.restore_window(hwnd, state.had_layered, state.prev_alpha)
        if state.click != state.was_click:
            winapi.set_click_through(hwnd, state.was_click)
        if state.topmost != state.was_topmost:
            winapi.set_topmost(hwnd, state.was_topmost)
        self._forget(hwnd)

    def _restore_everything(self):
        for hwnd, state in list(self._state.items()):
            if winapi.is_window(hwnd):
                self._restore_one(hwnd, state)
            else:
                self._forget(hwnd)
        self._overrides.clear()
        self._ledger_dirty = True
        self._flush_ledger()

    def _forget(self, hwnd):
        if self._state.pop(hwnd, None) is not None:
            self._ledger_dirty = True
        self._overrides.pop(hwnd, None)

    # -- crash ledger ---------------------------------------------------------------

    def _flush_ledger(self):
        if not self._ledger_path or not self._ledger_dirty:
            return
        self._ledger_dirty = False
        touched = {
            str(hwnd): state.snapshot()
            for hwnd, state in self._state.items()
            if state.alpha is not None
        }
        try:
            if touched:
                tmp = self._ledger_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"pid": self._own_pid, "windows": touched}, f)
                os.replace(tmp, self._ledger_path)
            else:
                self._clear_ledger()
        except OSError:
            pass

    def _clear_ledger(self):
        if not self._ledger_path:
            return
        try:
            os.remove(self._ledger_path)
        except OSError:
            pass

    def _recover_previous_session(self):
        """If the last session crashed, un-transparent the windows it left."""
        if not self._ledger_path or not os.path.exists(self._ledger_path):
            return
        try:
            with open(self._ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            recovered = 0
            for hwnd_str, snap in data.get("windows", {}).items():
                hwnd = int(hwnd_str)
                # Only touch windows that still exist and are still layered
                # (i.e. plausibly still carrying our alpha).
                if winapi.is_window(hwnd) and winapi.get_window_alpha(hwnd) is not None:
                    winapi.restore_window(
                        hwnd,
                        bool(snap.get("had_layered")),
                        snap.get("prev_alpha"),
                    )
                    if not snap.get("was_click", False):
                        winapi.set_click_through(hwnd, False)
                    recovered += 1
            if recovered:
                log.info("recovered %d windows from previous session", recovered)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self._clear_ledger()
