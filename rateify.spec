# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# The visualiser and the trace need numpy and pyaudiowpatch. audio.py imports
# both lazily, inside the function that opens the device, so a build without
# them still runs — just without listening.
#
# NB: PyInstaller analyses bytecode, not runtime behaviour, so it finds those
# imports perfectly well despite them being nested inside a function. That means
# leaving them out of hiddenimports does NOT exclude them — an earlier version
# of this flag looked like it worked and quietly shipped numpy anyway. To
# actually drop them they have to be named in `excludes`.
#
# collect_all('numpy') also works but drags numpy's own test suite (and pytest
# with it) into the exe for no reason; the stock hook pulls in what's needed.
#
# Measured on 2.0.0: 29.3MB with audio, 19.5MB without.
audio_excludes = []
if os.environ.get('RATEIFY_NO_AUDIO') or os.environ.get('NOSKIPS_NO_AUDIO'):
    audio_excludes = ['numpy', 'pyaudiowpatch']
else:
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
    ] + audio_excludes,
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
    name='rateify',
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
    icon=['rateify.ico'],
)
