"""draw.txt / frames_out.bin 解析 -> 帧结果数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def _unescape(s: str) -> str:
    """%xx 为字节转义（C 侧 write_escaped 按字节写 UTF-8），按字节收集后整体解码。"""
    if "%" not in s:
        return s
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        if s[i] == "%" and i + 2 < n:
            try:
                out.append(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out += s[i].encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


@dataclass
class DrawCmd:
    kind: str            # P L R C X T
    args: tuple          # 数值参数
    color: int = 0       # 0xRRGGBB
    text: str = ""       # 仅 T


@dataclass
class FrameResult:
    index: int
    cmds: list[DrawCmd] = field(default_factory=list)
    watches: dict[str, float] = field(default_factory=dict)
    tags: list[tuple[int, int, str]] = field(default_factory=list)  # (x, y, text)
    t_us: float = 0.0


@dataclass
class RunResult:
    frames: list[FrameResult]
    processed: np.ndarray | None   # (N, H, W) uint8，可能因崩溃不完整
    logs: list[tuple[int, str]]    # (帧号, 文本)
    crashed: bool = False
    crash_frame: int = -1
    exit_code: int = 0
    error_msg: str = ""

    @property
    def frame_count(self) -> int:
        return len(self.frames)


def parse_draw_file(path: Path) -> list[FrameResult]:
    """解析 draw.txt。协议：指令行在前，F 行收尾该帧。"""
    frames: list[FrameResult] = []
    cur = FrameResult(index=0)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return frames

    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        try:
            if tag == "F" and len(parts) >= 2:
                cur.index = int(parts[1])
                cur.t_us = float(parts[2]) if len(parts) >= 3 else 0.0
                frames.append(cur)
                cur = FrameResult(index=cur.index + 1)
            elif tag == "P" and len(parts) == 4:
                cur.cmds.append(DrawCmd("P", (int(parts[1]), int(parts[2])), int(parts[3], 16)))
            elif tag == "L" and len(parts) == 6:
                cur.cmds.append(DrawCmd("L", tuple(int(v) for v in parts[1:5]), int(parts[5], 16)))
            elif tag == "R" and len(parts) == 6:
                cur.cmds.append(DrawCmd("R", tuple(int(v) for v in parts[1:5]), int(parts[5], 16)))
            elif tag == "C" and len(parts) == 5:
                cur.cmds.append(DrawCmd("C", tuple(int(v) for v in parts[1:4]), int(parts[4], 16)))
            elif tag == "X" and len(parts) == 5:
                cur.cmds.append(DrawCmd("X", tuple(int(v) for v in parts[1:4]), int(parts[4], 16)))
            elif tag == "T" and len(parts) >= 5:
                cur.cmds.append(
                    DrawCmd("T", (int(parts[1]), int(parts[2])), int(parts[3], 16),
                            _unescape(parts[4]))
                )
            elif tag == "V" and len(parts) == 3:
                cur.watches[_unescape(parts[1])] = float(parts[2])
            elif tag == "A" and len(parts) >= 3:
                # 空文本时行尾无第 4 段
                cur.tags.append((int(parts[1]), int(parts[2]),
                                 _unescape(parts[3]) if len(parts) >= 4 else ""))
        except (ValueError, IndexError):
            continue  # 坏行容错

    # 尾部无 F 行的残帧（崩溃时）也保留
    if cur.cmds or cur.watches or cur.tags:
        frames.append(cur)
    return frames


def load_processed_frames(path: Path, w: int, h: int) -> np.ndarray | None:
    """读 frames_out.bin -> (N, H, W)；不完整的最后一帧丢弃。"""
    try:
        raw = np.fromfile(path, dtype=np.uint8)
    except (FileNotFoundError, OSError):
        return None
    per = w * h
    n = raw.size // per
    if n == 0:
        return None
    return raw[: n * per].reshape(n, h, w)


def parse_stdout_logs(text: str) -> tuple[list[tuple[int, str]], int]:
    """解析 stdout：G 行为日志，F 行为进度。返回 (logs, 最后完成帧号)。"""
    logs: list[tuple[int, str]] = []
    last_done = -1
    for line in text.splitlines():
        if line.startswith("G "):
            rest = line[2:]
            sp = rest.find(" ")
            if sp > 0:
                try:
                    logs.append((int(rest[:sp]), rest[sp + 1:]))
                    continue
                except ValueError:
                    pass
            logs.append((-1, rest))
        elif line.startswith("F "):
            try:
                last_done = int(line[2:].strip())
            except ValueError:
                pass
        elif line.strip():
            logs.append((-1, line))  # 用户裸 printf
    return logs, last_done
