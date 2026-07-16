"""从入口 .c 出发扫描 #include "xxx.h" 依赖，收集要参与编译的本地文件。

只认引号形式（<> 是系统头不管）。每个头在其 includer 同目录查找；
找到的头若旁边有同名 .c 则一并编译（常见的 utils.h/utils.c 配对）。
找不到的头直接跳过——留给 gcc 报错，天然准确。
sim_api.h 由 harness 提供，特判排除。
"""
from __future__ import annotations

import re
from pathlib import Path

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.M)


def _read_source(p: Path) -> str:
    raw = p.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def scan_includes(entry: Path) -> tuple[list[Path], list[Path]]:
    """返回 (c_files, h_files)。c_files 含 entry 本身且排首位，均为 resolve 后路径。"""
    entry = entry.resolve()
    c_files: list[Path] = [entry]
    h_files: list[Path] = []
    seen: set[Path] = {entry}
    queue: list[Path] = [entry]

    while queue:
        cur = queue.pop()
        try:
            text = _read_source(cur)
        except OSError:
            continue
        for name in _INCLUDE_RE.findall(text):
            if Path(name).name == "sim_api.h":
                continue
            hdr = (cur.parent / name).resolve()
            if hdr in seen or not hdr.is_file():
                continue
            seen.add(hdr)
            h_files.append(hdr)
            queue.append(hdr)
            src = hdr.with_suffix(".c")
            if src not in seen and src.is_file():
                seen.add(src)
                c_files.append(src)
                queue.append(src)

    return c_files, h_files
