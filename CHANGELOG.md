# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[semantic versioning](https://semver.org/).

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
