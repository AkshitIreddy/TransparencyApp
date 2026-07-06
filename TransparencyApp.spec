# PyInstaller spec — builds a single windowed TransparencyApp.exe.
# Build locally with:  pyinstaller TransparencyApp.spec
# CI uses the same spec so local and released binaries match.

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("customtkinter")           # themes / assets
datas += [("assets/icon.ico", "assets")]              # tray + window icon

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=["pystray._win32"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "numpy", "matplotlib", "IPython", "jupyter_client"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TransparencyApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)
