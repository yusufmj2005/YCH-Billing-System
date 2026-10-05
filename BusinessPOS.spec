# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build definition for BusinessPOS (one-folder build).
#
# One-folder (dist/BusinessPOS/BusinessPOS.exe + _internal/) is used instead of
# one-file because it starts much faster, is not unpacked to %TEMP% on every
# launch and triggers fewer antivirus false positives. The Inno Setup
# installer ships the whole folder, so end users still get a single
# BusinessPOS-Setup.exe.
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("app")                       # pages are imported lazily
    + collect_submodules("reportlab.graphics.barcode")
    + ["sqlalchemy.dialects.sqlite", "PySide6.QtPdf", "PySide6.QtPrintSupport",
       "bcrypt"]
)

# Qt modules the application does not use (keeps the installer small).
excluded = [
    "tkinter", "pytest", "_pytest", "IPython", "matplotlib", "numpy",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtQml",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtOpenGLWidgets", "PySide6.QtAxContainer", "PySide6.QtConcurrent",
    "PySide6.QtDBus", "PySide6.QtXml",
]

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BusinessPOS",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icons/app.ico",
    version="build/version_info.txt",
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BusinessPOS")
