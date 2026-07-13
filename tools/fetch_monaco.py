"""下载 monaco-editor 静态文件到 assets/monaco/vs/。

用法：python tools/fetch_monaco.py
需要 npm（已配置国内源则无网络障碍）。
"""
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

MONACO_VERSION = "0.52.2"  # 经典 AMD min/vs 布局的稳定版本
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "assets" / "monaco" / "vs"


def main() -> int:
    if DEST.exists():
        print(f"已存在 {DEST}，如需重新下载请先删除该目录")
        return 0

    work = ROOT / "_monaco_tmp"
    work.mkdir(exist_ok=True)
    try:
        print(f"npm pack monaco-editor@{MONACO_VERSION} ...")
        subprocess.run(
            ["npm", "pack", f"monaco-editor@{MONACO_VERSION}"],
            cwd=work, check=True, shell=sys.platform == "win32",
        )
        tgz = next(work.glob("monaco-editor-*.tgz"))
        print(f"解包 {tgz.name} ...")
        with tarfile.open(tgz) as tf:
            members = [m for m in tf.getmembers() if m.name.startswith("package/min/vs/")]
            tf.extractall(work, members=members)
        src = work / "package" / "min" / "vs"
        # 验证是经典 AMD 布局
        if not (src / "loader.js").exists() or not (src / "basic-languages" / "cpp" / "cpp.js").exists():
            print("错误：解包结果不是经典 AMD 布局（缺 loader.js 或 basic-languages/cpp）")
            return 1
        DEST.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(DEST))
        print(f"完成：{DEST}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
