"""Central palette, fonts and spacing so every widget reads consistently."""

import customtkinter as ctk

# Accent palettes: name -> (accent, hover, muted). "muted" is the dark
# tint used for active nav / secondary buttons.
ACCENTS = {
    "blue":   ("#5B8CFF", "#4577E6", "#2E3A57"),
    "purple": ("#A06BFF", "#8A55E6", "#3B2E57"),
    "green":  ("#3FB950", "#2EA043", "#24402A"),
    "orange": ("#F0883E", "#D9752F", "#4A3423"),
    "pink":   ("#F065B8", "#D9509F", "#4A2A3D"),
    "red":    ("#E5534B", "#C4443C", "#472A28"),
    "teal":   ("#2DBFB8", "#22A39D", "#1F3D3B"),
}
DEFAULT_ACCENT = "blue"

# Accent used for primary actions, active nav, slider fill. Mutated by
# set_accent(); widgets read these at build time, so pages are rebuilt
# after a change.
ACCENT, ACCENT_HOVER, ACCENT_MUTED = ACCENTS[DEFAULT_ACCENT]


def set_accent(name: str):
    """Switch the module-level accent palette. Unknown names -> default."""
    global ACCENT, ACCENT_HOVER, ACCENT_MUTED
    ACCENT, ACCENT_HOVER, ACCENT_MUTED = ACCENTS.get(
        name, ACCENTS[DEFAULT_ACCENT])

DANGER = "#E5534B"
DANGER_HOVER = "#C4443C"
SUCCESS = "#3FB950"

# Surfaces (dark). CustomTkinter accepts (light, dark) tuples; we lead with a
# light value so a future light theme still looks reasonable.
BG = ("#F2F3F5", "#15171C")
SURFACE = ("#FFFFFF", "#1D2027")
SURFACE_2 = ("#E9EBEF", "#252932")
BORDER = ("#D5D8DE", "#2E333D")
CARD = ("#FFFFFF", "#20242C")

TEXT = ("#1A1C20", "#E6E8EC")
TEXT_MUTED = ("#6B7280", "#8A909C")

RADIUS = 12
RADIUS_SM = 8
PAD = 16
GAP = 10


def font(size=13, weight="normal"):
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


def h1():
    return font(22, "bold")


def h2():
    return font(16, "bold")


def body():
    return font(13)


def small():
    return font(11)


def apply_appearance(mode: str):
    """mode: 'dark' | 'light' | 'system'."""
    ctk.set_appearance_mode(mode if mode in ("dark", "light", "system") else "dark")
