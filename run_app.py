"""Frozen-app entry point (PyInstaller analyses this).

Kept as a top-level module so PyInstaller has a concrete script to bundle;
it just defers to the package's main().
"""

from transparency_app.__main__ import main

if __name__ == "__main__":
    main()
