# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("httpx")
hiddenimports += collect_submodules("zmq")
hiddenimports += collect_submodules("PySide6.QtWebEngineCore")
hiddenimports += collect_submodules("PySide6.QtWebEngineWidgets")

binaries = []
binaries += collect_dynamic_libs("zmq")

datas = []
datas += collect_data_files("certifi")
datas += [
    ("app\\templates", "app\\templates"),
    ("app\\static", "app\\static"),
]


a = Analysis(
    ["elite_plug_desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Elite55",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
