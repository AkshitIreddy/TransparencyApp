import json
import os
import time

import pytest

from transparency_app.config import (
    ConfigManager, Rule, MATCH_PROCESS, MATCH_TITLE, MATCH_TITLE_EXACT,
    MIN_FOCUS_BACKGROUND_ALPHA,
)


@pytest.fixture
def config(tmp_path):
    return ConfigManager(str(tmp_path / "config.json"))


class TestRuleMatching:
    def test_title_substring_case_insensitive(self):
        rule = Rule("visual studio code", match_mode=MATCH_TITLE)
        assert rule.matches("main.py - Visual Studio Code", "code.exe")
        assert not rule.matches("Notepad", "notepad.exe")

    def test_title_exact(self):
        rule = Rule("Calculator", match_mode=MATCH_TITLE_EXACT)
        assert rule.matches("calculator", "calc.exe")
        assert not rule.matches("Calculator - solar", "calc.exe")

    def test_process_match_appends_exe(self):
        rule = Rule("Code", match_mode=MATCH_PROCESS)
        assert rule.matches("anything at all", "code.exe")
        assert not rule.matches("Code", "chrome.exe")

    def test_process_match_with_exe_suffix(self):
        rule = Rule("chrome.EXE", match_mode=MATCH_PROCESS)
        assert rule.matches("", "chrome.exe")

    def test_opacity_clamped(self):
        assert Rule("x", opacity=999).opacity == 255
        assert Rule("x", opacity=-5).opacity == 0
        assert Rule("x", opacity="junk").opacity == 220


class TestPersistence:
    def test_defaults_when_missing(self, config):
        assert config.get_rules() == []
        assert config.get_setting("theme") == "dark"

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "config.json")
        cfg = ConfigManager(path)
        rule = cfg.add_rule("notepad", opacity=200)
        cfg.save_preset("My preset")
        cfg.set_setting("theme", "light")
        cfg.close()

        fresh = ConfigManager(path)
        assert len(fresh.get_rules()) == 1
        assert fresh.get_rules()[0].pattern == "notepad"
        assert fresh.get_rules()[0].opacity == 200
        assert fresh.get_rules()[0].id == rule.id
        assert fresh.list_presets() == ["My preset"]
        assert fresh.get_setting("theme") == "light"

    def test_v1_migration(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"windows": {"visual studio code": 230,
                                                "notepad": 180}}))
        cfg = ConfigManager(str(path))
        rules = cfg.get_rules()
        assert len(rules) == 2
        patterns = {r.pattern: r.opacity for r in rules}
        assert patterns == {"visual studio code": 230, "notepad": 180}
        assert all(r.match_mode == MATCH_TITLE for r in rules)

    def test_corrupt_file_recovers(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{not json at all")
        cfg = ConfigManager(str(path))
        assert cfg.get_rules() == []
        assert (tmp_path / "config.json.corrupt").exists()

    def test_debounced_save(self, config):
        config.SAVE_DELAY_SECONDS = 0.1
        config.add_rule("one")
        # File may not exist yet (debounce), but must exist after the delay.
        time.sleep(0.5)
        assert os.path.exists(config.path)
        with open(config.path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["rules"][0]["pattern"] == "one"

    def test_atomic_save_leaves_no_tmp(self, config):
        config.add_rule("x")
        config.close()
        assert not os.path.exists(config.path + ".tmp")


class TestRulesCrud:
    def test_add_empty_pattern_rejected(self, config):
        assert config.add_rule("   ") is None
        assert config.get_rules() == []

    def test_update(self, config):
        rule = config.add_rule("chrome")
        assert config.update_rule(rule.id, opacity=128, click_through=True,
                                  match_mode=MATCH_PROCESS)
        updated = config.get_rule(rule.id)
        assert updated.opacity == 128
        assert updated.click_through is True
        assert updated.match_mode == MATCH_PROCESS

    def test_update_unknown_id(self, config):
        assert not config.update_rule("nope", opacity=1)

    def test_remove(self, config):
        rule = config.add_rule("chrome")
        assert config.remove_rule(rule.id)
        assert config.get_rules() == []
        assert not config.remove_rule(rule.id)

    def test_first_matching_rule_wins(self, config):
        config.add_rule("stack", opacity=100)
        config.add_rule("overflow", opacity=50)
        match = config.find_matching_rule("stack overflow - chrome", "chrome.exe")
        assert match.opacity == 100

    def test_disabled_rule_ignored(self, config):
        rule = config.add_rule("chrome", opacity=100)
        config.update_rule(rule.id, enabled=False)
        assert config.find_matching_rule("chrome", "chrome.exe") is None


class TestPresets:
    def test_save_apply_delete(self, config):
        config.add_rule("chrome", opacity=100)
        assert config.save_preset("Work")
        config.add_rule("spotify", opacity=50)
        assert config.save_preset("Music")

        assert config.apply_preset("Work")
        assert [r.pattern for r in config.get_rules()] == ["chrome"]
        assert config.apply_preset("Music")
        assert sorted(r.pattern for r in config.get_rules()) == ["chrome", "spotify"]

        assert config.delete_preset("Work")
        assert config.list_presets() == ["Music"]
        assert not config.apply_preset("Work")

    def test_blank_name_rejected(self, config):
        assert not config.save_preset("  ")


class TestImportExport:
    def test_round_trip(self, config, tmp_path):
        config.add_rule("chrome", opacity=77)
        config.save_preset("P1")
        out = str(tmp_path / "export.json")
        assert config.export_to(out)

        other = ConfigManager(str(tmp_path / "other.json"))
        assert other.import_from(out)
        assert other.get_rules()[0].pattern == "chrome"
        assert other.get_rules()[0].opacity == 77
        assert other.list_presets() == ["P1"]

    def test_import_v1_file(self, config, tmp_path):
        legacy = tmp_path / "old.json"
        legacy.write_text(json.dumps({"windows": {"notepad": 150}}))
        assert config.import_from(str(legacy))
        assert config.get_rules()[0].pattern == "notepad"

    def test_import_garbage_fails_cleanly(self, config, tmp_path):
        config.add_rule("keepme")
        bad = tmp_path / "bad.json"
        bad.write_text("[1,2,3]")
        assert not config.import_from(str(bad))
        assert config.get_rules()[0].pattern == "keepme"

    def test_import_missing_file(self, config):
        assert not config.import_from("Z:/does/not/exist.json")


class TestSettings:
    def test_focus_background_floor(self, config):
        config.set_setting("focus_mode", {"background_opacity": 1})
        assert (config.get_setting("focus_mode")["background_opacity"]
                >= MIN_FOCUS_BACKGROUND_ALPHA)

    def test_invalid_theme_rejected(self, config):
        config.set_setting("theme", "neon")
        assert config.get_setting("theme") == "dark"

    def test_focus_exclude_normalized(self, config):
        config.set_setting("focus_mode", {"exclude": ["Chrome.EXE", ""]})
        assert config.get_setting("focus_mode")["exclude"] == ["chrome.exe"]

    def test_dimmer_defaults(self, config):
        assert config.get_setting("dimmer_intensity") == 160
        assert config.get_setting("dimmer_enabled") is False
        assert config.get_setting("dimmer_monitors") == "all"

    def test_dimmer_monitors_persist(self, tmp_path):
        path = str(tmp_path / "config.json")
        cfg = ConfigManager(path)
        cfg.set_setting("dimmer_monitors", ["\\\\.\\DISPLAY2", " "])
        cfg.close()
        fresh = ConfigManager(path)
        # Blank entries dropped; the real device name kept.
        assert fresh.get_setting("dimmer_monitors") == ["\\\\.\\DISPLAY2"]

    def test_dimmer_monitors_bad_value_falls_back_to_all(self, config):
        config.set_setting("dimmer_monitors", "garbage")
        assert config.get_setting("dimmer_monitors") == "all"

    def test_toggles_persist(self, tmp_path):
        path = str(tmp_path / "config.json")
        cfg = ConfigManager(path)
        cfg.set_setting("dimmer_enabled", True)
        cfg.set_setting("focus_mode", {"enabled": True})
        cfg.set_setting("accent", "teal")
        cfg.set_setting("transparency_on", False)
        cfg.close()

        fresh = ConfigManager(path)
        assert fresh.get_setting("dimmer_enabled") is True
        assert fresh.get_setting("focus_mode")["enabled"] is True
        assert fresh.get_setting("accent") == "teal"
        assert fresh.get_setting("transparency_on") is False

    def test_transparency_defaults_on(self, config):
        assert config.get_setting("transparency_on") is True

    def test_invalid_accent_rejected(self, config):
        config.set_setting("accent", "hotdog")
        assert config.get_setting("accent") == "blue"

    def test_hotkey_overrides_persist(self, tmp_path):
        path = str(tmp_path / "config.json")
        cfg = ConfigManager(path)
        cfg.set_setting("hotkeys", {"toggle_focus": "Ctrl+Shift+F9", "bad": " "})
        cfg.close()

        fresh = ConfigManager(path)
        hot = fresh.get_setting("hotkeys")
        assert hot == {"toggle_focus": "ctrl+shift+f9"}
