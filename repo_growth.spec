# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Repo Growth.
# Build locally with:  pyinstaller repo_growth.spec
#
# Windows / Linux -> one-file program:  dist/RepoGrowth.exe  /  dist/RepoGrowth
# macOS           -> app bundle:        dist/RepoGrowth.app
#
# macOS uses onedir + BUNDLE, the supported way to build a .app; PyInstaller
# deprecates onefile + .app. Windows and Linux use onefile so users get a single
# double-clickable program.
#
# The whole templates/ tree (the two HTML templates plus templates/fonts/) is
# bundled so the app's frozen-aware BASE_DIR / TEMPLATES_DIR / FONTS_DIR resolve,
# and assets/ alongside it so the GUI can find the window icon at runtime.
#
# The Windows exe is stamped with the same mark, which is what Explorer, the
# desktop shortcut and the installer show.

import sys

is_macos = sys.platform == 'darwin'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('assets', 'assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

if is_macos:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='RepoGrowth',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='RepoGrowth',
    )
    app = BUNDLE(
        coll,
        name='RepoGrowth.app',
        # PyInstaller converts the PNG to the .icns a bundle needs, which it
        # does with Pillow — see requirements-dev.txt.
        icon='assets/logo.png',
        bundle_identifier='com.repogrowth.app',
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='RepoGrowth',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/logo.ico',
    )
