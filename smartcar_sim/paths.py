"""路径与临时目录管理：保证传给 gcc/sim.exe 的所有路径 100% ASCII。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _resource_root() -> Path:
    """资源根目录：开发态用源码目录，打包态用 bundle 目录。

    PyInstaller 把 --add-data 的资源放到 sys._MEIPASS（onedir 为 _internal/）。
    csim/ 和 assets/ 运行时都要读，必须能在两种模式下定位。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


ROOT = _resource_root()
CSIM_DIR = ROOT / "csim"
ASSETS_DIR = ROOT / "assets"

_FALLBACK_TMP = Path("C:/SmartcarSimTmp")


def _is_ascii(s: str) -> bool:
    return s.isascii()


def ensure_ascii_dir() -> Path:
    """返回一个纯 ASCII 路径的可写临时根目录。

    %TEMP% 含非 ASCII（如中文用户名）时回落到 C:\\SmartcarSimTmp。
    """
    tmp = Path(tempfile.gettempdir())
    base = tmp if _is_ascii(str(tmp)) else _FALLBACK_TMP
    d = base / "smartcar_sim"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_work_dir(prefix: str) -> Path:
    """在 ASCII 临时根下创建一个新的独立工作目录。"""
    root = ensure_ascii_dir()
    return Path(tempfile.mkdtemp(prefix=prefix + "_", dir=root))


def cleanup_old_runs(keep: int = 5) -> None:
    """按修改时间清理旧的 run_* 目录，保留最近 keep 个。"""
    root = ensure_ascii_dir()
    runs = sorted(
        (p for p in root.glob("run_*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in runs[keep:]:
        shutil.rmtree(p, ignore_errors=True)


def find_gcc() -> str | None:
    """定位 gcc：优先 PATH，其次常见安装位置。"""
    exe = shutil.which("gcc")
    if exe:
        return exe
    for cand in (r"C:\MinGW\bin\gcc.exe", r"C:\mingw64\bin\gcc.exe"):
        if os.path.isfile(cand):
            return cand
    return None
