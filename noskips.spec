# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# audio.py imports these lazily, inside the function that opens the device, so
# that a build without them still runs — just without listening. PyInstaller
# can't see a lazy import, so they're named here explicitly.
#
# They cost roughly 15-25MB of exe (almost all numpy). Set NOSKIPS_NO_AUDIO=1
# before building for a smaller exe: the visualiser then reports itself as
# unavailable and the mini bar falls back to the procedural animation.
if not os.environ.get('NOSKIPS_NO_AUDIO'):
    # naming them is enough — PyInstaller ships a hook for numpy that pulls in
    # exactly what's needed. collect_all('numpy') also works but drags numpy's
    # own test suite (and pytest with it) into the exe for no reason.
    hiddenimports += ['pyaudiowpatch', 'numpy']


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # none of these belong in a shipped widget; they ride in on other packages'
    # coat-tails and cost megabytes each. sqlalchemy/alembic are the server's,
    # and the widget only ever imports server.resolve, which is pure stdlib.
    excludes=[
        'pytest', '_pytest', 'pluggy', 'setuptools', 'pip',
        'numpy.testing', 'numpy.typing.mypy_plugin',
        'tkinter', 'pydoc_data', 'sqlalchemy', 'alembic',
    ],
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
    name='noskips',
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
    icon=['noskips.ico'],
)
