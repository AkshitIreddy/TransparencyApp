# Building & developing

Transparency App is Windows-only (it uses Win32 layered windows and event
hooks). You need **Python 3.12** on **Windows 10/11**.

## Set up a dev environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run from source

```powershell
python -m transparency_app
```

## Run the tests

The suite creates real Win32 windows, so run it through the sandboxed wrapper,
which launches pytest on a hidden desktop with a hard watchdog (nothing ever
appears on screen or hangs your session):

```powershell
powershell -File scripts\run_tests.ps1
```

Or run pytest directly if you don't mind test windows flashing:

```powershell
pytest tests -v --timeout=60 --timeout-method=thread
```

## Build the executable

```powershell
pyinstaller --clean --noconfirm TransparencyApp.spec
```

The result is `dist\TransparencyApp.exe`. Verify it starts:

```powershell
dist\TransparencyApp.exe --self-test
```

## Releases

Releases are built automatically by GitHub Actions
(`.github/workflows/release.yml`). Pushing a tag that starts with `v` runs the
tests, builds the executable, smoke-tests it, and publishes a GitHub Release
with the `.exe` and a zip attached:

```powershell
git tag v2.0.0
git push origin v2.0.0
```

You can also trigger the workflow manually from the Actions tab with a tag
name.

## Project layout

```
transparency_app/
  winapi.py     Win32 wrappers (ctypes, GIL-releasing) + WinEventHook
  engine.py     Event-driven transparency engine (single worker thread)
  config.py     Rules / presets / settings model, debounced atomic saves
  dimmer.py     Multi-monitor screen-dimming overlay
  hotkeys.py    Global hotkey manager (RegisterHotKey pump thread)
  startup.py    Run-at-startup registry toggle
  paths.py      %APPDATA% paths, logging, v1 migration
  tray.py       System-tray icon
  app.py        Controller wiring everything together
  ui/           CustomTkinter interface (theme, window, rule card, picker)
tests/          pytest suite (real windows, run via scripts/run_tests.ps1)
```
