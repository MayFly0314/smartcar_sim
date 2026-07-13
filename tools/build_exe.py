"""一键打包为 exe：python tools/build_exe.py

前置：pip install pyinstaller，且已跑过 python tools/fetch_monaco.py。
产物：dist/SmartcarSim/SmartcarSim.exe（onedir，整个文件夹拷走即可运行）。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    monaco = ROOT / "assets" / "monaco" / "vs" / "loader.js"
    if not monaco.exists():
        print("错误：Monaco 静态文件缺失，先运行 python tools/fetch_monaco.py")
        return 1
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("错误：未安装 PyInstaller，先运行 pip install pyinstaller")
        return 1

    # 清理旧产物
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)

    print("开始打包（几分钟）...")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "SmartcarSim.spec", "--noconfirm"],
        cwd=ROOT,
    )
    if r.returncode != 0:
        print("打包失败")
        return r.returncode

    exe = ROOT / "dist" / "SmartcarSim" / "SmartcarSim.exe"
    if exe.exists():
        size = sum(f.stat().st_size for f in (ROOT / "dist" / "SmartcarSim").rglob("*")) / 1e6
        print(f"\n完成 ✓  {exe}")
        print(f"整个 dist/SmartcarSim/ 文件夹约 {size:.0f} MB，拷到别的机器可直接双击运行")
        return 0
    print("打包结束但未找到 exe")
    return 1


if __name__ == "__main__":
    sys.exit(main())
