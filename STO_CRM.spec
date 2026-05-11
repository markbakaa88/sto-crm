# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['sto_crm.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('sto_crm/assets/__init__.py', 'sto_crm/assets'),
        ('sto_crm/assets/index.html', 'sto_crm/assets'),
        ('sto_crm/assets/app.css', 'sto_crm/assets'),
        ('sto_crm/assets/app.js', 'sto_crm/assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='STO_CRM',
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
