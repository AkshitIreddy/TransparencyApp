# Using Transparency App

## First run

1. Launch **TransparencyApp.exe**. The window opens on the **Rules** page and
   a **◐** icon appears in your system tray.
2. Click **＋ Pick a window** and choose one of your open windows (search by
   title or app name). A rule card is created for it.
3. Drag the card's **Opacity** slider down — the matching window becomes
   see-through immediately. The quick **Shades** buttons jump to 25/50/75/100%.

The rule keeps working for windows you open later too, and after you minimise
the app to the tray.

## Rules

Each rule card has:

| Control | What it does |
| --- | --- |
| Enable switch (left) | Turns the rule on/off without deleting it. |
| Pattern box | The text or app name to match. |
| Match mode | **Title contains** / **Title is exactly** / **App (process)**. |
| Opacity slider | 0 % (invisible) to 100 % (normal). |
| Shades | Quick 25 / 50 / 75 / 100 % presets. |
| Click-through | Let mouse clicks pass through to whatever is behind. |
| Always on top | Keep matching windows above others. |
| ✕ | Delete the rule. |

**Tip:** *App (process)* is the most reliable match mode — it targets the
program (e.g. `chrome.exe`) regardless of what its title says.

## Presets

Use the **Presets** bar on the Rules page to **Save as…** the current rules
under a name, then **Apply** to switch between sets (for example a "Work"
preset and a "Gaming" preset).

## Focus mode

**Focus mode** dims every window except the one you're using, and follows you
as you switch windows. Set the focused-window and background opacity on the
**Focus mode** page. It never makes a window fully invisible.

Focus mode is independent of the master transparency switch: turning
transparency off pauses your rules but focus mode keeps working. It is also
remembered across launches, like the screen dimmer.

## Screen dimmer

The **Screen dimmer** lays a soft dark overlay over your monitors to cut glare
in a dark room. It is click-through, so it never gets in your way. Each detected
display has its own dimming slider, so one screen can stay bright while another
is heavily dimmed. Untick a display to leave it completely unchanged. Snipping
Tool and compatible Windows capture apps leave the dimmer out, so screenshots
retain the screen's original, undimmed brightness.

## Updates

Transparency App checks GitHub Releases shortly after startup. When a newer
version is available, it downloads the portable executable in the background,
verifies GitHub's SHA-256 digest, and asks before restarting into the update.
Use **Settings → Updates** to check manually or disable startup checks.

## Global hotkeys

| Default shortcut | Action |
| --- | --- |
| `Ctrl+Alt+T` | Toggle all transparency on/off |
| `Ctrl+Alt+F` | Toggle focus mode |
| `Ctrl+Alt+↑` | Make the focused window more opaque |
| `Ctrl+Alt+↓` | Make the focused window more transparent |
| `Ctrl+Alt+Home` | Restore every window (panic) |

Every shortcut is remappable: in **Settings › Keyboard shortcuts**, click the
one you want to change and press the new combination (it must include Ctrl,
Alt or Shift). Turn hotkeys off entirely in **Settings** if they clash with
another app.

## Settings

- **Theme** — Dark, Light, or follow the system.
- **Accent colour** — pick one of seven accent palettes.
- **Start with Windows** — launch automatically at sign-in.
- **Global hotkeys** — enable/disable the shortcuts above.
- **Export… / Import…** — back up or move your rules and presets.
- **Restore all windows now** — a one-click reset.

## Tray menu

Right-click the tray icon to show the window, toggle transparency or focus
mode, restore all windows, or quit.

## Where settings live

Your configuration is stored at
`%APPDATA%\TransparencyApp\config.json`. Deleting that file resets the app.

## Recovering a stuck window

If a window is left transparent or click-through (for example after a crash),
press **`Ctrl+Alt+Home`**, use **Restore all windows now** in Settings, or just
relaunch the app — it restores windows left over from the previous session.
