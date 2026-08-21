# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

## [2.2.2] — 2026-08-21

### Added
- **Visible update notifications** — verified GitHub updates now raise a native
  Windows notification and add an install action to the tray menu. Automatic
  checks no longer force the main window open, while manual checks still offer
  immediate installation.

### Fixed
- **Complete Windows shell dimming** — Start, the taskbar and shell flyouts can
  no longer jump above the screen-dimming overlay when they open or reorder.

## [2.2.1] — 2026-08-21

### Fixed
- **Undimmed screenshots** — Snipping Tool and other Windows capture APIs now
  omit the screen-dimming overlays, so saved screenshots keep their original
  brightness while the physical displays stay comfortably dimmed.

## [2.2.0] — 2026-08-09

### Added
- **Independent dimming per monitor** — every detected display now has its own
  intensity slider and enable checkbox, with values remembered across launches.
- **Automatic updates from GitHub Releases** — the app checks on startup,
  downloads new versions in the background, verifies GitHub's SHA-256 digest,
  and installs after approval with a safe restart-and-rollback helper.
- **Manual update controls** under Settings › Updates, including an option to
  disable automatic startup checks.

## [2.1.2] — 2026-07-11

### Added
- **Per-monitor screen dimmer** — choose which monitors the dimmer covers
  (all, or a specific subset) under Screen dimmer › Screens. Leaving every
  screen ticked also dims monitors you plug in later; the choice is
  remembered across launches. Single-monitor setups are unaffected.

## [2.1.1] — 2026-07-11

### Changed
- **The master transparency switch is remembered across launches** — if you
  turn transparency off, it stays off next time you start the app (it used
  to always come back on). Panic also leaves it off.

## [2.1.0] — 2026-07-10

### Added
- **Remappable keyboard shortcuts** — click any shortcut in Settings and
  press a new combination. Conflicting or already-taken combinations are
  rejected with a message, and one click resets everything to defaults.
- **Accent colour options** — seven accent palettes (blue, purple, green,
  orange, pink, red, teal) selectable in Settings › Appearance.

### Changed
- **Settings persist across launches** — focus mode and the screen dimmer
  now come back exactly as you left them (previously only rules and the
  dimmer intensity were remembered).
- **Focus mode works while transparency is off** — the master switch now only
  pauses per-window rules; focus mode keeps dimming background windows.
  Panic (`Ctrl+Alt+Home`) turns both off.
- **Higher default dimming** — the screen dimmer defaults to 80 % intensity
  (was 60 %).

## [2.0.0] — 2026-07-07

A ground-up rewrite. The single 1,000-line script is now a tested Python
package with an event-driven engine and a modern interface.

### Added
- **Modern UI** — dark, card-based CustomTkinter interface with a sidebar
  (Rules, Focus mode, Screen dimmer, Settings), tooltips, and a guided
  empty state for first-time users.
- **Live window picker** — add a rule by clicking one of your open windows
  instead of typing its exact title.
- **Match modes** — match by window title (contains), exact title, or app
  (process name). Process matching survives title changes.
- **Quick shades** — one-tap 25 / 50 / 75 / 100 % opacity per rule.
- **Presets** — save the current set of rules and switch between them.
- **Per-rule click-through** and **always-on-top**.
- **Global hotkeys** — toggle transparency, toggle focus mode, nudge the
  focused window's opacity up/down, and a panic "restore everything".
- **Run at startup** toggle (per-user, no admin needed).
- **Import / export** all settings as a JSON file.
- **Focus mode** (successor to "ultra mode") with configurable focused and
  background opacity, and a per-app exclude list. It can no longer make a
  window fully invisible.
- **Screen dimmer** now covers every monitor, not just the primary one.
- **Crash recovery** — if the app is killed while windows are transparent,
  the next launch restores them.
- **Automated tests** — 76 tests run against real Windows windows, plus a
  packaged-executable self-test, all in CI.

### Changed
- **Event-driven engine.** The old version re-read `data.json` from disk and
  re-applied transparency to every window ten times a second. The engine now
  reacts to window events (create / show / rename / focus) and only writes
  when something actually changed — near-zero idle CPU, disk, and battery use.
- **No more freezes.** All window calls use GIL-releasing ctypes, so a slow
  or unresponsive target window can never lock up the interface.
- **Config lives in `%APPDATA%\TransparencyApp`** and is saved atomically.
  A `data.json` from v1 is migrated automatically on first run.
- Clean shutdown that restores every window (no more `os._exit`).

### Removed
- The bundled `.exe`, build logs, backups and helper scripts are gone from
  the repository. Releases are built by CI and attached to the
  [Releases page](https://github.com/AkshitIreddy/TransparencyApp/releases).
