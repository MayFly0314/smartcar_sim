# -*- mode: python ; coding: utf-8 -*-
# 打包配置：pyinstaller SmartcarSim.spec
# 采用 onedir 模式：QtWebEngine 体积大，onefile 每次启动要解压 200MB+，
# 且 WebEngine 子进程在 onefile 下路径解析易出问题。

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("csim", "csim"),                                   # C harness（运行时编译要用）
        ("assets", "assets"),                               # editor.html + monaco/vs
        ("examples/workspace_demo", "examples/workspace_demo"),  # 首启示例代码
    ],
    hiddenimports=["winpty"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # anaconda 环境里的大件，应用用不到（干净 venv 下本就没有，这里双保险）
        "matplotlib", "scipy", "pandas", "IPython", "jedi", "numba",
        "tkinter", "test", "pydoc_data", "cv2",
        # 注意：不要排除 PySide6.QtQuick/QtQml——QtWebEngine 渲染进程依赖它们
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartcarSim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # 无黑框
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
    upx=False,
    upx_exclude=[],
    name="SmartcarSim",
)
