"""编译用户 C 代码 + harness 为 sim.exe。

策略：把用户 *.c 和 csim 一起拷到 ASCII 临时目录，用相对裸文件名调 gcc，
彻底规避 GBK 代码页 + 老 gcc 对 UTF-8 中文路径的问题。
用户文件名若含非 ASCII，改名为 u0.c/u1.c 并记录映射，供诊断回跳。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..paths import CSIM_DIR, find_gcc, new_work_dir
from .diagnostics import CompileResult, friendly_link_error, parse_gcc_output

_CFLAGS = [
    "-std=gnu99", "-O1", "-Wall", "-Wextra",
    "-fno-strict-aliasing", "-static",
]
_CREATE_NO_WINDOW = 0x08000000


def _stage_sources(user_files: list[Path], work: Path) -> tuple[list[str], dict[str, str]]:
    """把用户源文件拷入 work，返回 (编译文件名列表, 文件名->原路径映射)。"""
    compile_names: list[str] = []
    file_map: dict[str, str] = {}
    for i, src in enumerate(user_files):
        name = src.name if src.name.isascii() else f"u{i}.c"
        shutil.copyfile(src, work / name)
        compile_names.append(name)
        file_map[name] = str(src)
    return compile_names, file_map


def compile_sources(
    user_files: list[Path],
    img_w: int,
    img_h: int,
    gcc: str | None = None,
    work: Path | None = None,
) -> CompileResult:
    """同步编译。返回 CompileResult（含 exe 路径或诊断）。"""
    gcc = gcc or find_gcc()
    if not gcc:
        return CompileResult(False, None, friendly_error="未找到 gcc，请安装 MinGW 或在设置里指定路径。")

    work = work or new_work_dir("build")
    # 拷 harness（sim_main.c/sim_api.c + 头文件）
    for f in ("sim_main.c", "sim_api.c", "sim_api.h"):
        shutil.copyfile(CSIM_DIR / f, work / f)

    compile_names, file_map = _stage_sources(user_files, work)
    exe_path = work / "sim.exe"

    cmd = (
        [gcc, *_CFLAGS, f"-DIMG_W={img_w}", f"-DIMG_H={img_h}", "-I."]
        + ["sim_main.c", "sim_api.c"]
        + compile_names
        + ["-o", "sim.exe"]
    )
    proc = subprocess.run(
        cmd, cwd=work, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL,  # noconsole 打包下 stdin 句柄无效，必须显式重定向
        creationflags=_CREATE_NO_WINDOW,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    diags = parse_gcc_output(output, file_map)

    if proc.returncode == 0 and exe_path.exists():
        return CompileResult(True, exe_path, diags, output)

    friendly = friendly_link_error(output)
    return CompileResult(False, None, diags, output, friendly)
