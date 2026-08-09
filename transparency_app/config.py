"""Configuration model and persistence.

The old app re-read data.json from disk ten times a second. Here the config
lives in memory, notifies listeners on change, and writes to disk atomically
on a short debounce. The v1 format ({"windows": {title: alpha}}) is migrated
in place on first load.
"""

import copy
import json
import os
import threading
import uuid

CONFIG_VERSION = 2

MATCH_TITLE = "title"           # case-insensitive substring of window title
MATCH_TITLE_EXACT = "title_exact"
MATCH_PROCESS = "process"       # executable name, e.g. "code.exe"
MATCH_MODES = (MATCH_TITLE, MATCH_TITLE_EXACT, MATCH_PROCESS)

# Focus mode must never make windows fully invisible (the old "ultra mode"
# set background windows to alpha 0, which stranded users).
MIN_FOCUS_BACKGROUND_ALPHA = 20
MIN_RULE_ALPHA = 0
MAX_ALPHA = 255

DEFAULT_SETTINGS = {
    "theme": "dark",                 # dark | light | system
    "accent": "blue",                # key into theme.ACCENTS
    "transparency_on": True,         # master switch (engine not paused)
    "hotkeys_enabled": True,
    "start_minimized": False,
    "focus_mode": {
        "enabled": False,
        "active_opacity": 255,
        "background_opacity": 120,
        "exclude": [],               # process names to leave alone
    },
    "dimmer_intensity": 160,         # 0..200
    "dimmer_intensities": {},        # monitor device name -> 0..200
    "dimmer_enabled": False,
    "dimmer_monitors": "all",        # "all" or list of monitor device names
    "hotkeys": {},                   # action -> combo string overrides
}

ACCENT_NAMES = ("blue", "purple", "green", "orange", "pink", "red", "teal")


def _clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


class Rule:
    """One transparency rule: what to match and how to treat it."""

    def __init__(self, pattern, opacity=220, match_mode=MATCH_TITLE,
                 enabled=True, click_through=False, topmost=False, rule_id=None):
        self.id = rule_id or uuid.uuid4().hex[:12]
        self.pattern = str(pattern).strip()
        self.opacity = _clamp(opacity, MIN_RULE_ALPHA, MAX_ALPHA, 220)
        self.match_mode = match_mode if match_mode in MATCH_MODES else MATCH_TITLE
        self.enabled = bool(enabled)
        self.click_through = bool(click_through)
        self.topmost = bool(topmost)

    def matches(self, title: str, process: str) -> bool:
        if not self.pattern:
            return False
        if self.match_mode == MATCH_PROCESS:
            pat = self.pattern.lower()
            if not pat.endswith(".exe"):
                pat += ".exe"
            return process == pat
        if self.match_mode == MATCH_TITLE_EXACT:
            return title.lower() == self.pattern.lower()
        return self.pattern.lower() in title.lower()

    def to_dict(self):
        return {
            "id": self.id,
            "pattern": self.pattern,
            "match_mode": self.match_mode,
            "opacity": self.opacity,
            "enabled": self.enabled,
            "click_through": self.click_through,
            "topmost": self.topmost,
        }

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or not str(d.get("pattern", "")).strip():
            return None
        return cls(
            pattern=d.get("pattern", ""),
            opacity=d.get("opacity", 220),
            match_mode=d.get("match_mode", MATCH_TITLE),
            enabled=d.get("enabled", True),
            click_through=d.get("click_through", False),
            topmost=d.get("topmost", False),
            rule_id=str(d["id"]) if d.get("id") else None,
        )


def _validate_settings(raw):
    """Merge raw settings over defaults, clamping numeric fields."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings
    if raw.get("theme") in ("dark", "light", "system"):
        settings["theme"] = raw["theme"]
    if raw.get("accent") in ACCENT_NAMES:
        settings["accent"] = raw["accent"]
    settings["transparency_on"] = bool(raw.get("transparency_on", True))
    settings["hotkeys_enabled"] = bool(raw.get("hotkeys_enabled", True))
    settings["start_minimized"] = bool(raw.get("start_minimized", False))
    settings["dimmer_intensity"] = _clamp(raw.get("dimmer_intensity"), 0, 200, 160)
    dimmer_intensities = raw.get("dimmer_intensities")
    if isinstance(dimmer_intensities, dict):
        settings["dimmer_intensities"] = {
            str(name): _clamp(value, 0, 200, settings["dimmer_intensity"])
            for name, value in dimmer_intensities.items()
            if str(name).strip()
        }
    settings["dimmer_enabled"] = bool(raw.get("dimmer_enabled", False))
    dm = raw.get("dimmer_monitors", "all")
    if isinstance(dm, (list, tuple)):
        settings["dimmer_monitors"] = [str(x) for x in dm if str(x).strip()]
    else:
        settings["dimmer_monitors"] = "all"
    hotkeys = raw.get("hotkeys")
    if isinstance(hotkeys, dict):
        settings["hotkeys"] = {
            str(action): str(combo).strip().lower()
            for action, combo in hotkeys.items()
            if str(combo).strip()
        }
    fm = raw.get("focus_mode") if isinstance(raw.get("focus_mode"), dict) else {}
    settings["focus_mode"]["enabled"] = bool(fm.get("enabled", False))
    settings["focus_mode"]["active_opacity"] = _clamp(
        fm.get("active_opacity"), MIN_FOCUS_BACKGROUND_ALPHA, MAX_ALPHA, 255)
    settings["focus_mode"]["background_opacity"] = _clamp(
        fm.get("background_opacity"), MIN_FOCUS_BACKGROUND_ALPHA, MAX_ALPHA, 120)
    exclude = fm.get("exclude")
    if isinstance(exclude, list):
        settings["focus_mode"]["exclude"] = [
            str(p).lower() for p in exclude if str(p).strip()
        ]
    return settings


class ConfigManager:
    """Thread-safe in-memory config with debounced atomic persistence."""

    SAVE_DELAY_SECONDS = 0.5

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._save_timer = None
        self._listeners = []
        self.rules = []
        self.presets = {}          # name -> [rule dicts]
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    # -- change notification --------------------------------------------------

    def add_listener(self, fn):
        """fn() is called (on the mutating thread) after any config change."""
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # -- load / save -----------------------------------------------------------

    def load(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {}
            except (json.JSONDecodeError, OSError):
                # Keep the corrupt file for forensics, then start fresh.
                try:
                    os.replace(self.path, self.path + ".corrupt")
                except OSError:
                    pass
                data = {}

            if not isinstance(data, dict):
                data = {}

            if "windows" in data and "rules" not in data:
                data = self._migrate_v1(data)

            self.rules = []
            for raw in data.get("rules", []) if isinstance(data.get("rules"), list) else []:
                rule = Rule.from_dict(raw)
                if rule:
                    self.rules.append(rule)

            self.presets = {}
            raw_presets = data.get("presets")
            if isinstance(raw_presets, dict):
                for name, rules in raw_presets.items():
                    if isinstance(rules, list):
                        clean = [r.to_dict() for r in
                                 (Rule.from_dict(x) for x in rules) if r]
                        self.presets[str(name)] = clean

            self.settings = _validate_settings(data.get("settings"))

    @staticmethod
    def _migrate_v1(data):
        """v1: {"windows": {title_fragment: alpha}} -> v2 rules."""
        rules = []
        windows = data.get("windows")
        if isinstance(windows, dict):
            for pattern, alpha in windows.items():
                if str(pattern).strip():
                    rules.append(Rule(pattern=pattern, opacity=_clamp(
                        alpha, MIN_RULE_ALPHA, MAX_ALPHA, 220)).to_dict())
        return {"version": CONFIG_VERSION, "rules": rules}

    def _snapshot(self):
        return {
            "version": CONFIG_VERSION,
            "rules": [r.to_dict() for r in self.rules],
            "presets": copy.deepcopy(self.presets),
            "settings": copy.deepcopy(self.settings),
        }

    def save_now(self):
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            data = self._snapshot()
        # A per-write unique temp name so an already-fired debounce timer and
        # close()/save_now() on another thread can never truncate each other's
        # temp file mid os.replace (which on Windows corrupts the target).
        tmp_path = f"{self.path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except OSError:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def save_soon(self):
        """Debounced save: many slider ticks collapse into one disk write."""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self.SAVE_DELAY_SECONDS, self.save_now)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _changed(self):
        self.save_soon()
        self._notify()

    # -- rules -----------------------------------------------------------------

    def get_rules(self):
        with self._lock:
            return list(self.rules)

    def get_rule(self, rule_id):
        with self._lock:
            for r in self.rules:
                if r.id == rule_id:
                    return r
        return None

    def add_rule(self, pattern, opacity=220, match_mode=MATCH_TITLE) -> Rule:
        rule = Rule(pattern=pattern, opacity=opacity, match_mode=match_mode)
        if not rule.pattern:
            return None
        with self._lock:
            self.rules.append(rule)
        self._changed()
        return rule

    def update_rule(self, rule_id, **fields) -> bool:
        with self._lock:
            rule = self.get_rule(rule_id)
            if rule is None:
                return False
            if "pattern" in fields:
                pattern = str(fields["pattern"]).strip()
                if pattern:
                    rule.pattern = pattern
            if "opacity" in fields:
                rule.opacity = _clamp(fields["opacity"], MIN_RULE_ALPHA, MAX_ALPHA,
                                      rule.opacity)
            if "match_mode" in fields and fields["match_mode"] in MATCH_MODES:
                rule.match_mode = fields["match_mode"]
            for flag in ("enabled", "click_through", "topmost"):
                if flag in fields:
                    setattr(rule, flag, bool(fields[flag]))
        self._changed()
        return True

    def remove_rule(self, rule_id) -> bool:
        with self._lock:
            before = len(self.rules)
            self.rules = [r for r in self.rules if r.id != rule_id]
            removed = len(self.rules) != before
        if removed:
            self._changed()
        return removed

    def find_matching_rule(self, title, process):
        """First enabled rule matching a window, or None."""
        with self._lock:
            for rule in self.rules:
                if rule.enabled and rule.matches(title, process):
                    return rule
        return None

    # -- presets -----------------------------------------------------------------

    def save_preset(self, name) -> bool:
        name = str(name).strip()
        if not name:
            return False
        with self._lock:
            self.presets[name] = [r.to_dict() for r in self.rules]
        self._changed()
        return True

    def apply_preset(self, name) -> bool:
        with self._lock:
            rules = self.presets.get(name)
            if rules is None:
                return False
            self.rules = [r for r in (Rule.from_dict(d) for d in rules) if r]
        self._changed()
        return True

    def delete_preset(self, name) -> bool:
        with self._lock:
            if name not in self.presets:
                return False
            del self.presets[name]
        self._changed()
        return True

    def list_presets(self):
        with self._lock:
            return sorted(self.presets.keys())

    # -- settings ----------------------------------------------------------------

    def get_setting(self, key, default=None):
        with self._lock:
            return copy.deepcopy(self.settings.get(key, default))

    def set_setting(self, key, value):
        with self._lock:
            if key == "focus_mode" and isinstance(value, dict):
                merged = self.settings["focus_mode"] | value
                self.settings = _validate_settings(
                    {**self.settings, "focus_mode": merged})
            else:
                self.settings = _validate_settings({**self.settings, key: value})
        self._changed()

    # -- import / export -----------------------------------------------------------

    def export_to(self, path) -> bool:
        try:
            with self._lock:
                data = self._snapshot()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except OSError:
            return False

    def import_from(self, path) -> bool:
        """Replace current rules/presets/settings from an exported file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict):
            return False
        if "windows" in data and "rules" not in data:
            data = self._migrate_v1(data)
        if not isinstance(data.get("rules"), list):
            return False
        with self._lock:
            self.rules = [r for r in (Rule.from_dict(d) for d in data["rules"]) if r]
            self.presets = {}
            if isinstance(data.get("presets"), dict):
                for name, rules in data["presets"].items():
                    if isinstance(rules, list):
                        self.presets[str(name)] = [
                            r.to_dict() for r in
                            (Rule.from_dict(x) for x in rules) if r]
            self.settings = _validate_settings(data.get("settings"))
        self._changed()
        return True

    def close(self):
        """Flush any pending debounced save."""
        with self._lock:
            timer = self._save_timer
            self._save_timer = None
        if timer is not None:
            timer.cancel()
        self.save_now()
