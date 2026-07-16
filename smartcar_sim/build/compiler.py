"""编译用户 C 代码 + harness 为 sim.exe。

策略：把用户 *.c 和 csim 一起拷到 ASCII 临时目录，用相对裸文件名调 gcc，
彻底规避 GBK 代码页 + 老 gcc 对 UTF-8 中文路径的问题。
用户文件名若含非 ASCII，改名为 u0.c/u1.c 并记录映射，供诊断回跳。

提速：harness（sim_main/sim_api）内容与宏不变时复用磁盘 .o 缓存；
链接用 -static-libgcc 替代 -static（msvcrt 是系统库，免全静态链接开销）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from ..paths import CSIM_DIR, ensure_ascii_dir, find_gcc, new_work_dir
from .diagnostics import CompileResult, friendly_link_error, parse_gcc_output

_CFLAGS = [
    "-std=gnu99", "-O1", "-Wall", "-Wextra",
    "-fno-strict-aliasing", "-static-libgcc",
]
_HARNESS_SRCS = ("sim_main.c", "sim_api.c")
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


def _harness_cache_key(gcc: str, img_w: int, img_h: int) -> str:
    """缓存 key：gcc 变了/升级了、宏变了、harness 源码变了都会失效。"""
    h = hashlib.sha1()
    h.update(gcc.encode("utf-8", "replace"))
    try:
        h.update(str(os.path.getmtime(gcc)).encode())
    except OSError:
        pass
    h.update(f"{img_w}x{img_h}".encode())
    for f in (*_HARNESS_SRCS, "sim_api.h"):
        h.update((CSIM_DIR / f).read_bytes())
    return h.hexdigest()[:16]


def _get_harness_objs(gcc: str, img_w: int, img_h: int) -> list[Path] | None:
    """返回缓存的 harness .o 列表；未命中则编译并落盘，失败返回 None。"""
    cache = ensure_ascii_dir() / "obj_cache" / _harness_cache_key(gcc, img_w, img_h)
    objs = [cache / (Path(s).stem + ".o") for s in _HARNESS_SRCS]
    if all(o.is_file() for o in objs):
        return objs

    work = new_work_dir("objc")
    for f in (*_HARNESS_SRCS, "sim_api.h"):
        shutil.copyfile(CSIM_DIR / f, work / f)
    cmd = [gcc, *_CFLAGS, f"-DIMG_W={img_w}", f"-DIMG_H={img_h}", "-I.", "-c", *_HARNESS_SRCS]
    proc = subprocess.run(
        cmd, cwd=work, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL,
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        shutil.rmtree(work, ignore_errors=True)
        return None
    cache.mkdir(parents=True, exist_ok=True)
    for o in objs:
        # 临时名 + replace 原子落盘，防多实例同时写坏缓存
        tmp = cache / (o.name + f".tmp{os.getpid()}")
        shutil.copyfile(work / o.name, tmp)
        os.replace(tmp, o)
    shutil.rmtree(work, ignore_errors=True)
    return objs


def compile_sources(
    user_files: list[Path],
    img_w: int,
    img_h: int,
    gcc: str | None = None,
    work: Path | None = None,
    header_files: list[Path] | None = None,
) -> CompileResult:
    """同步编译。返回 CompileResult（含 exe 路径或诊断）。"""
    gcc = gcc or find_gcc()
    if not gcc:
        return CompileResult(False, None, friendly_error="未找到 gcc，请安装 MinGW 或在设置里指定路径。")

    work = work or new_work_dir("build")
    shutil.copyfile(CSIM_DIR / "sim_api.h", work / "sim_api.h")

    # 用户头文件平铺拷入（源码里 #include 引用原名，不能改名）。
    # 同名冲突或带路径的 include（"inc/x.h"）由下面的 -I 原目录回退兜住。
    file_map: dict[str, str] = {}
    for h in header_files or []:
        if h.name not in file_map:
            shutil.copyfile(h, work / h.name)
            file_map[h.name] = str(h)

    compile_names, src_map = _stage_sources(user_files, work)
    file_map.update(src_map)
    exe_path = work / "sim.exe"

    # 原始目录作为额外 include 路径：让 "inc/x.h"、"../x.h" 这类
    # 带路径的 include 能解析到用户原文件（非 ASCII 路径时老 gcc 可能
    # 找不到，属已知限制；平铺拷贝已覆盖最常见的同目录 include）
    extra_incs: list[str] = []
    for p in (*user_files, *(header_files or [])):
        d = str(p.parent)
        if d not in extra_incs:
            extra_incs.append(d)

    # harness 优先用 .o 缓存；编不出（异常 gcc 环境）回退源码一起编
    harness_objs = _get_harness_objs(gcc, img_w, img_h)
    if harness_objs:
        harness_inputs = [str(o) for o in harness_objs]
    else:
        for f in _HARNESS_SRCS:
            shutil.copyfile(CSIM_DIR / f, work / f)
        harness_inputs = list(_HARNESS_SRCS)

    cmd = (
        [gcc, *_CFLAGS, f"-DIMG_W={img_w}", f"-DIMG_H={img_h}", "-I."]
        + [f"-I{d}" for d in extra_incs]
        + harness_inputs
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
