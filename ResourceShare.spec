# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'psutil',
    'customtkinter',
    'resource_share',
    'resource_share.ui',
    'resource_share.service',
    'resource_share.inventory',
    'resource_share.models',
    'resource_share.certificate',
    'resource_share.matching',
    'resource_share.bootstrap',
    'resource_share.components',
    'resource_share.compute',
    'resource_share.compute.base',
    'resource_share.compute.factory',
    'resource_share.compute.local',
    'resource_share.compute.docker',
    'resource_share.compute.kubernetes',
    'resource_share.network',
    'resource_share.network.server',
    'resource_share.network.client',
    'resource_share.network.tunnel',
    'resource_share.ports',
]

tmp_ctk = collect_all('customtkinter')
datas += tmp_ctk[0]; binaries += tmp_ctk[1]; hiddenimports += tmp_ctk[2]

tmp_rs = collect_all('resource_share')
datas += tmp_rs[0]; binaries += tmp_rs[1]; hiddenimports += tmp_rs[2]



a = Analysis(
    ['main.py'],
    pathex=[],
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
    name='ResourceShare',
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
)
