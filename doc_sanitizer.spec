# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for doc-sanitizer. Builds a single-file binary on the host OS.

Run:
    pyinstaller doc_sanitizer.spec

Outputs:
    dist/doc-sanitizer       (POSIX)
    dist/doc-sanitizer.exe   (Windows)
    dist/doc-sanitizer.app   (macOS, when --windowed or BUNDLE used below)
"""
import sys
from pathlib import Path

APP_NAME = "doc-sanitizer"
ROOT = Path.cwd()
ENTRY = "doc_sanitizer/cli.py"

# Bundle templates and static assets used by the Flask UI
datas = [
    ("doc_sanitizer/templates", "doc_sanitizer/templates"),
    ("doc_sanitizer/static", "doc_sanitizer/static"),
]

# Hidden imports — keyring backends and cryptography lazily-loaded modules
hiddenimports = [
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.fail",
    "keyring.backends.null",
    "keyring.backends.chainer",
]

a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,           # CLI tool — keep console; UI/API run in foreground
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS .app bundle (only built when running on darwin)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="ai.cogniflow.doc-sanitizer",
        info_plist={
            "CFBundleDisplayName": "Doc Sanitizer",
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "0.2.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
