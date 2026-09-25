# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 app.py、resource 资源包与 MaaFramework 一起打包。

一般不需要直接调用，用 ``powershell -File .\build_exe.ps1`` 即可。
手动打包：

    python -m PyInstaller .\Myhero.spec --noconfirm

默认产出单文件 ``dist/勇者邦邦.exe``；把环境变量 ``MYHERO_ONEFILE`` 设为 ``0``
则产出目录版 ``dist/勇者邦邦/勇者邦邦.exe``（启动更快，但依赖文件较多）。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve()
ONEFILE = os.environ.get("MYHERO_ONEFILE", "1") != "0"
APP_NAME = os.environ.get("MYHERO_NAME", "勇者邦邦")
# 排错用：``MYHERO_CONSOLE=1`` 会保留控制台并打印 Python 异常。
CONSOLE = os.environ.get("MYHERO_CONSOLE", "0") == "1"

# 运行时通过 ``sys._MEIPASS / resource`` 读取，打包时必须带上整个资源包。
datas = [(str(ROOT / "resource"), "resource")]
binaries = []
# app.py 用 sys.path 动态导入了 tools 下的两个模块，显式声明避免漏收。
hiddenimports = ["stone_selector", "battle_runner", "decompose_runner"]

# MaaFramework 的原生 DLL 与 ADB 代理二进制都在包目录里，必须一并收集。
for package in ("maa", "MaaAgentBinary", "maaagentbinary"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:  # pragma: no cover - 包不存在时跳过
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT), str(ROOT / "tools")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "matplotlib",
        "pandas",
        "IPython",
        "pytest",
        "setuptools",
        # 当前系统 Python 还安装了深度学习/数据工具；本项目完全不使用它们。
        # 显式排除可避免 PyInstaller 钩子把数 GB 的无关运行库带进单文件包。
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "numba",
        "llvmlite",
        "sympy",
        "fsspec",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        icon=str(ROOT / "resource" / "app_icon.ico"),
        debug=False,
        strip=False,
        upx=False,
        console=CONSOLE,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        icon=str(ROOT / "resource" / "app_icon.ico"),
        debug=False,
        strip=False,
        upx=False,
        console=CONSOLE,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
