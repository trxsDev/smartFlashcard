# -*- mode: python ; coding: utf-8 -*-


block_cipher = None

a = Analysis(
    ['../app/main.py'],
    pathex=['../app'],
    binaries=[],
    datas=[
        ('../assets', 'assets'),
        ('../card_images', 'card_images')
    ],
    hiddenimports=[
        'cv2', 'pygame', 'speech_recognition', 'numpy', 'requests'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartFlashCard',
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
    icon='../assets/icons/app.icns'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartFlashCard',
)

app = BUNDLE(
    coll,
    name='SmartFlashCard.app',
    icon='../assets/icons/app.icns',
    bundle_identifier='com.smartflashcard.app',
)
