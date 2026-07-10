"""Engine behavior against real windows.

Most tests drive the engine synchronously (calling its worker-side methods
directly) for determinism; the integration tests at the bottom run the full
threaded engine with the real WinEventHook.
"""

import json
import time

import pytest

from transparency_app import winapi
from transparency_app.config import ConfigManager, MATCH_PROCESS
from transparency_app.engine import TransparencyEngine

from conftest import wait_for


@pytest.fixture
def config(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    yield cfg
    cfg.close()


@pytest.fixture
def engine(config, tmp_path):
    eng = TransparencyEngine(
        config, ledger_path=str(tmp_path / "session.json"),
        manage_own_windows=True)
    yield eng
    eng._restore_everything()


class TestApplyRules:
    def test_matching_rule_sets_alpha(self, engine, config, native_window):
        config.add_rule(native_window.title, opacity=150)
        engine._apply_one(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == 150

    def test_process_rule_matches(self, engine, config, native_window):
        config.add_rule("python", opacity=140, match_mode=MATCH_PROCESS)
        engine._apply_one(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == 140

    def test_non_matching_window_untouched(self, engine, config, native_window):
        config.add_rule("some other app", opacity=100)
        engine._apply_one(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_rule_removal_restores(self, engine, config, native_window):
        rule = config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == 100

        config.remove_rule(rule.id)
        engine._sweep()
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_opacity_update_reapplies(self, engine, config, native_window):
        rule = config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        config.update_rule(rule.id, opacity=222)
        engine._apply_one(native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == 222

    def test_click_through_and_topmost_flags(self, engine, config, native_window):
        rule = config.add_rule(native_window.title, opacity=200)
        config.update_rule(rule.id, click_through=True, topmost=True)
        engine._apply_one(native_window.hwnd)
        assert winapi.is_click_through(native_window.hwnd)
        assert winapi.is_topmost(native_window.hwnd)

        config.update_rule(rule.id, click_through=False, topmost=False)
        engine._apply_one(native_window.hwnd)
        assert not winapi.is_click_through(native_window.hwnd)
        assert not winapi.is_topmost(native_window.hwnd)

    def test_sweep_applies_to_all_matches(self, engine, config,
                                          native_window, second_window):
        config.add_rule("TA-Test-", opacity=90)
        engine._sweep()
        assert winapi.get_window_alpha(native_window.hwnd) == 90
        assert winapi.get_window_alpha(second_window.hwnd) == 90


class TestPauseRestore:
    def test_pause_restores(self, engine, config, native_window):
        config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        engine.paused = True
        engine._restore_everything()
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_resume_reapplies(self, engine, config, native_window):
        config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        engine.paused = True
        engine._restore_everything()
        engine.paused = False
        engine._sweep()
        assert winapi.get_window_alpha(native_window.hwnd) == 100

    def test_restore_returns_original_topmost(self, engine, config, native_window):
        winapi.set_topmost(native_window.hwnd, True)  # user had it topmost
        rule = config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        config.remove_rule(rule.id)
        engine._sweep()
        assert winapi.is_topmost(native_window.hwnd), \
            "engine should not strip a topmost the user set themselves"


class TestOverrides:
    def test_override_wins_over_rule(self, engine, config, native_window):
        config.add_rule(native_window.title, opacity=100)
        engine._apply_one(native_window.hwnd)
        engine._dispatch(("override", native_window.hwnd, 60))
        assert winapi.get_window_alpha(native_window.hwnd) == 60
        # A sweep must not fight the override back to the rule value.
        engine._sweep()
        assert winapi.get_window_alpha(native_window.hwnd) == 60

    def test_clear_override_returns_to_rule(self, engine, config, native_window):
        config.add_rule(native_window.title, opacity=100)
        engine._dispatch(("override", native_window.hwnd, 60))
        engine._dispatch(("clear_override", native_window.hwnd))
        assert winapi.get_window_alpha(native_window.hwnd) == 100

    def test_override_floor(self, engine, config, native_window):
        engine._dispatch(("override", native_window.hwnd, 0))
        alpha = winapi.get_window_alpha(native_window.hwnd)
        assert alpha is not None and alpha >= 20, \
            "overrides must never make a window fully invisible"


class TestFocusMode:
    def test_focus_mode_dims_background(self, engine, config,
                                        native_window, second_window):
        engine.focus_mode = True
        fm = config.get_setting("focus_mode")
        # Synthetic foreground event: second_window is focused.
        engine._last_foreground = second_window.hwnd
        engine._apply_to(winapi.get_window_info(native_window.hwnd),
                         second_window.hwnd)
        engine._apply_to(winapi.get_window_info(second_window.hwnd),
                         second_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == fm["background_opacity"]
        assert winapi.get_window_alpha(second_window.hwnd) == fm["active_opacity"]

    def test_focus_change_swaps_roles(self, engine, config,
                                      native_window, second_window):
        engine.focus_mode = True
        fm = config.get_setting("focus_mode")
        engine._handle_event(winapi.EVENT_SYSTEM_FOREGROUND, second_window.hwnd)
        engine._handle_event(winapi.EVENT_SYSTEM_FOREGROUND, native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == fm["active_opacity"]
        assert winapi.get_window_alpha(second_window.hwnd) == fm["background_opacity"]

    def test_excluded_process_left_alone(self, engine, config, native_window):
        config.set_setting("focus_mode", {"exclude": ["python.exe", "pythonw.exe"]})
        engine.focus_mode = True
        engine._apply_to(winapi.get_window_info(native_window.hwnd), 0)
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_disable_restores(self, engine, config, native_window):
        engine.focus_mode = True
        engine._apply_to(winapi.get_window_info(native_window.hwnd), 0)
        assert winapi.get_window_alpha(native_window.hwnd) is not None
        engine.focus_mode = False
        engine._restore_everything()
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_zero_opacity_rule_never_hides_focused_window(self, engine, config,
                                                          native_window):
        # A 0% rule on the window you're focused on must not make it invisible.
        config.add_rule(native_window.title, opacity=0)
        engine.focus_mode = True
        engine._last_foreground = native_window.hwnd
        engine._apply_to(winapi.get_window_info(native_window.hwnd),
                         native_window.hwnd)
        alpha = winapi.get_window_alpha(native_window.hwnd)
        assert alpha is not None and alpha >= 20

    def test_focus_mode_still_works_while_paused(self, engine, config,
                                                 native_window, second_window):
        # Pausing transparency turns rules off but focus mode keeps dimming.
        engine.focus_mode = True
        engine.paused = True
        fm = config.get_setting("focus_mode")
        engine._last_foreground = second_window.hwnd
        engine._apply_to(winapi.get_window_info(native_window.hwnd),
                         second_window.hwnd)
        engine._apply_to(winapi.get_window_info(second_window.hwnd),
                         second_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == fm["background_opacity"]
        assert winapi.get_window_alpha(second_window.hwnd) == fm["active_opacity"]

    def test_rules_ignored_while_paused_in_focus_mode(self, engine, config,
                                                      native_window):
        # A rule's opacity must not leak through while paused: the focused
        # window gets focus-mode's active opacity instead.
        config.add_rule(native_window.title, opacity=42)
        engine.focus_mode = True
        engine.paused = True
        fm = config.get_setting("focus_mode")
        engine._last_foreground = native_window.hwnd
        engine._apply_to(winapi.get_window_info(native_window.hwnd),
                         native_window.hwnd)
        assert winapi.get_window_alpha(native_window.hwnd) == fm["active_opacity"]

    def test_paused_without_focus_mode_touches_nothing(self, engine, config,
                                                       native_window):
        config.add_rule(native_window.title, opacity=100)
        engine.paused = True
        engine._apply_one(native_window.hwnd)
        engine._sweep()
        assert winapi.get_window_alpha(native_window.hwnd) is None

    def test_panic_disables_focus_mode(self, engine, native_window):
        engine.focus_mode = True
        engine._apply_to(winapi.get_window_info(native_window.hwnd), 0)
        engine.panic_restore()
        assert engine.paused and not engine.focus_mode

    def test_foreground_tracked_while_paused(self, engine, second_window):
        # A foreground event during pause must still update _last_foreground,
        # so resume doesn't act on a stale value.
        engine.focus_mode = True
        engine.paused = True
        engine._handle_event(winapi.EVENT_SYSTEM_FOREGROUND, second_window.hwnd)
        assert engine._last_foreground == second_window.hwnd


class TestCrashLedger:
    def test_ledger_written_and_recovered(self, config, tmp_path, native_window):
        ledger = str(tmp_path / "session.json")
        eng = TransparencyEngine(config, ledger_path=ledger,
                                 manage_own_windows=True)
        config.add_rule(native_window.title, opacity=90)
        eng._apply_one(native_window.hwnd)
        eng._ledger_dirty = True
        eng._flush_ledger()
        with open(ledger, encoding="utf-8") as f:
            data = json.load(f)
        assert str(native_window.hwnd) in data["windows"]
        assert winapi.get_window_alpha(native_window.hwnd) == 90

        # Simulate a crash: no restore, new engine instance starts up.
        eng2 = TransparencyEngine(config, ledger_path=ledger,
                                  manage_own_windows=True)
        eng2._recover_previous_session()
        assert winapi.get_window_alpha(native_window.hwnd) is None
        assert not (tmp_path / "session.json").exists()

    def test_recovery_skips_hwnd_with_mismatched_identity(self, config, tmp_path,
                                                          native_window):
        # Simulate a crash ledger whose entry points at this HWND but records a
        # DIFFERENT window's identity (as if the HWND had been recycled).
        ledger = str(tmp_path / "session.json")
        winapi.set_window_alpha(native_window.hwnd, 90)  # pretend it's ours
        with open(ledger, "w", encoding="utf-8") as f:
            json.dump({"pid": 1, "windows": {str(native_window.hwnd): {
                "had_layered": False, "prev_alpha": None, "was_topmost": False,
                "was_click": False, "process": "someone-else.exe",
                "title": "A Totally Different Window"}}}, f)
        eng = TransparencyEngine(config, ledger_path=ledger,
                                 manage_own_windows=True)
        eng._recover_previous_session()
        # Identity didn't match, so our window must be left as-is (still 90).
        assert winapi.get_window_alpha(native_window.hwnd) == 90
        winapi.restore_window(native_window.hwnd)

    def test_recovery_restores_topmost(self, config, tmp_path, native_window):
        ledger = str(tmp_path / "session.json")
        info = winapi.get_window_info(native_window.hwnd)
        winapi.set_window_alpha(native_window.hwnd, 90)
        winapi.set_topmost(native_window.hwnd, True)  # left topmost by "crash"
        with open(ledger, "w", encoding="utf-8") as f:
            json.dump({"pid": 1, "windows": {str(native_window.hwnd): {
                "had_layered": False, "prev_alpha": None, "was_topmost": False,
                "was_click": False, "process": info.process,
                "title": info.title}}}, f)
        eng = TransparencyEngine(config, ledger_path=ledger,
                                 manage_own_windows=True)
        eng._recover_previous_session()
        assert winapi.get_window_alpha(native_window.hwnd) is None
        assert not winapi.is_topmost(native_window.hwnd)

    def test_clean_stop_clears_ledger(self, config, tmp_path, native_window):
        ledger = str(tmp_path / "session.json")
        eng = TransparencyEngine(config, ledger_path=ledger,
                                 manage_own_windows=True)
        config.add_rule(native_window.title, opacity=90)
        eng.start()
        try:
            assert wait_for(
                lambda: winapi.get_window_alpha(native_window.hwnd) == 90)
        finally:
            eng.stop()
        assert winapi.get_window_alpha(native_window.hwnd) is None
        assert not (tmp_path / "session.json").exists()


class TestIntegrationThreaded:
    """Full engine with real hooks: the paths users actually exercise."""

    def _wait_alpha(self, hwnd, value, timeout=12.0):
        return wait_for(lambda: winapi.get_window_alpha(hwnd) == value, timeout)

    def test_new_window_gets_alpha_via_events(self, engine, config, make_window):
        config.add_rule("TA-Test-", opacity=123)
        engine.start()
        try:
            w = make_window()  # created AFTER engine start: only events see it
            assert self._wait_alpha(w.hwnd, 123), \
                "event-driven engine failed to catch a brand-new window"
        finally:
            engine.stop()

    def test_title_change_triggers_match(self, engine, config, make_window):
        config.add_rule("MagicTitleXYZ", opacity=111)
        engine.start()
        try:
            w = make_window()
            time.sleep(0.4)  # let events settle
            assert winapi.get_window_alpha(w.hwnd) is None
            w.set_title("Now Contains MagicTitleXYZ Somewhere")
            assert self._wait_alpha(w.hwnd, 111), \
                "rename event did not trigger re-match"
        finally:
            engine.stop()

    def test_pause_resume_cycle(self, engine, config, make_window):
        w = make_window()
        config.add_rule(w.title, opacity=100)
        engine.start()
        try:
            assert self._wait_alpha(w.hwnd, 100)
            engine.set_paused(True)
            assert wait_for(
                lambda: winapi.get_window_alpha(w.hwnd) is None), \
                "pause did not restore the window"
            engine.set_paused(False)
            assert self._wait_alpha(w.hwnd, 100)
        finally:
            engine.stop()

    def test_stop_restores_everything(self, engine, config, make_window):
        w1, w2 = make_window(), make_window()
        config.add_rule("TA-Test-", opacity=80)
        engine.start()
        try:
            assert self._wait_alpha(w1.hwnd, 80)
            assert self._wait_alpha(w2.hwnd, 80)
        finally:
            engine.stop()
        assert winapi.get_window_alpha(w1.hwnd) is None
        assert winapi.get_window_alpha(w2.hwnd) is None
