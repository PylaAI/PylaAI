# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for PylaAI.

Produces a single windowed Windows executable (PylaAI.exe) with the app icon,
bundling the web UI, configs, models and the scrcpy server jar. Build with:

    pyinstaller PylaAI.spec

Run on Windows: PyInstaller does not cross-compile, so the .exe must be built
from a Windows machine.
"""

from PyInstaller.utils.hooks import collect_submodules

# Data folders shipped alongside the code. (source, destination-in-bundle)
datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("cfg", "cfg"),
    ("images", "images"),
    ("models", "models"),
    ("playstyles", "playstyles"),
    ("api/assets", "api/assets"),
    ("scrcpy/scrcpy-server.jar", "scrcpy"),
]

# Modules PyInstaller's static analysis tends to miss.
hiddenimports = (
    collect_submodules("webview")
    + collect_submodules("easyocr")
    + ["pyla_discord_auth", "desktop_window"]
)

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PylaAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    # console=True keeps the log window; set to False for a pure GUI app.
    console=True,
    disable_windowed_traceback=False,
    icon="images/logo.ico",
)
